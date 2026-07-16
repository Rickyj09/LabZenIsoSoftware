import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from flask import current_app

from app.extensions import db
from app.models.documentos import (
    ARTEFACTO_CONVIRTIENDO,
    ARTEFACTO_DISPONIBLE,
    ARTEFACTO_ERROR,
    ARTEFACTO_PDF_APROBADO,
    ARTEFACTO_PENDIENTE,
    CONVERSION_COMPLETADA,
    CONVERSION_EN_PROCESO,
    CONVERSION_ERROR,
    CONVERSION_PENDIENTE,
    CONVERSION_SOLICITADA,
    DocumentoArtefacto,
    DocumentoConversion,
    DocumentoSnapshot,
    ESTADO_APROBADO,
    SNAPSHOT_APROBADO,
    SNAPSHOT_DISPONIBLE,
)
from app.services.document_snapshot_service import DocumentSnapshotError, DocumentSnapshotService
from app.services.onlyoffice_document_view_service import DOCX_MIME
from app.services.onlyoffice_jwt_service import generate_onlyoffice_conversion_source_token, sign_onlyoffice_config
from app.services.storage_service import (
    DocumentStorageError,
    delete_pdf_artifact_file,
    file_digest_and_size,
    resolve_document_path,
    store_pdf_artifact_copy,
    validate_docx_file_path,
)


PDF_MIME = "application/pdf"
CONVERSION_PROVIDER_ONLYOFFICE = "onlyoffice"


class DocumentPdfError(ValueError):
    pass


class DocumentConversionProviderError(DocumentPdfError):
    pass


@dataclass(frozen=True)
class ConversionProviderResult:
    end_convert: bool
    percent: int
    file_url: str | None = None
    file_type: str | None = None
    provider_error: str | None = None
    raw_fingerprint: str | None = None


@dataclass(frozen=True)
class PdfValidationResult:
    sha256: str
    size: int
    page_count: int
    metadata: dict


