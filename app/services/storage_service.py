import hashlib
import mimetypes
import os
import re
import shutil
import unicodedata
import zipfile
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


@dataclass(frozen=True)
class AtomicDocumentReplacement:
    destination_path: Path
    backup_path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class StoredSnapshotFile:
    stored_name: str
    storage_path: str
    mime_type: str
    size: int
    sha256: str


@dataclass(frozen=True)
class StoredPdfArtifactFile:
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


def _safe_snapshot_type(value) -> str:
    normalized = secure_filename(str(value or "snapshot")).replace("_", "-").lower()
    normalized = re.sub(r"[^a-z0-9-]+", "-", normalized).strip("-")
    return normalized or "snapshot"


def _safe_hash_part(value) -> str:
    normalized = re.sub(r"[^a-fA-F0-9]", "", str(value or "")).lower()
    if len(normalized) < 12:
        raise DocumentStorageError("Hash documental insuficiente para construir la ruta.")
    return normalized


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


def validate_docx_file_path(path: Path) -> None:
    if path.is_symlink():
        raise DocumentStorageError("No se permiten enlaces simbolicos como documento DOCX.")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise DocumentStorageError("El archivo DOCX no contiene word/document.xml.")
            if "[Content_Types].xml" not in names:
                raise DocumentStorageError("El archivo DOCX no contiene tipos de contenido OOXML.")
    except zipfile.BadZipFile as exc:
        raise DocumentStorageError("El archivo DOCX recibido no es un ZIP OOXML vÃ¡lido.") from exc


def file_digest_and_size(path: Path) -> tuple[str, int]:
    if path.is_symlink():
        raise DocumentStorageError("No se permiten enlaces simbolicos en el storage documental.")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as input_file:
        while True:
            chunk = input_file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def prepare_document_file_replacement(version_doc, source_path: Path) -> AtomicDocumentReplacement:
    if not version_doc.archivo_storage_path:
        raise DocumentStorageError("La versiÃ³n no tiene ruta privada para reemplazo.")

    validate_docx_file_path(source_path)
    new_sha256, new_size = file_digest_and_size(source_path)
    destination = resolve_document_path(version_doc.archivo_storage_path)
    if "snapshots" in destination.parts:
        raise DocumentStorageError("No se permite reemplazar archivos dentro del area de snapshots.")
    if not destination.is_file():
        raise DocumentStorageError("La copia de trabajo actual no existe.")
    if destination.is_symlink():
        raise DocumentStorageError("La copia de trabajo no puede ser un enlace simbolico.")

    backup = destination.with_name(f".backup-{uuid4().hex}-{destination.name}")
    replacement = destination.with_name(f".replace-{uuid4().hex}-{destination.name}")
    try:
        shutil.copyfile(source_path, replacement)
        os.replace(destination, backup)
        try:
            os.replace(replacement, destination)
        except Exception:
            if destination.exists():
                destination.unlink(missing_ok=True)
            os.replace(backup, destination)
            raise
    except Exception:
        replacement.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        raise

    replacement.unlink(missing_ok=True)
    return AtomicDocumentReplacement(
        destination_path=destination,
        backup_path=backup,
        sha256=new_sha256,
        size=new_size,
    )


def finalize_document_file_replacement(replacement: AtomicDocumentReplacement | None) -> None:
    if replacement:
        replacement.backup_path.unlink(missing_ok=True)


def restore_document_file_replacement(replacement: AtomicDocumentReplacement | None) -> None:
    if not replacement or not replacement.backup_path.exists():
        return
    replacement.destination_path.unlink(missing_ok=True)
    os.replace(replacement.backup_path, replacement.destination_path)


def replace_document_file_atomically(version_doc, source_path: Path) -> tuple[str, int]:
    replacement = prepare_document_file_replacement(version_doc, source_path)
    finalize_document_file_replacement(replacement)
    return replacement.sha256, replacement.size


