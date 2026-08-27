import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from flask import current_app, url_for
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.documentos import (
    ANEXO_ESTADO_ACTIVO,
    ANEXO_ESTADO_APROBADO,
    ANEXO_ESTADO_ELIMINADO,
    ANEXO_TIPO_XLSX,
    Documento,
    DocumentoEdicion,
    DocumentoEdicionEvento,
    DocumentoVersion,
    DocumentoVersionAnexo,
    ESTADO_EDICION_ACTIVA,
    ESTADO_EDICION_EXPIRADA,
)
from app.services.document_versioning_service import get_preparation_version
from app.services.office_document_profile import XLSX_MIME, get_onlyoffice_document_profile, get_onlyoffice_profile_by_extension
from app.services.onlyoffice_document_edit_service import (
    CALLBACK_STATUS_CLOSED_NO_CHANGES,
    CALLBACK_STATUS_EDITING,
    CALLBACK_STATUS_SAVE_FINAL,
    CALLBACK_STATUS_FORCE_SAVE,
    EDITABLE_VERSION_STATES,
    OnlyOfficeEditCallbackError,
    OnlyOfficeEditConflictError,
    OnlyOfficeEditForbiddenError,
    OnlyOfficeEditSessionService,
    record_edit_event,
    user_is_document_cycle_participant,
)
from app.services.onlyoffice_document_view_service import (
    OnlyOfficeDisabledError,
    OnlyOfficeDocumentViewContext,
    OnlyOfficeInvalidDocumentError,
    OnlyOfficeUnavailableError,
    onlyoffice_document_key,
)
from app.services.onlyoffice_health_service import OnlyOfficeHealthService
from app.services.onlyoffice_jwt_service import (
    generate_onlyoffice_callback_token,
    generate_onlyoffice_document_token,
    sign_onlyoffice_config,
)
from app.services.storage_service import (
    DocumentStorageError,
    StoredDocumentFile,
    apply_stored_file_metadata,
    file_digest_and_size,
    prepare_document_file_replacement,
    resolve_document_path,
    restore_document_file_replacement,
    finalize_document_file_replacement,
    store_document_file,
    validate_onlyoffice_file_path,
)


class DocumentAttachmentError(ValueError):
    status_code = 400


class DocumentAttachmentForbiddenError(DocumentAttachmentError):
    status_code = 403


@dataclass(frozen=True)
class DocumentAttachmentEditContext:
    documento: Documento
    version: DocumentoVersion
    anexo: DocumentoVersionAnexo
    edicion: DocumentoEdicion
    editor_config: dict
    public_api_url: str
    csp_origin: str
    heartbeat_seconds: int
    force_save_debounce_seconds: int


def _now():
    return datetime.now(timezone.utc)


def _expiry_from(now):
    return now + timedelta(seconds=int(current_app.config["ONLYOFFICE_EDIT_LOCK_TTL_SECONDS"]))


def _event_fingerprint(*parts):
    normalized = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ensure_xlsx_upload(file_storage):
    filename = secure_filename(file_storage.filename if file_storage else "")
    if not filename or "." not in filename:
        raise DocumentStorageError("El anexo debe tener extension XLSX.")
    extension = filename.rsplit(".", 1)[1].lower()
    if extension != "xlsx":
        raise DocumentStorageError("Solo se permiten anexos XLSX sin macros.")


def _ensure_principal_docx(version_doc):
    profile = get_onlyoffice_document_profile(version_doc)
    if not profile or profile.extension != "docx":
        raise DocumentAttachmentError("Los anexos XLSX solo pueden asociarse a una version principal DOCX.")


def list_active_attachments(version_doc):
    if not version_doc:
        return []
    return (
        DocumentoVersionAnexo.query
        .filter(
            DocumentoVersionAnexo.documento_version_id == version_doc.id,
            DocumentoVersionAnexo.empresa_id == version_doc.empresa_id,
            DocumentoVersionAnexo.estado != ANEXO_ESTADO_ELIMINADO,
        )
        .order_by(DocumentoVersionAnexo.id.asc())
        .all()
    )


