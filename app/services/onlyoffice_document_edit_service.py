import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from flask import current_app, url_for

from app.extensions import db
from app.models.documentos import (
    Documento,
    DocumentoEdicion,
    DocumentoEdicionEvento,
    DocumentoVersion,
    ESTADO_EDICION_ACTIVA,
    ESTADO_EDICION_CANCELADA,
    ESTADO_EDICION_ERROR,
    ESTADO_EDICION_EXPIRADA,
    ESTADO_EDICION_LIBERADA,
    ESTADO_EN_ACTUALIZACION,
    ESTADO_EN_ELABORACION,
)
from app.security.permissions import user_has_permission
from app.services.document_versioning_service import get_preparation_version
from app.services.onlyoffice_document_view_service import (
    OnlyOfficeDisabledError,
    OnlyOfficeDocumentViewError,
    OnlyOfficeInvalidDocumentError,
    OnlyOfficeUnavailableError,
    is_onlyoffice_supported_version,
    resolve_onlyoffice_source_path,
)
from app.services.office_document_profile import get_onlyoffice_document_profile
from app.services.onlyoffice_health_service import OnlyOfficeHealthService
from app.services.onlyoffice_jwt_service import (
    generate_onlyoffice_callback_token,
    generate_onlyoffice_document_token,
    sign_onlyoffice_config,
)
from app.services.storage_service import (
    DocumentStorageError,
    finalize_document_file_replacement,
    prepare_document_file_replacement,
    restore_document_file_replacement,
    validate_onlyoffice_file_path,
)


CALLBACK_STATUS_EDITING = 1
CALLBACK_STATUS_SAVE_FINAL = 2
CALLBACK_STATUS_SAVE_ERROR = 3
CALLBACK_STATUS_CLOSED_NO_CHANGES = 4
CALLBACK_STATUS_FORCE_SAVE = 6
CALLBACK_STATUS_FORCE_SAVE_ERROR = 7
SAVEABLE_CALLBACK_STATUSES = {CALLBACK_STATUS_SAVE_FINAL, CALLBACK_STATUS_FORCE_SAVE}
ERROR_CALLBACK_STATUSES = {CALLBACK_STATUS_SAVE_ERROR, CALLBACK_STATUS_FORCE_SAVE_ERROR}
SUPPORTED_CALLBACK_STATUSES = {
    CALLBACK_STATUS_EDITING,
    CALLBACK_STATUS_SAVE_FINAL,
    CALLBACK_STATUS_SAVE_ERROR,
    CALLBACK_STATUS_CLOSED_NO_CHANGES,
    CALLBACK_STATUS_FORCE_SAVE,
    CALLBACK_STATUS_FORCE_SAVE_ERROR,
}
EDITABLE_VERSION_STATES = {ESTADO_EN_ELABORACION, ESTADO_EN_ACTUALIZACION}
ONLYOFFICE_EDIT_ADMIN_PERMISSION = "documentos.ver_historial"


class OnlyOfficeEditError(OnlyOfficeDocumentViewError):
    status_code = 409


class OnlyOfficeEditConflictError(OnlyOfficeEditError):
    status_code = 409


class OnlyOfficeEditForbiddenError(OnlyOfficeEditError):
    status_code = 403


class OnlyOfficeEditCallbackError(ValueError):
    status_code = 400
    callback_error = 1


@dataclass(frozen=True)
class OnlyOfficeDocumentEditContext:
    documento: Documento
    version: DocumentoVersion
    edicion: DocumentoEdicion
    editor_config: dict
    public_api_url: str
    csp_origin: str
    heartbeat_seconds: int
    force_save_debounce_seconds: int


@dataclass(frozen=True)
class ActiveEditInfo:
    edicion: DocumentoEdicion | None
    editable_by_current_user: bool
    blocked_by_other_user: bool


def _now():
    return datetime.now(timezone.utc)


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _expiry_from(now):
    return now + timedelta(seconds=int(current_app.config["ONLYOFFICE_EDIT_LOCK_TTL_SECONDS"]))