def _now():
    return datetime.now(timezone.utc)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def conversion_key_for_snapshot(snapshot):
    raw = "|".join(
        [
            str(snapshot.empresa_id),
            str(snapshot.documento_id),
            str(snapshot.documento_version_id),
            str(snapshot.public_id),
            str(snapshot.archivo_sha256),
            ARTEFACTO_PDF_APROBADO,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DocumentConversionProvider:
    provider_name = "base"

    def request_conversion(self, *, conversion, source_url, source_token):
        raise NotImplementedError

    def download_result(self, file_url):
        raise NotImplementedError


class OnlyOfficeConversionProvider(DocumentConversionProvider):
    provider_name = CONVERSION_PROVIDER_ONLYOFFICE

    def __init__(self, app=None):
        self.app = app or current_app

    def request_conversion(self, *, conversion, source_url, source_token):
        payload = {
            "async": bool(self.app.config["ONLYOFFICE_CONVERSION_ASYNC"]),
            "filetype": "docx",
            "key": conversion.conversion_key,
            "outputtype": "pdf",
            "title": self._controlled_title(conversion),
            "url": source_url,
        }
        if source_token:
            payload["token"] = source_token
        payload["token"] = sign_onlyoffice_config(payload)
        request_body = json.dumps(payload).encode("utf-8")
        converter_url = self._converter_url(conversion.conversion_key)
        request = Request(
            converter_url,
            data=request_body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(
                request,
                timeout=int(self.app.config["ONLYOFFICE_CONVERSION_REQUEST_TIMEOUT_SECONDS"]),
            ) as response:
                if int(response.status) < 200 or int(response.status) >= 300:
                    raise DocumentConversionProviderError("ONLYOFFICE devolvio un estado HTTP inesperado.")
                raw = response.read(1024 * 1024)
        except Exception as exc:
            raise DocumentConversionProviderError("No se pudo solicitar conversion a ONLYOFFICE.") from exc
        return self._parse_response(raw)

    def download_result(self, file_url):
        self._validate_result_url(file_url)
        max_bytes = int(self.app.config["ONLYOFFICE_CONVERSION_DOWNLOAD_MAX_BYTES"])
        request = Request(file_url, headers={"User-Agent": "LabZenISO-ONLYOFFICE-conversion"})
        fd, temp_name = tempfile.mkstemp(prefix="onlyoffice-pdf-", suffix=".pdf")
        os.close(fd)
        temp_path = Path(temp_name)
        size = 0
        try:
            with urlopen(
                request,
                timeout=int(self.app.config["ONLYOFFICE_CONVERSION_REQUEST_TIMEOUT_SECONDS"]),
            ) as response:
                final_url = response.geturl()
                self._validate_result_url(final_url)
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise DocumentConversionProviderError("El PDF devuelto supera el tamano permitido.")
                with temp_path.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise DocumentConversionProviderError("El PDF devuelto supera el tamano permitido.")
                        output.write(chunk)
            return temp_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _converter_url(self, conversion_key):
        base = self.app.config["ONLYOFFICE_INTERNAL_URL"].rstrip("/")
        path = "/" + self.app.config["ONLYOFFICE_CONVERTER_PATH"].strip("/")
        return f"{base}{path}?{urlencode({'shardkey': conversion_key})}"

    def _controlled_title(self, conversion):
        return f"documento-{conversion.documento_id}-version-{conversion.documento_version_id}.docx"

    def _parse_response(self, raw):
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise DocumentConversionProviderError("ONLYOFFICE devolvio una respuesta JSON invalida.") from exc
        if not isinstance(data, dict):
            raise DocumentConversionProviderError("ONLYOFFICE devolvio una respuesta inesperada.")
        if "error" in data and data.get("error") not in (0, "0", None):
            return ConversionProviderResult(
                end_convert=False,
                percent=0,
                provider_error=str(data.get("error")),
                raw_fingerprint=_fingerprint(data),
            )
        end_convert = data.get("endConvert")
        if not isinstance(end_convert, bool):
            raise DocumentConversionProviderError("Respuesta de conversion sin endConvert valido.")
        percent = data.get("percent", 100 if end_convert else 0)
        if not isinstance(percent, int) or percent < 0 or percent > 100:
            raise DocumentConversionProviderError("Porcentaje de conversion invalido.")
        if end_convert:
            file_type = (data.get("fileType") or "").strip().lower()
            file_url = (data.get("fileUrl") or "").strip()
            if file_type != "pdf" or not file_url:
                raise DocumentConversionProviderError("Conversion finalizada sin PDF valido.")
            return ConversionProviderResult(True, percent, file_url=file_url, file_type=file_type, raw_fingerprint=_fingerprint(data))
        return ConversionProviderResult(False, percent, raw_fingerprint=_fingerprint(data))

    def _validate_result_url(self, result_url):
        parsed = urlparse(result_url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DocumentConversionProviderError("URL de resultado no permitida.")
        allowed_hosts = set(self.app.config["ONLYOFFICE_ALLOWED_HOSTS"])
        internal_host = urlparse(self.app.config["ONLYOFFICE_INTERNAL_URL"]).hostname
        allowed_hosts.update(host for host in (internal_host,) if host)
        if parsed.hostname not in allowed_hosts:
            raise DocumentConversionProviderError("Host de resultado no autorizado.")


class DocumentPdfService:
    def __init__(self, provider=None, app=None):
        self.app = app or current_app
        self.provider = provider or OnlyOfficeConversionProvider(self.app)
        self.snapshot_service = DocumentSnapshotService()

    def latest_artifact_for_version(self, version_doc):
        return (
            DocumentoArtefacto.query
            .filter_by(
                empresa_id=version_doc.empresa_id,
                documento_version_id=version_doc.id,
                tipo=ARTEFACTO_PDF_APROBADO,
            )
            .order_by(DocumentoArtefacto.id.desc())
            .first()
        )

    def available_artifact_for_version(self, version_doc):
        return (
            DocumentoArtefacto.query
            .filter_by(
                empresa_id=version_doc.empresa_id,
                documento_version_id=version_doc.id,
                tipo=ARTEFACTO_PDF_APROBADO,
                estado=ARTEFACTO_DISPONIBLE,
            )
            .order_by(DocumentoArtefacto.disponible_en.desc(), DocumentoArtefacto.id.desc())
            .first()
        )

    def latest_conversion_for_version(self, version_doc):
        return (
            DocumentoConversion.query
            .filter_by(
                empresa_id=version_doc.empresa_id,
                documento_version_id=version_doc.id,
            )
            .order_by(DocumentoConversion.id.desc())
            .first()
        )

    def ensure_conversion_for_approved_version(self, *, documento, version_doc, usuario, start=True):
        if not self.app.config.get("ONLYOFFICE_CONVERSION_ENABLED"):
            return None
        snapshot = self._approved_snapshot_for_conversion(documento=documento, version_doc=version_doc)
        existing_artifact = self._valid_available_artifact(snapshot)
        if existing_artifact:
            return existing_artifact
        conversion = self._get_or_create_conversion(documento=documento, version_doc=version_doc, snapshot=snapshot, usuario=usuario)
        if start:
            return self.process_conversion(conversion=conversion)
        return conversion.artefacto

    def retry_conversion(self, *, conversion_public_id, usuario):
        conversion = DocumentoConversion.query.filter_by(public_id=conversion_public_id, empresa_id=usuario.empresa_id).first()
        if not conversion:
            raise LookupError("Conversion no encontrada.")
        if conversion.estado != CONVERSION_ERROR:
            raise DocumentPdfError("Solo una conversion en ERROR puede reintentarse.")
        max_attempts = int(self.app.config["ONLYOFFICE_CONVERSION_MAX_ATTEMPTS"])
        if conversion.attempt_number >= max_attempts:
            raise DocumentPdfError("La conversion alcanzo el maximo de reintentos.")
        if self._valid_available_artifact(conversion.source_snapshot):
            raise DocumentPdfError("Ya existe un PDF aprobado disponible.")
        self._validate_approved_snapshot(conversion.source_snapshot)
        conversion.attempt_number += 1
        conversion.estado = CONVERSION_PENDIENTE
        conversion.percent = 0
        conversion.error_code = None
        conversion.error_message = None
        if conversion.artefacto:
            conversion.artefacto.estado = ARTEFACTO_PENDIENTE
            conversion.artefacto.error_codigo = None
            conversion.artefacto.error_mensaje = None
        db.session.commit()
        return self.process_conversion(conversion=conversion)

    def process_conversion(self, *, conversion):
        artifact = conversion.artefacto
        snapshot = conversion.source_snapshot
        self._validate_approved_snapshot(snapshot)
        if self._valid_available_artifact(snapshot):
            return self._valid_available_artifact(snapshot)

        source_url, source_token, expires_at = self._build_source_url(snapshot=snapshot, conversion=conversion)
        conversion.source_url_expires_at = expires_at
        conversion.iniciado_en = conversion.iniciado_en or _now()
        artifact.estado = ARTEFACTO_CONVIRTIENDO
        conversion.estado = CONVERSION_SOLICITADA
        conversion.request_fingerprint = _fingerprint({
            "provider": self.provider.provider_name,
            "conversion_key": conversion.conversion_key,
            "snapshot": snapshot.public_id,
        })
        db.session.commit()

        deadline = time.monotonic() + int(self.app.config["ONLYOFFICE_CONVERSION_MAX_WAIT_SECONDS"])
        result = None
        while time.monotonic() <= deadline:
            try:
                result = self.provider.request_conversion(
                    conversion=conversion,
                    source_url=source_url,
                    source_token=source_token,
                )
            except Exception as exc:
                return self._mark_error(conversion, "PROVIDER_REQUEST_FAILED", str(exc))
            conversion.ultima_consulta_en = _now()
            conversion.response_fingerprint = result.raw_fingerprint
            if result.provider_error:
                return self._mark_error(conversion, f"ONLYOFFICE_{result.provider_error}", "ONLYOFFICE reporto un error de conversion.")
            conversion.percent = int(result.percent)
            if not result.end_convert:
                conversion.estado = CONVERSION_EN_PROCESO
                artifact.estado = ARTEFACTO_CONVIRTIENDO
                db.session.commit()
                if int(self.app.config["ONLYOFFICE_CONVERSION_MAX_WAIT_SECONDS"]) <= int(self.app.config["ONLYOFFICE_CONVERSION_POLL_INTERVAL_SECONDS"]):
                    break
                time.sleep(min(int(self.app.config["ONLYOFFICE_CONVERSION_POLL_INTERVAL_SECONDS"]), 5))
                continue
            return self._store_completed_pdf(conversion=conversion, result=result)

        conversion.estado = CONVERSION_EN_PROCESO
        artifact.estado = ARTEFACTO_CONVIRTIENDO
        db.session.commit()
        return artifact

    def validate_source_token_snapshot(self, payload):
        snapshot = DocumentoSnapshot.query.filter_by(
            public_id=payload.get("snapshot_public_id"),
            empresa_id=int(payload.get("empresa_id", 0)),
            documento_id=int(payload.get("documento_id", 0)),
            documento_version_id=int(payload.get("documento_version_id", 0)),
        ).first()
        if not snapshot:
            raise DocumentPdfError("Snapshot no encontrado.")
        if payload.get("snapshot_sha256") != snapshot.archivo_sha256:
            raise DocumentPdfError("Hash de snapshot invalido.")
        if payload.get("conversion_key") != conversion_key_for_snapshot(snapshot):
            raise DocumentPdfError("Clave de conversion invalida.")
        self._validate_approved_snapshot(snapshot)
        return snapshot

    def validate_pdf_file(self, path, *, allow_signature_forms=False):
        if path.is_symlink() or not path.is_file():
            raise DocumentPdfError("PDF no disponible para validacion.")
        sha256, size = file_digest_and_size(path)
        max_size = int(self.app.config["ONLYOFFICE_PDF_MAX_BYTES"])
        if size <= 0 or size > max_size:
            raise DocumentPdfError("Tamano de PDF invalido.")
        with path.open("rb") as input_file:
            head = input_file.read(8)
            input_file.seek(max(0, size - 2048))
            tail = input_file.read()
        if not head.startswith(b"%PDF-") or b"%%EOF" not in tail:
            raise DocumentPdfError("Estructura PDF invalida.")
        data = path.read_bytes()
        if b"/Encrypt" in data:
            raise DocumentPdfError("PDF cifrado no permitido.")
        active_markers = {
            "javascript": b"/JavaScript" in data or b"/JS" in data,
            "open_action": b"/OpenAction" in data or b"/AA" in data,
            "embedded_files": b"/EmbeddedFile" in data,
            "forms": (not allow_signature_forms) and b"/AcroForm" in data,
        }
        if any(active_markers.values()):
            raise DocumentPdfError("PDF con contenido activo inesperado.")
        page_count = self._count_pdf_pages(data)
        if self.app.config.get("ONLYOFFICE_PDF_VALIDATE_PAGE_COUNT") and page_count <= 0:
            raise DocumentPdfError("PDF sin paginas validas.")
        return PdfValidationResult(sha256=sha256, size=size, page_count=page_count, metadata={"active_markers": active_markers})

    def _count_pdf_pages(self, data):
        return len(re.findall(br"/Type\s*/Page\b", data))

    def _approved_snapshot_for_conversion(self, *, documento, version_doc):
        if version_doc.estado != ESTADO_APROBADO:
            raise DocumentPdfError("Solo una version APROBADA puede convertirse a PDF definitivo.")
        snapshot = self.snapshot_service.approved_snapshot(version_doc)
        if not snapshot:
            raise DocumentPdfError("No existe snapshot APROBADO para convertir.")
        if snapshot.documento_id != documento.id or snapshot.empresa_id != documento.empresa_id:
            raise DocumentPdfError("Snapshot aprobado no pertenece al documento.")
        self._validate_approved_snapshot(snapshot)
        return snapshot

    def _validate_approved_snapshot(self, snapshot):
        if not snapshot:
            raise DocumentPdfError("Snapshot aprobado inexistente.")
        if snapshot.tipo != SNAPSHOT_APROBADO or snapshot.estado != SNAPSHOT_DISPONIBLE or not snapshot.inmutable:
            raise DocumentPdfError("La fuente de conversion debe ser un snapshot APROBADO disponible e inmutable.")
        if not _is_sha256(snapshot.archivo_sha256 or ""):
            raise DocumentPdfError("Snapshot aprobado sin hash SHA-256 valido.")
        if not snapshot.workflow_evento or snapshot.workflow_evento.accion != "APROBAR":
            raise DocumentPdfError("Snapshot APROBADO sin evento APROBAR asociado.")
        if (snapshot.archivo_mime or DOCX_MIME) != DOCX_MIME:
            raise DocumentPdfError("Snapshot aprobado no es DOCX.")
        try:
            path = self.snapshot_service.resolve_snapshot_path(snapshot)
            validate_docx_file_path(path)
        except (DocumentSnapshotError, DocumentStorageError, FileNotFoundError) as exc:
            raise DocumentPdfError(str(exc)) from exc
        return snapshot

    def _valid_available_artifact(self, snapshot):
        artifact = (
            DocumentoArtefacto.query
            .filter_by(
                empresa_id=snapshot.empresa_id,
                source_snapshot_id=snapshot.id,
                tipo=ARTEFACTO_PDF_APROBADO,
                estado=ARTEFACTO_DISPONIBLE,
            )
            .first()
        )
        if not artifact:
            return None
        self.validate_artifact_file(artifact)
        return artifact

    def validate_artifact_file(self, artifact):
        if artifact.estado != ARTEFACTO_DISPONIBLE or artifact.tipo != ARTEFACTO_PDF_APROBADO:
            raise DocumentPdfError("Artefacto PDF no disponible.")
        if not artifact.inmutable or not artifact.storage_path:
            raise DocumentPdfError("Artefacto PDF no es inmutable.")
        path = resolve_document_path(artifact.storage_path)
        result = self.validate_pdf_file(path)
        if result.sha256 != artifact.archivo_sha256:
            raise DocumentPdfError("Hash fisico del PDF no coincide.")
        if int(result.size) != int(artifact.archivo_size or 0):
            raise DocumentPdfError("Tamano fisico del PDF no coincide.")
        if int(result.page_count) != int(artifact.page_count or 0):
            raise DocumentPdfError("Conteo fisico de paginas no coincide.")
        return path

    def _get_or_create_conversion(self, *, documento, version_doc, snapshot, usuario):
        conversion_key = conversion_key_for_snapshot(snapshot)
        conversion = DocumentoConversion.query.filter_by(conversion_key=conversion_key).first()
        if conversion:
            return conversion
        artifact = DocumentoArtefacto(
            empresa_id=documento.empresa_id,
            public_id=uuid4().hex,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            source_snapshot_id=snapshot.id,
            tipo=ARTEFACTO_PDF_APROBADO,
            estado=ARTEFACTO_PENDIENTE,
            source_snapshot_sha256=snapshot.archivo_sha256,
            provider=self.provider.provider_name,
            creado_por_id=usuario.id,
            creado_en=_now(),
            inmutable=False,
            metadata_json={"source": "snapshot_aprobado", "source_snapshot_public_id": snapshot.public_id},
        )
        db.session.add(artifact)
        db.session.flush()
        conversion = DocumentoConversion(
            empresa_id=documento.empresa_id,
            public_id=uuid4().hex,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            source_snapshot_id=snapshot.id,
            artefacto_id=artifact.id,
            provider=self.provider.provider_name,
            conversion_key=conversion_key,
            estado=CONVERSION_PENDIENTE,
            attempt_number=1,
            percent=0,
            solicitado_por_id=usuario.id,
            solicitado_en=_now(),
            metadata_json={},
        )
        db.session.add(conversion)
        db.session.commit()
        return conversion

    def _build_source_url(self, *, snapshot, conversion):
        expires_at = _now() + timedelta(seconds=int(self.app.config["ONLYOFFICE_CONVERSION_SOURCE_TOKEN_TTL_SECONDS"]))
        token = generate_onlyoffice_conversion_source_token(
            snapshot_public_id=snapshot.public_id,
            empresa_id=snapshot.empresa_id,
            documento_id=snapshot.documento_id,
            version_id=snapshot.documento_version_id,
            snapshot_sha256=snapshot.archivo_sha256,
            conversion_key=conversion.conversion_key,
        )
        path = f"/documentacion/integraciones/onlyoffice/snapshots/{snapshot.public_id}/conversion-source"
        source_url = self.app.config["ONLYOFFICE_CALLBACK_BASE_URL"].rstrip("/") + path + "?" + urlencode({"token": token})
        return source_url, token, expires_at

    def _store_completed_pdf(self, *, conversion, result):
        artifact = conversion.artefacto
        snapshot = conversion.source_snapshot
        temp_path = None
        stored = None
        try:
            temp_path = self.provider.download_result(result.file_url)
            validation = self.validate_pdf_file(temp_path)
            stored = store_pdf_artifact_copy(
                source_path=temp_path,
                documento=conversion.documento,
                version_doc=conversion.documento_version,
                source_snapshot=snapshot,
                expected_sha256=validation.sha256,
            )
            artifact.storage_path = stored.storage_path
            artifact.archivo_nombre_interno = stored.stored_name
            artifact.archivo_nombre_visible = f"{conversion.documento.codigo}_v{conversion.documento_version.version}_aprobado_sin_firmas.pdf"
            artifact.archivo_mime = PDF_MIME
            artifact.archivo_size = stored.size
            artifact.archivo_sha256 = stored.sha256
            artifact.page_count = validation.page_count
            artifact.estado = ARTEFACTO_DISPONIBLE
            artifact.inmutable = True
            artifact.disponible_en = _now()
            artifact.error_codigo = None
            artifact.error_mensaje = None
            artifact.metadata_json = {**(artifact.metadata_json or {}), **validation.metadata, "file_type": result.file_type}
            conversion.estado = CONVERSION_COMPLETADA
            conversion.percent = 100
            conversion.completado_en = _now()
            conversion.error_code = None
            conversion.error_message = None
            db.session.commit()
            return artifact
        except Exception as exc:
            db.session.rollback()
            if stored:
                delete_pdf_artifact_file(stored.storage_path)
            return self._mark_error(conversion, "PDF_STORE_FAILED", str(exc))
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def _mark_error(self, conversion, code, message):
        conversion = DocumentoConversion.query.get(conversion.id)
        artifact = conversion.artefacto
        conversion.estado = CONVERSION_ERROR
        conversion.error_code = str(code)[:80]
        conversion.error_message = str(message)[:1000]
        conversion.ultima_consulta_en = _now()
        if artifact:
            artifact.estado = ARTEFACTO_ERROR
            artifact.error_codigo = str(code)[:80]
            artifact.error_mensaje = str(message)[:1000]
        db.session.commit()
        return artifact