def can_user_edit_attachment(documento, version, anexo, user, *, enforce_lock=True):
    if not documento or not version or not anexo or not user:
        return False
    if anexo.empresa_id != version.empresa_id or anexo.documento_version_id != version.id:
        return False
    if int(documento.empresa_id) != int(user.empresa_id):
        return False
    if version.estado not in EDITABLE_VERSION_STATES:
        return False
    if anexo.estado != ANEXO_ESTADO_ACTIVO or anexo.inmutable:
        return False
    preparation = get_preparation_version(documento)
    if not preparation or int(preparation.id) != int(version.id):
        return False
    if not user_is_document_cycle_participant(documento, version, user):
        return False
    if not enforce_lock:
        return True
    active = get_active_attachment_edit(anexo.id)
    return not bool(active and int(active.usuario_id) != int(user.id))


def get_active_attachment_edit(anexo_id):
    now = _now()
    stale = (
        DocumentoEdicion.query
        .filter(
            DocumentoEdicion.documento_version_anexo_id == anexo_id,
            DocumentoEdicion.estado == ESTADO_EDICION_ACTIVA,
            DocumentoEdicion.fecha_expiracion <= now,
        )
        .all()
    )
    for edicion in stale:
        edicion.estado = ESTADO_EDICION_EXPIRADA
        edicion.fecha_liberacion = now
        record_edit_event(edicion=edicion, tipo="SESION_EXPIRADA", detalle="Anexo expirado por timeout de heartbeat.")
    if stale:
        db.session.commit()
    return (
        DocumentoEdicion.query
        .filter_by(documento_version_anexo_id=anexo_id, estado=ESTADO_EDICION_ACTIVA)
        .first()
    )