def _event_fingerprint(*parts):
    normalized = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def record_edit_event(
    *,
    edicion,
    tipo,
    detalle=None,
    status_callback=None,
    fingerprint=None,
    usuario_id=None,
    ip=None,
    user_agent=None,
):
    if fingerprint and DocumentoEdicionEvento.query.filter_by(fingerprint=fingerprint).first():
        return None

    event = DocumentoEdicionEvento(
        empresa_id=edicion.empresa_id,
        edicion_id=edicion.id,
        documento_id=edicion.documento_id,
        documento_version_id=edicion.documento_version_id,
        usuario_id=usuario_id if usuario_id is not None else edicion.usuario_id,
        tipo=tipo,
        fecha_evento=_now(),
        status_callback=status_callback,
        fingerprint=fingerprint,
        detalle=(detalle or "").strip() or None,
        ip=ip,
        user_agent=user_agent,
    )
    db.session.add(event)
    return event


def expire_stale_active_edits(now=None):
    now = now or _now()
    stale = (
        DocumentoEdicion.query
        .filter(
            DocumentoEdicion.estado == ESTADO_EDICION_ACTIVA,
            DocumentoEdicion.fecha_expiracion <= now,
        )
        .all()
    )
    for edicion in stale:
        edicion.estado = ESTADO_EDICION_EXPIRADA
        edicion.fecha_liberacion = now
        edicion.motivo_liberacion = "Expirada por timeout de heartbeat."
        record_edit_event(edicion=edicion, tipo="SESION_EXPIRADA", detalle=edicion.motivo_liberacion)
    return stale


def get_active_edit_for_version(version_id):
    expire_stale_active_edits()
    return (
        DocumentoEdicion.query
        .filter_by(documento_version_id=version_id, estado=ESTADO_EDICION_ACTIVA)
        .first()
    )


def get_active_edit_info(version_doc, user):
    edicion = get_active_edit_for_version(version_doc.id) if version_doc else None
    return ActiveEditInfo(
        edicion=edicion,
        editable_by_current_user=bool(edicion and int(edicion.usuario_id) == int(user.id)),
        blocked_by_other_user=bool(edicion and int(edicion.usuario_id) != int(user.id)),
    )


def has_blocking_edit(version_doc):
    edicion = get_active_edit_for_version(version_doc.id) if version_doc else None
    return edicion is not None


def user_is_assigned_elaborator(documento, version, user):
    assigned_id = version.elaborado_por_id or documento.elaborado_por_id
    return bool(assigned_id and user and int(assigned_id) == int(user.id))


def user_has_onlyoffice_edit_admin_permission(user):
    return user_has_permission(user, ONLYOFFICE_EDIT_ADMIN_PERMISSION)


def can_user_edit_onlyoffice_version(documento, version, user, *, active_edit_info=None, enforce_lock=True):
    if not documento or not version or not user:
        return False
    if version.empresa_id != documento.empresa_id or version.documento_id != documento.id:
        return False
    if int(documento.empresa_id) != int(user.empresa_id):
        return False
    if not user_has_permission(user, "documentos.editar"):
        return False
    if version.estado not in EDITABLE_VERSION_STATES:
        return False
    if not is_onlyoffice_supported_version(version):
        return False
    preparation = get_preparation_version(documento)
    if not preparation or int(preparation.id) != int(version.id):
        return False
    if not (user_is_assigned_elaborator(documento, version, user) or user_has_onlyoffice_edit_admin_permission(user)):
        return False
    if active_edit_info and active_edit_info.blocked_by_other_user:
        return False
    if not enforce_lock:
        return True
    active = get_active_edit_for_version(version.id)
    return not bool(active and int(active.usuario_id) != int(user.id))