def store_snapshot_copy(*, source_path: Path, documento, version_doc, secuencia: int, tipo: str) -> StoredSnapshotFile:
    """Crea una copia fisica independiente e inmutable de un DOCX de trabajo."""
    if source_path.is_symlink():
        raise DocumentStorageError("No se permite congelar un enlace simbolico.")
    if not source_path.is_file():
        raise DocumentStorageError("La copia de trabajo no existe.")
    validate_docx_file_path(source_path)
    source_sha256, source_size = file_digest_and_size(source_path)

    relative_directory = Path(
        f"empresa_{int(documento.empresa_id)}",
        f"documento_{int(documento.id)}",
        f"v{_safe_version(getattr(version_doc, 'version', version_doc.id))}",
        "snapshots",
    )
    destination_directory = (_storage_root() / relative_directory).resolve()
    destination_directory.mkdir(parents=True, exist_ok=True)
    if os.path.commonpath([str(_storage_root()), str(destination_directory)]) != str(_storage_root()):
        raise DocumentStorageError("La ruta de snapshots no es valida.")

    stored_name = f"{int(secuencia):04d}-{_safe_snapshot_type(tipo)}-{source_sha256[:12]}.docx"
    destination = (destination_directory / stored_name).resolve()
    if os.path.commonpath([str(_storage_root()), str(destination)]) != str(_storage_root()):
        raise DocumentStorageError("La ruta del snapshot no es valida.")
    if destination.exists():
        raise DocumentStorageError("Ya existe un snapshot con la misma ruta.")

    temporary = (destination_directory / f".snapshot-{uuid4().hex}.tmp").resolve()
    try:
        shutil.copyfile(source_path, temporary, follow_symlinks=False)
        validate_docx_file_path(temporary)
        copied_sha256, copied_size = file_digest_and_size(temporary)
        if copied_sha256 != source_sha256 or copied_size != source_size:
            raise DocumentStorageError("El hash del snapshot no coincide con el origen.")
        os.replace(temporary, destination)
        try:
            destination.chmod(0o444)
        except OSError:
            current_app.logger.debug("No se pudo marcar snapshot como solo lectura: %s", stored_name)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise

    return StoredSnapshotFile(
        stored_name=stored_name,
        storage_path=(relative_directory / stored_name).as_posix(),
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=source_size,
        sha256=source_sha256,
    )


def delete_snapshot_file(storage_path: str | None) -> None:
    if not storage_path:
        return
    path = resolve_document_path(storage_path)
    if "snapshots" not in path.parts:
        raise DocumentStorageError("La ruta no pertenece al area de snapshots.")
    try:
        path.chmod(0o666)
    except OSError:
        current_app.logger.debug("No se pudo ajustar permisos antes de eliminar snapshot: %s", storage_path)
    path.unlink(missing_ok=True)


def store_pdf_artifact_copy(
    *,
    source_path: Path,
    documento,
    version_doc,
    source_snapshot,
    expected_sha256: str | None = None,
) -> StoredPdfArtifactFile:
    """Guarda un PDF definitivo como archivo privado independiente e inmutable."""
    if source_path.is_symlink():
        raise DocumentStorageError("No se permite almacenar un PDF desde un enlace simbolico.")
    if not source_path.is_file():
        raise DocumentStorageError("El PDF temporal no existe.")
    source_sha256, source_size = file_digest_and_size(source_path)
    if expected_sha256 and source_sha256 != expected_sha256:
        raise DocumentStorageError("El hash del PDF no coincide con la validacion previa.")

    relative_directory = Path(
        f"empresa_{int(documento.empresa_id)}",
        f"documento_{int(documento.id)}",
        f"v{_safe_version(getattr(version_doc, 'version', version_doc.id))}",
        "pdf",
    )
    destination_directory = (_storage_root() / relative_directory).resolve()
    destination_directory.mkdir(parents=True, exist_ok=True)
    if os.path.commonpath([str(_storage_root()), str(destination_directory)]) != str(_storage_root()):
        raise DocumentStorageError("La ruta de artefactos PDF no es valida.")

    snapshot_hash = _safe_hash_part(getattr(source_snapshot, "archivo_sha256", ""))[:12]
    pdf_hash = _safe_hash_part(source_sha256)[:12]
    stored_name = f"aprobado-{snapshot_hash}-{pdf_hash}.pdf"
    destination = (destination_directory / stored_name).resolve()
    if os.path.commonpath([str(_storage_root()), str(destination)]) != str(_storage_root()):
        raise DocumentStorageError("La ruta del PDF aprobado no es valida.")
    if destination.exists():
        raise DocumentStorageError("Ya existe un PDF aprobado en la ruta destino.")
    if destination.is_symlink():
        raise DocumentStorageError("No se permite sobrescribir enlaces simbolicos.")

    temporary = (destination_directory / f".pdf-{uuid4().hex}.tmp").resolve()
    try:
        shutil.copyfile(source_path, temporary, follow_symlinks=False)
        copied_sha256, copied_size = file_digest_and_size(temporary)
        if copied_sha256 != source_sha256 or copied_size != source_size:
            raise DocumentStorageError("El hash del PDF copiado no coincide con el origen.")
        os.replace(temporary, destination)
        try:
            destination.chmod(0o444)
        except OSError:
            current_app.logger.debug("No se pudo marcar PDF como solo lectura: %s", stored_name)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise

    return StoredPdfArtifactFile(
        stored_name=stored_name,
        storage_path=(relative_directory / stored_name).as_posix(),
        mime_type="application/pdf",
        size=source_size,
        sha256=source_sha256,
    )


