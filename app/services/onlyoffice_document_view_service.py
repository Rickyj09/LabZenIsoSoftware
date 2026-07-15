import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from flask import current_app, url_for

from app.models.documentos import Documento, DocumentoVersion
from app.services.onlyoffice_health_service import OnlyOfficeHealthService
from app.services.onlyoffice_jwt_service import (
    generate_onlyoffice_document_token,
    sign_onlyoffice_config,
)
from app.services.storage_service import DocumentStorageError, resolve_document_path


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class OnlyOfficeDocumentViewError(ValueError):
    status_code = 400


class OnlyOfficeDisabledError(OnlyOfficeDocumentViewError):
    status_code = 409


class OnlyOfficeUnavailableError(OnlyOfficeDocumentViewError):
    status_code = 503


class OnlyOfficeInvalidDocumentError(OnlyOfficeDocumentViewError):
    status_code = 422


@dataclass(frozen=True)
class OnlyOfficeDocumentViewContext:
    documento: Documento
    version: DocumentoVersion
    editor_config: dict
    public_api_url: str
    csp_origin: str


def is_docx_version(version_doc):
    filename = (
        version_doc.archivo_nombre_original
        or version_doc.archivo_nombre_guardado
        or version_doc.archivo_storage_path
        or ""
    )
    return filename.lower().endswith(".docx")


def onlyoffice_document_key(*, empresa_id, documento_id, version_id, archivo_sha256):
    raw = f"{int(empresa_id)}:{int(documento_id)}:{int(version_id)}:{archivo_sha256}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resolve_viewable_docx_path(version_doc):
    if not is_docx_version(version_doc):
        raise OnlyOfficeInvalidDocumentError("La versión documental no es un archivo DOCX compatible.")
    if not version_doc.archivo_storage_path:
        raise OnlyOfficeInvalidDocumentError("La versión no tiene archivo privado disponible para ONLYOFFICE.")
    if not version_doc.archivo_sha256:
        raise OnlyOfficeInvalidDocumentError("La versión no tiene hash documental registrado.")

    try:
        physical_path = resolve_document_path(version_doc.archivo_storage_path)
    except DocumentStorageError as exc:
        raise OnlyOfficeInvalidDocumentError("La ruta privada del documento no es válida.") from exc

    if not physical_path.is_file():
        raise FileNotFoundError("El archivo privado de la versión no existe.")
    return physical_path


class OnlyOfficeDocumentViewService:
    def __init__(self, app=None):
        self.app = app or current_app

    def build_context(self, *, documento_id, version_id, user):
        if not self.app.config.get("ONLYOFFICE_ENABLED"):
            raise OnlyOfficeDisabledError("ONLYOFFICE está deshabilitado.")

        documento = Documento.query.filter_by(
            id=documento_id,
            empresa_id=user.empresa_id,
        ).first()
        if not documento:
            raise LookupError("Documento no encontrado.")

        version = DocumentoVersion.query.filter_by(
            id=version_id,
            documento_id=documento.id,
            empresa_id=user.empresa_id,
        ).first()
        if not version:
            raise LookupError("Versión documental no encontrada.")

        resolve_viewable_docx_path(version)

        health = OnlyOfficeHealthService(self.app).check()
        if not health.available:
            raise OnlyOfficeUnavailableError(health.message or "ONLYOFFICE no está disponible.")

        document_url = self._build_document_url(documento, version)
        document_key = onlyoffice_document_key(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            version_id=version.id,
            archivo_sha256=version.archivo_sha256,
        )
        config = self._build_editor_config(documento, version, document_url, document_key, user)
        config["token"] = sign_onlyoffice_config(config)

        return OnlyOfficeDocumentViewContext(
            documento=documento,
            version=version,
            editor_config=config,
            public_api_url=self.app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/") + "/web-apps/apps/api/documents/api.js",
            csp_origin=self.app.config["ONLYOFFICE_PUBLIC_URL"].rstrip("/"),
        )

    def _build_document_url(self, documento, version):
        token = generate_onlyoffice_document_token(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            version_id=version.id,
            archivo_sha256=version.archivo_sha256,
        )
        path = url_for("onlyoffice_integration.document_file", version_id=version.id)
        return (
            self.app.config["ONLYOFFICE_CALLBACK_BASE_URL"].rstrip("/")
            + path
            + "?"
            + urlencode({"token": token})
        )

    def _build_editor_config(self, documento, version, document_url, document_key, user):
        title = version.archivo_nombre_original or f"{documento.codigo}_v{version.version}.docx"
        return {
            "document": {
                "fileType": "docx",
                "key": document_key,
                "title": Path(title).name,
                "url": document_url,
                "permissions": {
                    "comment": False,
                    "download": False,
                    "edit": False,
                    "fillForms": False,
                    "modifyFilter": False,
                    "print": False,
                    "review": False,
                },
            },
            "documentType": "word",
            "editorConfig": {
                "mode": "view",
                "lang": "es",
                "user": {
                    "id": str(user.id),
                    "name": f"{user.nombre} {user.apellido}".strip(),
                },
                "customization": {
                    "autosave": False,
                    "forcesave": False,
                    "comments": False,
                    "compactToolbar": False,
                    "hideRightMenu": True,
                },
            },
            "height": "100%",
            "type": "desktop",
            "width": "100%",
        }