class OnlyOfficeDocumentEditService:
    def __init__(self, app=None):
        self.app = app or current_app

    def build_context(self, *, documento_id, version_id, user):
        documento, version = self._load_editable_version(documento_id, version_id, user)
        self._ensure_onlyoffice_available()
        edicion = self.acquire_lock(documento=documento, version=version, user=user)
        document_url = self._build_document_url(documento, version)
        callback_url = self._build_callback_url(edicion)
        config = self._build_editor_config(documento, version, edicion, document_url, callback_url, user)
        config["token"] = sign_onlyoffice_config(config)
        return OnlyOfficeDocumentEditContext(
            documento=documento,
            version=version,
            edicion=edicion,
            editor_config=config,
            public_api_url=self.app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/") + "/web-apps/apps/api/documents/api.js",
            csp_origin=self.app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/"),
            heartbeat_seconds=int(self.app.config["ONLYOFFICE_EDIT_HEARTBEAT_SECONDS"]),
            force_save_debounce_seconds=int(self.app.config["ONLYOFFICE_FORCE_SAVE_DEBOUNCE_SECONDS"]),
        )

    def _ensure_onlyoffice_available(self):
        if not self.app.config.get("ONLYOFFICE_ENABLED") or not self.app.config.get("ONLYOFFICE_EDIT_ENABLED"):
            raise OnlyOfficeDisabledError("La ediciÃ³n con ONLYOFFICE estÃ¡ deshabilitada.")
        health = OnlyOfficeHealthService(self.app).check()
        if not health.available:
            raise OnlyOfficeUnavailableError(health.message or "ONLYOFFICE no estÃ¡ disponible.")

    def _load_editable_version(self, documento_id, version_id, user):
        documento = Documento.query.filter_by(id=documento_id, empresa_id=user.empresa_id).first()
        if not documento:
            raise LookupError("Documento no encontrado.")
        version = DocumentoVersion.query.filter_by(
            id=version_id,
            documento_id=documento.id,
            empresa_id=user.empresa_id,
        ).first()
        if not version:
            raise LookupError("VersiÃ³n documental no encontrada.")
        self.validate_editable(documento=documento, version=version)
        self.validate_user_can_edit(documento=documento, version=version, user=user)
        return documento, version

    def validate_editable(self, *, documento, version):
        if version.empresa_id != documento.empresa_id or version.documento_id != documento.id:
            raise OnlyOfficeInvalidDocumentError("La versiÃ³n no pertenece al documento indicado.")
        if version.estado not in EDITABLE_VERSION_STATES:
            raise OnlyOfficeEditConflictError("Solo una versiÃ³n EN_ELABORACION puede editarse en ONLYOFFICE.")
        preparation = get_preparation_version(documento)
        if not preparation or preparation.id != version.id:
            raise OnlyOfficeEditConflictError("La versiÃ³n seleccionada no es la versiÃ³n activa de trabajo.")
        resolve_onlyoffice_source_path(version)

    def validate_user_can_edit(self, *, documento, version, user):
        if not (user_is_assigned_elaborator(documento, version, user) or user_has_onlyoffice_edit_admin_permission(user)):
            raise OnlyOfficeEditForbiddenError("Solo el elaborador asignado o un usuario administrativo puede editar el contenido.")

    def acquire_lock(self, *, documento, version, user):
        now = _now()
        expire_stale_active_edits(now)
        active = (
            DocumentoEdicion.query
            .filter_by(documento_version_id=version.id, estado=ESTADO_EDICION_ACTIVA)
            .with_for_update(of=DocumentoEdicion)
            .first()
        )
        if active:
            if int(active.usuario_id) != int(user.id):
                raise OnlyOfficeEditConflictError(
                    f"Documento en ediciÃ³n por {active.usuario.nombre} {active.usuario.apellido or ''}. "
                    "Puedes abrirlo en modo lectura."
                )
            active.ultima_actividad = now
            active.fecha_expiracion = _expiry_from(now)
            record_edit_event(edicion=active, tipo="BLOQUEO_RENOVADO", detalle="ReutilizaciÃ³n de sesiÃ³n activa.")
            db.session.commit()
            return active

        edicion = DocumentoEdicion(
            empresa_id=documento.empresa_id,
            public_id=uuid4().hex,
            documento_id=documento.id,
            documento_version_id=version.id,
            usuario_id=user.id,
            editor_key=uuid4().hex,
            estado=ESTADO_EDICION_ACTIVA,
            fecha_inicio=now,
            ultima_actividad=now,
            fecha_expiracion=_expiry_from(now),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.flush()
        record_edit_event(edicion=edicion, tipo="SESION_INICIADA", detalle="Bloqueo exclusivo adquirido.")
        db.session.commit()
        return edicion

    def _build_document_url(self, documento, version):
        token = generate_onlyoffice_document_token(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            version_id=version.id,
            archivo_sha256=version.archivo_sha256,
        )
        path = url_for("onlyoffice_integration.document_file", version_id=version.id)
        return self.app.config["ONLYOFFICE_CALLBACK_BASE_URL"].rstrip("/") + path + "?" + urlencode({"token": token})

    def _build_callback_url(self, edicion):
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)
        path = url_for("onlyoffice_integration.edit_callback", public_id=edicion.public_id)
        return self.app.config["ONLYOFFICE_CALLBACK_BASE_URL"].rstrip("/") + path + "?" + urlencode({"token": token})

    def _build_editor_config(self, documento, version, edicion, document_url, callback_url, user):
        profile = get_onlyoffice_document_profile(version)
        title = Path(version.archivo_nombre_original or f"{documento.codigo}_v{version.version}.{profile.extension}").name
        return {
            "document": {
                "fileType": profile.file_type,
                "key": edicion.editor_key,
                "title": title,
                "url": document_url,
                "permissions": {
                    "comment": False,
                    "copy": True,
                    "download": False,
                    "edit": True,
                    "fillForms": False,
                    "modifyFilter": False,
                    "print": False,
                    "review": False,
                },
            },
            "documentType": profile.document_type,
            "editorConfig": {
                "mode": "edit",
                "callbackUrl": callback_url,
                "lang": "es",
                "user": {
                    "id": str(user.id),
                    "name": f"{user.nombre} {user.apellido}".strip(),
                },
                "customization": {
                    "autosave": True,
                    "forcesave": True,
                    "comments": False,
                    "compactToolbar": False,
                    "hideRightMenu": False,
                },
                "coEditing": {
                    "mode": "strict",
                    "change": False,
                },
            },
            "height": "100%",
            "type": "desktop",
            "width": "100%",
        }