def store_signed_pdf_artifact_copy(
    *,
    source_path: Path,
    documento,
    version_doc,
    source_artifact,
    signed_revision: int,
    final: bool = False,
    expected_sha256: str | None = None,
) -> StoredPdfArtifactFile:
    """Guarda un PDF firmado parcial/final como artefacto privado e inmutable."""
    if source_path.is_symlink():
        raise DocumentStorageError("No se permite almacenar un PDF firmado desde un enlace simbolico.")
    if not source_path.is_file():
        raise DocumentStorageError("El PDF firmado temporal no existe.")
    source_sha256, source_size = file_digest_and_size(source_path)
    if expected_sha256 and source_sha256 != expected_sha256:
        raise DocumentStorageError("El hash del PDF firmado no coincide con la validacion previa.")

    relative_directory = Path(
        f"empresa_{int(documento.empresa_id)}",
        f"documento_{int(documento.id)}",
        f"v{_safe_version(getattr(version_doc, 'version', version_doc.id))}",
        "pdf",
        "firmas",
    )
    destination_directory = (_storage_root() / relative_directory).resolve()
    destination_directory.mkdir(parents=True, exist_ok=True)
    if os.path.commonpath([str(_storage_root()), str(destination_directory)]) != str(_storage_root()):
        raise DocumentStorageError("La ruta de artefactos PDF firmados no es valida.")

    source_hash = _safe_hash_part(getattr(source_artifact, "archivo_sha256", ""))[:12]
    pdf_hash = _safe_hash_part(source_sha256)[:12]
    prefix = "firmado-final" if final else "firmado-parcial"
    stored_name = f"{prefix}-r{int(signed_revision)}-{source_hash}-{pdf_hash}.pdf"
    destination = (destination_directory / stored_name).resolve()
    if os.path.commonpath([str(_storage_root()), str(destination)]) != str(_storage_root()):
        raise DocumentStorageError("La ruta del PDF firmado no es valida.")
    if destination.exists():
        raise DocumentStorageError("Ya existe un PDF firmado en la ruta destino.")
    if destination.is_symlink():
        raise DocumentStorageError("No se permite sobrescribir enlaces simbolicos.")

    temporary = (destination_directory / f".signed-pdf-{uuid4().hex}.tmp").resolve()
    try:
        shutil.copyfile(source_path, temporary, follow_symlinks=False)
        copied_sha256, copied_size = file_digest_and_size(temporary)
        if copied_sha256 != source_sha256 or copied_size != source_size:
            raise DocumentStorageError("El hash del PDF firmado copiado no coincide con el origen.")
        os.replace(temporary, destination)
        try:
            destination.chmod(0o444)
        except OSError:
            current_app.logger.debug("No se pudo marcar PDF firmado como solo lectura: %s", stored_name)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise

    return StoredPdfArtifactFile(
        stored_name=stored_name,
        storage_path=(relative_directory / stored_name).as_posix(),
        mime_type="application/pdf",
        size=source_size,
        sha256=source_sha256,
    )


def delete_pdf_artifact_file(storage_path: str | None) -> None:
    if not storage_path:
        return
    path = resolve_document_path(storage_path)
    if "pdf" not in path.parts:
        raise DocumentStorageError("La ruta no pertenece al area de PDF.")
    try:
        path.chmod(0o666)
    except OSError:
        current_app.logger.debug("No se pudo ajustar permisos antes de eliminar PDF: %s", storage_path)
    path.unlink(missing_ok=True)


def restore_working_copy_from_snapshot(*, snapshot_storage_path: str, version_doc) -> AtomicDocumentReplacement:
    snapshot_path = resolve_document_path(snapshot_storage_path)
    if snapshot_path.is_symlink() or not snapshot_path.is_file():
        raise DocumentStorageError("El snapshot no esta disponible para restauracion.")
    validate_docx_file_path(snapshot_path)
    return prepare_document_file_replacement(version_doc, snapshot_path)


def resolve_document_path(storage_path: str) -> Path:
    if not storage_path:
        raise DocumentStorageError("El documento no tiene una ruta privada registrada.")

    root = _storage_root()
    candidate = (root / Path(storage_path)).resolve()
    if os.path.commonpath([str(root), str(candidate)]) != str(root):
        raise DocumentStorageError("La ruta privada del documento no es válida.")
    if candidate.is_symlink():
        raise DocumentStorageError("La ruta privada del documento no puede ser un enlace simbolico.")
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
