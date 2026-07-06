import hashlib
import mimetypes
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename


ALLOWED_DOCUMENT_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "png", "jpg", "jpeg"
}
MAX_STORED_FILENAME_LENGTH = 200


class DocumentStorageError(ValueError):
    pass


@dataclass(frozen=True)
class StoredDocumentFile:
    original_name: str
    stored_name: str
    storage_path: str
    mime_type: str
    size: int
    sha256: str


def validate_document_file(file_storage) -> None:
    if not file_storage or not file_storage.filename:
        return

    safe_name = secure_filename(file_storage.filename)
    if not safe_name or "." not in safe_name:
        raise DocumentStorageError("El archivo no tiene un nombre o extensión válidos.")

    extension = safe_name.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise DocumentStorageError("El archivo seleccionado no tiene un formato permitido.")


def _safe_version(value) -> str:
    normalized = secure_filename(str(value or "1")).replace("_", "-")
    normalized = re.sub(r"[^A-Za-z0-9.-]+", "-", normalized).strip(".-")
    return normalized or "1"


def slugify_filename_part(texto, *, max_length=100) -> str:
    """Normaliza una parte del nombre sin permitir separadores ni traversal."""
    normalized = unicodedata.normalize("NFKD", str(texto or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9-]+", "_", ascii_text).strip("_-").lower()
    return slug[:max_length].rstrip("_-")


def build_document_filename(documento, version, original_filename, sha256) -> str:
    safe_original = secure_filename(original_filename or "")
    if not safe_original or "." not in safe_original:
        raise DocumentStorageError("El archivo no tiene un nombre o extensión válidos.")

    extension = safe_original.rsplit(".", 1)[1].lower()
    hash_short = re.sub(r"[^a-fA-F0-9]", "", str(sha256 or ""))[:8].lower()
    if len(hash_short) != 8:
        raise DocumentStorageError("No se pudo generar la huella del archivo documental.")

    code = slugify_filename_part(getattr(documento, "codigo", None), max_length=60).upper()
    code = code or f"DOCUMENTO_{getattr(documento, 'id', 'SIN_ID')}"
    version_value = getattr(version, "version", version)
    version_slug = slugify_filename_part(version_value, max_length=30) or "1"
    original_stem = safe_original.rsplit(".", 1)[0]
    descriptive = slugify_filename_part(
        getattr(documento, "titulo", None) or original_stem,
        max_length=100,
    ) or "archivo"

    fixed_length = len(f"{code}_v{version_slug}__{hash_short}.{extension}")
    available = max(1, MAX_STORED_FILENAME_LENGTH - fixed_length)
    descriptive = descriptive[:available].rstrip("_") or "a"
    return f"{code}_v{version_slug}_{descriptive}_{hash_short}.{extension}"


def _storage_root() -> Path:
    return Path(current_app.config["DOCUMENT_STORAGE_ROOT"]).resolve()


def _legacy_storage_root() -> Path:
    return Path(current_app.config["DOCUMENT_LEGACY_STORAGE_ROOT"]).resolve()


def store_document_file(file_storage, *, documento, version) -> StoredDocumentFile | None:
    if not file_storage or not file_storage.filename:
        return None

    validate_document_file(file_storage)
    original_name = str(file_storage.filename).replace("\\", "/").rsplit("/", 1)[-1].strip()
    safe_original_name = secure_filename(original_name)

    relative_directory = Path(
        f"empresa_{int(documento.empresa_id)}",
        f"documento_{int(documento.id)}",
        f"v{_safe_version(getattr(version, 'version', version))}",
    )
    destination_directory = (_storage_root() / relative_directory).resolve()
    destination_directory.mkdir(parents=True, exist_ok=True)
    if os.path.commonpath([str(_storage_root()), str(destination_directory)]) != str(_storage_root()):
        raise DocumentStorageError("La ruta de almacenamiento del documento no es válida.")

    temporary = (destination_directory / f".upload-{uuid4().hex}.tmp").resolve()
    digest = hashlib.sha256()
    size = 0
    max_size = int(current_app.config["DOCUMENT_MAX_FILE_SIZE"])

    try:
        file_storage.stream.seek(0)
        with temporary.open("wb") as output:
            while True:
                chunk = file_storage.stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    raise DocumentStorageError(
                        f"El archivo supera el límite permitido de {max_size // (1024 * 1024)} MB."
                    )
                digest.update(chunk)
                output.write(chunk)
        sha256 = digest.hexdigest()
        stored_name = build_document_filename(
            documento,
            version,
            safe_original_name,
            sha256,
        )
        destination = (destination_directory / stored_name).resolve()
        if os.path.commonpath([str(_storage_root()), str(destination)]) != str(_storage_root()):
            raise DocumentStorageError("La ruta de almacenamiento del documento no es válida.")
        if destination.exists():
            raise DocumentStorageError("Ya existe un archivo documental con el mismo nombre y contenido.")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    mime_type = (
        file_storage.mimetype
        or mimetypes.guess_type(safe_original_name)[0]
        or "application/octet-stream"
    )
    storage_path = (relative_directory / stored_name).as_posix()
    return StoredDocumentFile(
        original_name=original_name,
        stored_name=stored_name,
        storage_path=storage_path,
        mime_type=mime_type,
        size=size,
        sha256=sha256,
    )


def apply_stored_file_metadata(version_doc, stored_file: StoredDocumentFile | None) -> None:
    if not stored_file:
        return
    version_doc.archivo_nombre_original = stored_file.original_name
    version_doc.archivo_nombre_guardado = stored_file.stored_name
    version_doc.archivo_storage_path = stored_file.storage_path
    version_doc.archivo_mime = stored_file.mime_type
    version_doc.archivo_size = stored_file.size
    version_doc.archivo_sha256 = stored_file.sha256


def resolve_document_path(storage_path: str) -> Path:
    if not storage_path:
        raise DocumentStorageError("El documento no tiene una ruta privada registrada.")

    root = _storage_root()
    candidate = (root / Path(storage_path)).resolve()
    if os.path.commonpath([str(root), str(candidate)]) != str(root):
        raise DocumentStorageError("La ruta privada del documento no es válida.")
    return candidate


def resolve_legacy_document_path(archivo_url: str) -> Path:
    """Resuelve únicamente URLs del storage público histórico conocido."""
    prefix = "/static/uploads/documentos/"
    if not archivo_url or not archivo_url.startswith(prefix):
        raise DocumentStorageError("La URL histórica del documento no es válida.")

    relative_name = archivo_url[len(prefix):].split("?", 1)[0]
    if not relative_name or "/" in relative_name or "\\" in relative_name:
        raise DocumentStorageError("La URL histórica contiene una ruta no permitida.")

    root = _legacy_storage_root()
    candidate = (root / relative_name).resolve()
    if os.path.commonpath([str(root), str(candidate)]) != str(root):
        raise DocumentStorageError("La ruta histórica del documento no es válida.")
    return candidate


def delete_document_file(storage_path: str | None) -> None:
    if not storage_path:
        return
    try:
        resolve_document_path(storage_path).unlink(missing_ok=True)
    except (DocumentStorageError, OSError):
        current_app.logger.warning(
            "No se pudo eliminar el archivo documental huérfano: %s", storage_path
        )