class OnlyOfficeEditSessionService:
    def get_owned_active_session(self, *, public_id, user):
        edicion = DocumentoEdicion.query.filter_by(
            public_id=public_id,
            empresa_id=user.empresa_id,
            usuario_id=user.id,
        ).first()
        if not edicion:
            raise LookupError("SesiÃ³n de ediciÃ³n no encontrada.")
        if edicion.estado != ESTADO_EDICION_ACTIVA:
            raise OnlyOfficeEditConflictError("La sesiÃ³n de ediciÃ³n no estÃ¡ activa.")
        if _utc(edicion.fecha_expiracion) <= _now():
            edicion.estado = ESTADO_EDICION_EXPIRADA
            edicion.fecha_liberacion = _now()
            record_edit_event(edicion=edicion, tipo="SESION_EXPIRADA", detalle="Heartbeat recibido fuera de TTL.")
            db.session.commit()
            raise OnlyOfficeEditConflictError("La sesiÃ³n de ediciÃ³n estÃ¡ vencida.")
        return edicion

    def heartbeat(self, *, public_id, user):
        edicion = self.get_owned_active_session(public_id=public_id, user=user)
        now = _now()
        edicion.ultima_actividad = now
        edicion.fecha_expiracion = _expiry_from(now)
        record_edit_event(edicion=edicion, tipo="HEARTBEAT", detalle="RenovaciÃ³n de sesiÃ³n.")
        db.session.commit()
        return edicion

    def release(self, *, public_id, user, reason=None, administrative=False):
        query = DocumentoEdicion.query.filter_by(public_id=public_id)
        if not administrative:
            query = query.filter_by(empresa_id=user.empresa_id, usuario_id=user.id)
        else:
            query = query.filter_by(empresa_id=user.empresa_id)
        edicion = query.first()
        if not edicion:
            raise LookupError("SesiÃ³n de ediciÃ³n no encontrada.")
        if edicion.estado == ESTADO_EDICION_ACTIVA:
            release_reason = (reason or "Liberacion voluntaria.").strip()
            is_save_and_close = not administrative and release_reason == "Guardar y cerrar desde editor."
            edicion.estado = ESTADO_EDICION_LIBERADA if is_save_and_close else ESTADO_EDICION_CANCELADA
            edicion.fecha_liberacion = _now()
            edicion.liberado_por_id = user.id
            edicion.motivo_liberacion = release_reason
            record_edit_event(
                edicion=edicion,
                tipo="LIBERACION_ADMINISTRATIVA" if administrative else "LIBERACION_VOLUNTARIA",
                detalle=edicion.motivo_liberacion,
                usuario_id=user.id,
            )
            db.session.commit()
        return edicion

    def force_save(self, *, public_id, user):
        edicion = self.get_owned_active_session(public_id=public_id, user=user)
        command = {"c": "forcesave", "key": edicion.editor_key}
        command["token"] = sign_onlyoffice_config(command)
        payload = json.dumps(command).encode("utf-8")
        command_url = current_app.config["ONLYOFFICE_INTERNAL_URL"].rstrip("/") + "/coauthoring/CommandService.ashx"
        request = Request(
            command_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {command['token']}",
            },
            method="POST",
        )
        try:
            with urlopen(
                request,
                timeout=int(current_app.config["ONLYOFFICE_REQUEST_TIMEOUT_SECONDS"]),
            ) as response:
                raw = response.read(4096)
        except Exception as exc:
            record_edit_event(edicion=edicion, tipo="GUARDADO_FORZADO_ERROR", detalle=str(exc)[:500])
            db.session.commit()
            raise OnlyOfficeEditConflictError("No se pudo solicitar guardado forzado a ONLYOFFICE.") from exc

        result = json.loads(raw.decode("utf-8") or "{}")
        if int(result.get("error", 0)) != 0:
            record_edit_event(edicion=edicion, tipo="GUARDADO_FORZADO_ERROR", detalle=f"CommandService error {result.get('error')}")
            db.session.commit()
            raise OnlyOfficeEditConflictError("ONLYOFFICE rechazÃ³ el guardado forzado.")

        record_edit_event(edicion=edicion, tipo="GUARDADO_FORZADO_SOLICITADO", detalle="CommandService forcesave aceptado.")
        db.session.commit()
        return result