class DocumentAttachmentService:
    def add_attachment(self, *, documento, version_doc, usuario, file_storage):
        _ensure_principal_docx(version_doc)
        self._ensure_can_mutate(documento=documento, version_doc=version_doc, usuario=usuario)
        _ensure_xlsx_upload(file_storage)
        stored = store_document_file(file_storage, documento=documento, version=version_doc.version)
        anexo = DocumentoVersionAnexo(
            empresa_id=documento.empresa_id,
            public_id=uuid4().hex,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            nombre_visible=stored.original_name,
            archivo_nombre_original=stored.original_name,
            archivo_nombre_guardado=stored.stored_name,
            archivo_storage_path=stored.storage_path,
            archivo_mime=XLSX_MIME,
            archivo_size=stored.size,
            archivo_sha256=stored.sha256,
            tipo=ANEXO_TIPO_XLSX,
            estado=ANEXO_ESTADO_ACTIVO,
            creado_por_id=usuario.id,
            actualizado_por_id=usuario.id,
            inmutable=False,
            metadata_json={"source": "upload"},
        )
        db.session.add(anexo)
        db.session.flush()
        return anexo

    def replace_attachment(self, *, anexo, usuario, file_storage):
        self._ensure_can_mutate(documento=anexo.documento, version_doc=anexo.documento_version, usuario=usuario)
        _ensure_xlsx_upload(file_storage)
        stored = store_document_file(file_storage, documento=anexo.documento, version=anexo.documento_version.version)
        anexo.nombre_visible = stored.original_name
        anexo.archivo_nombre_original = stored.original_name
        anexo.archivo_nombre_guardado = stored.stored_name
        anexo.archivo_storage_path = stored.storage_path
        anexo.archivo_mime = XLSX_MIME
        anexo.archivo_size = stored.size
        anexo.archivo_sha256 = stored.sha256
        anexo.actualizado_por_id = usuario.id
        anexo.metadata_json = {**(anexo.metadata_json or {}), "last_action": "replace"}
        db.session.flush()
        return anexo

    def delete_attachment(self, *, anexo, usuario):
        self._ensure_can_mutate(documento=anexo.documento, version_doc=anexo.documento_version, usuario=usuario)
        anexo.estado = ANEXO_ESTADO_ELIMINADO
        anexo.eliminado_por_id = usuario.id
        anexo.eliminado_en = _now()
        anexo.actualizado_por_id = usuario.id
        anexo.metadata_json = {**(anexo.metadata_json or {}), "last_action": "delete"}
        db.session.flush()
        return anexo

    def approve_attachments(self, *, version_doc, usuario):
        approved = []
        for anexo in list_active_attachments(version_doc):
            anexo.estado = ANEXO_ESTADO_APROBADO
            anexo.inmutable = True
            anexo.aprobado_por_id = usuario.id
            anexo.aprobado_en = _now()
            anexo.actualizado_por_id = usuario.id
            anexo.metadata_json = {**(anexo.metadata_json or {}), "approved_with_version": version_doc.version}
            approved.append(anexo)
        return approved

    def attachment_hash_manifest(self, version_doc):
        return [
            {
                "public_id": anexo.public_id,
                "filename": anexo.archivo_nombre_original,
                "mime": anexo.archivo_mime,
                "size": anexo.archivo_size,
                "sha256": anexo.archivo_sha256,
                "estado": anexo.estado,
            }
            for anexo in list_active_attachments(version_doc)
        ]

    def resolve_attachment_path(self, anexo):
        if anexo.empresa_id != anexo.documento_version.empresa_id:
            raise DocumentStorageError("Anexo fuera de empresa.")
        profile = get_onlyoffice_profile_by_extension("xlsx")
        path = resolve_document_path(anexo.archivo_storage_path)
        validate_onlyoffice_file_path(path, profile)
        sha256, size = file_digest_and_size(path)
        if sha256 != anexo.archivo_sha256 or int(size) != int(anexo.archivo_size):
            raise DocumentStorageError("El anexo no coincide con la metadata registrada.")
        return path

    def build_view_context(self, *, public_id, user):
        anexo = self._load_attachment(public_id=public_id, user=user)
        documento = anexo.documento
        version = anexo.documento_version
        self.resolve_attachment_path(anexo)
        self._ensure_onlyoffice_available(edit=False)
        document_url = self._build_document_url(anexo)
        document_key = onlyoffice_document_key(
            empresa_id=anexo.empresa_id,
            documento_id=anexo.documento_id,
            version_id=anexo.documento_version_id,
            archivo_sha256=anexo.archivo_sha256,
            source_id=anexo.public_id,
        )
        config = self._build_editor_config(anexo, document_url, document_key, user, mode="view")
        config["token"] = sign_onlyoffice_config(config)
        return OnlyOfficeDocumentViewContext(
            documento=documento,
            version=version,
            editor_config=config,
            public_api_url=current_app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/") + "/web-apps/apps/api/documents/api.js",
            csp_origin=current_app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/"),
        )

    def build_edit_context(self, *, public_id, user):
        anexo = self._load_attachment(public_id=public_id, user=user)
        documento = anexo.documento
        version = anexo.documento_version
        if not can_user_edit_attachment(documento, version, anexo, user):
            raise OnlyOfficeEditForbiddenError("No puedes editar este anexo XLSX.")
        self.resolve_attachment_path(anexo)
        self._ensure_onlyoffice_available(edit=True)
        edicion = self.acquire_lock(anexo=anexo, user=user)
        document_url = self._build_document_url(anexo)
        callback_url = self._build_callback_url(edicion)
        config = self._build_editor_config(anexo, document_url, edicion.editor_key, user, mode="edit", callback_url=callback_url)
        config["token"] = sign_onlyoffice_config(config)
        return DocumentAttachmentEditContext(
            documento=documento,
            version=version,
            anexo=anexo,
            edicion=edicion,
            editor_config=config,
            public_api_url=current_app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/") + "/web-apps/apps/api/documents/api.js",
            csp_origin=current_app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/"),
            heartbeat_seconds=int(current_app.config["ONLYOFFICE_EDIT_HEARTBEAT_SECONDS"]),
            force_save_debounce_seconds=int(current_app.config["ONLYOFFICE_FORCE_SAVE_DEBOUNCE_SECONDS"]),
        )

    def acquire_lock(self, *, anexo, user):
        now = _now()
        active = (
            DocumentoEdicion.query
            .filter_by(documento_version_anexo_id=anexo.id, estado=ESTADO_EDICION_ACTIVA)
            .with_for_update(of=DocumentoEdicion)
            .first()
        )
        if active:
            if int(active.usuario_id) != int(user.id):
                raise OnlyOfficeEditConflictError("Anexo en edicion por otro usuario.")
            active.ultima_actividad = now
            active.fecha_expiracion = _expiry_from(now)
            record_edit_event(edicion=active, tipo="BLOQUEO_RENOVADO", detalle="Reutilizacion de sesion activa de anexo.")
            db.session.commit()
            return active
        edicion = DocumentoEdicion(
            empresa_id=anexo.empresa_id,
            public_id=uuid4().hex,
            documento_id=anexo.documento_id,
            documento_version_id=anexo.documento_version_id,
            documento_version_anexo_id=anexo.id,
            usuario_id=user.id,
            editor_key=uuid4().hex,
            estado=ESTADO_EDICION_ACTIVA,
            fecha_inicio=now,
            ultima_actividad=now,
            fecha_expiracion=_expiry_from(now),
            hash_inicial=anexo.archivo_sha256,
            hash_ultimo_guardado=anexo.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.flush()
        record_edit_event(edicion=edicion, tipo="SESION_INICIADA", detalle="Bloqueo exclusivo de anexo adquirido.")
        db.session.commit()
        return edicion

    def save_callback_file(self, *, edicion, payload, final):
        anexo = DocumentoVersionAnexo.query.filter_by(
            id=edicion.documento_version_anexo_id,
            documento_version_id=edicion.documento_version_id,
            empresa_id=edicion.empresa_id,
        ).with_for_update(of=DocumentoVersionAnexo).first()
        if not anexo or anexo.estado != ANEXO_ESTADO_ACTIVO or anexo.inmutable:
            raise OnlyOfficeEditCallbackError("El anexo no esta editable.")
        if payload.get("key") != edicion.editor_key:
            raise OnlyOfficeEditCallbackError("La clave del editor no coincide.")
        result_url = payload.get("url")
        if not result_url:
            raise OnlyOfficeEditCallbackError("Callback de anexo sin URL de resultado.")
        if anexo.archivo_sha256 != edicion.hash_ultimo_guardado:
            raise OnlyOfficeEditCallbackError("La copia del anexo cambio fuera de la sesion.")
        temp_path = self._download_result(result_url)
        old_sha = anexo.archivo_sha256
        old_size = anexo.archivo_size
        replacement = None
        try:
            replacement = prepare_document_file_replacement(anexo, temp_path)
            new_sha = replacement.sha256
            new_size = replacement.size
            if new_sha != old_sha:
                anexo.archivo_sha256 = new_sha
                anexo.archivo_size = new_size
                anexo.archivo_mime = XLSX_MIME
                anexo.actualizado_por_id = edicion.usuario_id
            edicion.hash_ultimo_guardado = new_sha
            edicion.ultimo_guardado_en = _now()
            edicion.error_ultimo_guardado = None
            edicion.ultima_actividad = _now()
            edicion.fecha_expiracion = _expiry_from(edicion.ultima_actividad)
            if final:
                edicion.estado = "LIBERADA"
                edicion.fecha_liberacion = _now()
                edicion.motivo_liberacion = "Guardado final de anexo completado por ONLYOFFICE."
            return replacement
        except Exception:
            anexo.archivo_sha256 = old_sha
            anexo.archivo_size = old_size
            restore_document_file_replacement(replacement)
            raise
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _download_result(self, result_url):
        self._validate_result_url(result_url)
        max_bytes = int(current_app.config["ONLYOFFICE_CALLBACK_DOWNLOAD_MAX_BYTES"])
        request = Request(result_url, headers={"User-Agent": "LabZenISO-ONLYOFFICE-attachment-callback"})
        fd, temp_name = tempfile.mkstemp(prefix="onlyoffice-attachment-", suffix=".xlsx")
        os.close(fd)
        temp_path = Path(temp_name)
        size = 0
        try:
            with urlopen(request, timeout=int(current_app.config["ONLYOFFICE_REQUEST_TIMEOUT_SECONDS"])) as response:
                self._validate_result_url(response.geturl())
                with temp_path.open("ab") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise DocumentStorageError("El anexo devuelto por ONLYOFFICE supera el tamano permitido.")
                        output.write(chunk)
            validate_onlyoffice_file_path(temp_path, get_onlyoffice_profile_by_extension("xlsx"))
            return temp_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _load_attachment(self, *, public_id, user):
        anexo = DocumentoVersionAnexo.query.filter_by(public_id=public_id, empresa_id=user.empresa_id).first()
        if not anexo or anexo.estado == ANEXO_ESTADO_ELIMINADO:
            raise LookupError("Anexo no encontrado.")
        return anexo

    def _ensure_can_mutate(self, *, documento, version_doc, usuario):
        _ensure_principal_docx(version_doc)
        if documento.empresa_id != usuario.empresa_id or version_doc.empresa_id != usuario.empresa_id:
            raise DocumentAttachmentForbiddenError("No puedes modificar anexos de otra empresa.")
        if version_doc.estado not in EDITABLE_VERSION_STATES:
            raise DocumentAttachmentError("Los anexos solo se modifican en una version activa de trabajo.")
        preparation = get_preparation_version(documento)
        if not preparation or int(preparation.id) != int(version_doc.id):
            raise DocumentAttachmentError("Solo la version activa de trabajo puede modificar anexos.")
        if not user_is_document_cycle_participant(documento, version_doc, usuario):
            raise DocumentAttachmentForbiddenError("Solo un participante asignado puede modificar anexos.")

    def _ensure_onlyoffice_available(self, *, edit):
        if not current_app.config.get("ONLYOFFICE_ENABLED") or (edit and not current_app.config.get("ONLYOFFICE_EDIT_ENABLED")):
            raise OnlyOfficeDisabledError("ONLYOFFICE esta deshabilitado.")
        health = OnlyOfficeHealthService(current_app).check()
        if not health.available:
            raise OnlyOfficeUnavailableError(health.message or "ONLYOFFICE no esta disponible.")

    def _build_document_url(self, anexo):
        token = generate_onlyoffice_document_token(
            empresa_id=anexo.empresa_id,
            documento_id=anexo.documento_id,
            version_id=anexo.documento_version_id,
            archivo_sha256=anexo.archivo_sha256,
            attachment_public_id=anexo.public_id,
        )
        path = url_for("onlyoffice_integration.attachment_file", public_id=anexo.public_id)
        return current_app.config["ONLYOFFICE_CALLBACK_BASE_URL"].rstrip("/") + path + "?" + urlencode({"token": token})

    def _build_callback_url(self, edicion):
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)
        path = url_for("onlyoffice_integration.edit_callback", public_id=edicion.public_id)
        return current_app.config["ONLYOFFICE_CALLBACK_BASE_URL"].rstrip("/") + path + "?" + urlencode({"token": token})

    def _build_editor_config(self, anexo, document_url, document_key, user, *, mode, callback_url=None):
        config = {
            "document": {
                "fileType": "xlsx",
                "key": document_key,
                "title": Path(anexo.archivo_nombre_original).name,
                "url": document_url,
                "permissions": {
                    "comment": False,
                    "copy": True,
                    "download": False,
                    "edit": mode == "edit",
                    "fillForms": False,
                    "modifyFilter": False,
                    "print": False,
                    "review": False,
                },
            },
            "documentType": "cell",
            "editorConfig": {
                "mode": mode,
                "lang": "es",
                "user": {
                    "id": str(user.id),
                    "name": f"{user.nombre} {user.apellido}".strip(),
                },
                "customization": {
                    "autosave": mode == "edit",
                    "forcesave": mode == "edit",
                    "comments": False,
                    "compactToolbar": False,
                    "hideRightMenu": mode != "edit",
                },
            },
            "height": "100%",
            "type": "desktop",
            "width": "100%",
        }
        if callback_url:
            config["editorConfig"]["callbackUrl"] = callback_url
            config["editorConfig"]["coEditing"] = {"mode": "strict", "change": False}
        return config

    def _validate_result_url(self, result_url):
        parsed = urlparse(result_url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise OnlyOfficeEditCallbackError("URL de resultado no permitida.")
        allowed_hosts = set(current_app.config["ONLYOFFICE_ALLOWED_HOSTS"])
        internal_host = urlparse(current_app.config["ONLYOFFICE_INTERNAL_URL"]).hostname
        public_host = urlparse(current_app.config["ONLYOFFICE_PUBLIC_URL"]).hostname
        allowed_hosts.update(host for host in (internal_host, public_host) if host)
        if parsed.hostname not in allowed_hosts:
            raise OnlyOfficeEditCallbackError("Host de resultado no autorizado.")