class OnlyOfficeCallbackService:
    def process(self, *, public_id, payload, token_payload):
        edicion = DocumentoEdicion.query.filter_by(public_id=public_id).first()
        if not edicion:
            raise OnlyOfficeEditCallbackError("SesiÃ³n de ediciÃ³n no encontrada.")
        if token_payload.get("public_id") != edicion.public_id or token_payload.get("editor_key") != edicion.editor_key:
            raise OnlyOfficeEditCallbackError("Token de callback no corresponde a la sesiÃ³n.")

        status = int(payload.get("status", 0))
        if status not in SUPPORTED_CALLBACK_STATUSES:
            raise OnlyOfficeEditCallbackError("Estado de callback no soportado.")

        fingerprint = self._callback_fingerprint(edicion=edicion, payload=payload, status=status)
        if fingerprint and edicion.ultimo_callback_fingerprint == fingerprint:
            return {"error": 0, "idempotent": True}
        if fingerprint and DocumentoEdicionEvento.query.filter_by(fingerprint=fingerprint).first():
            edicion.ultimo_callback_fingerprint = fingerprint
            db.session.commit()
            return {"error": 0, "idempotent": True}

        edicion.ultimo_callback_en = _now()
        edicion.ultimo_callback_status = status
        edicion.ultimo_callback_fingerprint = fingerprint

        replacement = None
        if status == CALLBACK_STATUS_EDITING:
            self._renew(edicion)
            record_edit_event(edicion=edicion, tipo="CALLBACK_ACTIVIDAD", status_callback=status, fingerprint=fingerprint)
        elif status == CALLBACK_STATUS_CLOSED_NO_CHANGES:
            edicion.estado = ESTADO_EDICION_LIBERADA
            edicion.fecha_liberacion = _now()
            edicion.motivo_liberacion = "Cierre sin cambios reportado por ONLYOFFICE."
            record_edit_event(edicion=edicion, tipo="CIERRE_SIN_CAMBIOS", status_callback=status, fingerprint=fingerprint)
        elif status in ERROR_CALLBACK_STATUSES:
            edicion.error_ultimo_guardado = f"ONLYOFFICE reportÃ³ error de guardado status {status}."
            if status == CALLBACK_STATUS_SAVE_ERROR:
                edicion.estado = ESTADO_EDICION_ERROR
            record_edit_event(edicion=edicion, tipo="ERROR_CALLBACK", status_callback=status, fingerprint=fingerprint, detalle=edicion.error_ultimo_guardado)
        elif status in SAVEABLE_CALLBACK_STATUSES:
            if status == CALLBACK_STATUS_SAVE_FINAL and edicion.estado == ESTADO_EDICION_LIBERADA:
                if payload.get("key") != edicion.editor_key:
                    raise OnlyOfficeEditCallbackError("La clave del editor no coincide.")
                record_edit_event(
                    edicion=edicion,
                    tipo="GUARDADO_FINAL_CONFIRMADO",
                    status_callback=status,
                    fingerprint=fingerprint,
                    detalle="Cierre final confirmado por ONLYOFFICE tras liberacion local.",
                )
            else:
                replacement = self._save_callback_file(edicion=edicion, payload=payload, final=(status == CALLBACK_STATUS_SAVE_FINAL))
                record_edit_event(
                    edicion=edicion,
                    tipo="GUARDADO_FINAL" if status == CALLBACK_STATUS_SAVE_FINAL else "GUARDADO_FORZADO_COMPLETADO",
                    status_callback=status,
                    fingerprint=fingerprint,
                )

        try:
            db.session.commit()
        except Exception:
            restore_document_file_replacement(replacement)
            raise
        finalize_document_file_replacement(replacement)
        return {"error": 0, "idempotent": False}

    def _callback_fingerprint(self, *, edicion, payload, status):
        relevant = {
            "public_id": edicion.public_id,
            "key": payload.get("key"),
            "status": status,
            "forcesavetype": payload.get("forcesavetype"),
            "url": self._normalized_url(payload.get("url")),
            "history": bool(payload.get("history")),
        }
        return _event_fingerprint(relevant)

    def _normalized_url(self, url):
        if not url:
            return ""
        parsed = urlparse(url)
        return parsed._replace(query="", fragment="").geturl()

    def _renew(self, edicion):
        if edicion.estado == ESTADO_EDICION_ACTIVA:
            now = _now()
            edicion.ultima_actividad = now
            edicion.fecha_expiracion = _expiry_from(now)

    def _save_callback_file(self, *, edicion, payload, final):
        if edicion.documento_version_anexo_id:
            from app.services.document_attachment_service import DocumentAttachmentService

            return DocumentAttachmentService().save_callback_file(
                edicion=edicion,
                payload=payload,
                final=final,
            )
        if edicion.estado != ESTADO_EDICION_ACTIVA:
            raise OnlyOfficeEditCallbackError("La sesiÃ³n no estÃ¡ activa para guardar.")
        if payload.get("key") != edicion.editor_key:
            raise OnlyOfficeEditCallbackError("La clave del editor no coincide.")
        result_url = payload.get("url")
        if not result_url:
            raise OnlyOfficeEditCallbackError("Callback de guardado sin URL de resultado.")

        version = DocumentoVersion.query.filter_by(
            id=edicion.documento_version_id,
            documento_id=edicion.documento_id,
            empresa_id=edicion.empresa_id,
        ).with_for_update(of=DocumentoVersion).first()
        if not version or version.estado not in EDITABLE_VERSION_STATES:
            raise OnlyOfficeEditCallbackError("La version ya no esta en elaboracion.")
        profile = get_onlyoffice_document_profile(version)
        if not profile:
            raise OnlyOfficeEditCallbackError("La version ya no es compatible con ONLYOFFICE.")
        if version.archivo_sha256 != edicion.hash_ultimo_guardado:
            raise OnlyOfficeEditCallbackError("La copia de trabajo cambio fuera de la sesion.")

        temp_path = self._download_result(result_url, profile)
        old_sha = version.archivo_sha256
        old_size = version.archivo_size
        try:
            replacement = prepare_document_file_replacement(version, temp_path)
            new_sha = replacement.sha256
            new_size = replacement.size
            if new_sha != old_sha:
                version.archivo_sha256 = new_sha
                version.archivo_size = new_size
                version.archivo_mime = profile.mime_type
            edicion.hash_ultimo_guardado = new_sha
            edicion.ultimo_guardado_en = _now()
            edicion.error_ultimo_guardado = None
            self._renew(edicion)
            if final:
                edicion.estado = ESTADO_EDICION_LIBERADA
                edicion.fecha_liberacion = _now()
                edicion.motivo_liberacion = "Guardado final completado por ONLYOFFICE."
            return replacement
        except Exception:
            version.archivo_sha256 = old_sha
            version.archivo_size = old_size
            raise
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _download_result(self, result_url, profile):
        self._validate_result_url(result_url)
        max_bytes = int(current_app.config["ONLYOFFICE_CALLBACK_DOWNLOAD_MAX_BYTES"])
        request = Request(result_url, headers={"User-Agent": "LabZenISO-ONLYOFFICE-callback"})
        fd, temp_name = tempfile.mkstemp(prefix="onlyoffice-callback-", suffix=f".{profile.extension}")
        os.close(fd)
        temp_path = Path(temp_name)
        size = 0
        try:
            with urlopen(
                request,
                timeout=int(current_app.config["ONLYOFFICE_REQUEST_TIMEOUT_SECONDS"]),
            ) as response:
                final_url = response.geturl()
                self._validate_result_url(final_url)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise DocumentStorageError("El archivo devuelto por ONLYOFFICE supera el tamano permitido.")
                    with temp_path.open("ab") as output:
                        output.write(chunk)
            validate_onlyoffice_file_path(temp_path, profile)
            return temp_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

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
