import zipfile
from dataclasses import dataclass
from pathlib import Path


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class OfficeDocumentProfileError(ValueError):
    pass


@dataclass(frozen=True)
class OnlyOfficeDocumentProfile:
    extension: str
    mime_type: str
    file_type: str
    document_type: str
    required_parts: tuple[str, ...]


ONLYOFFICE_DOCUMENT_PROFILES = {
    "docx": OnlyOfficeDocumentProfile(
        extension="docx",
        mime_type=DOCX_MIME,
        file_type="docx",
        document_type="word",
        required_parts=("[Content_Types].xml", "word/document.xml"),
    ),
    "xlsx": OnlyOfficeDocumentProfile(
        extension="xlsx",
        mime_type=XLSX_MIME,
        file_type="xlsx",
        document_type="cell",
        required_parts=("[Content_Types].xml", "xl/workbook.xml"),
    ),
}


def extension_from_filename(filename: str | None) -> str | None:
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if "." not in name:
        return None
    return name.rsplit(".", 1)[1].lower()


def get_onlyoffice_profile_by_extension(extension: str | None):
    return ONLYOFFICE_DOCUMENT_PROFILES.get((extension or "").lower().lstrip("."))


def get_onlyoffice_document_profile(value):
    if value is None:
        return None
    if isinstance(value, str):
        return get_onlyoffice_profile_by_extension(extension_from_filename(value))

    candidates = (
        getattr(value, "archivo_nombre_original", None),
        getattr(value, "archivo_nombre_guardado", None),
        getattr(value, "archivo_storage_path", None),
        getattr(value, "archivo_url", None),
    )
    for candidate in candidates:
        profile = get_onlyoffice_document_profile(candidate)
        if profile:
            return profile

    mime_type = (getattr(value, "archivo_mime", None) or "").strip().lower()
    for profile in ONLYOFFICE_DOCUMENT_PROFILES.values():
        if mime_type == profile.mime_type:
            return profile
    return None


def is_onlyoffice_supported_version(version_doc) -> bool:
    return get_onlyoffice_document_profile(version_doc) is not None


def validate_ooxml_file_path(path: Path, profile: OnlyOfficeDocumentProfile) -> None:
    if path.is_symlink():
        raise OfficeDocumentProfileError("No se permiten enlaces simbolicos como documento Office.")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            for required in profile.required_parts:
                if required not in names:
                    raise OfficeDocumentProfileError(
                        f"El archivo {profile.extension.upper()} no contiene {required}."
                    )
            lowered_names = {name.lower() for name in names}
            if any(name.endswith("vbaproject.bin") for name in lowered_names):
                raise OfficeDocumentProfileError("Los archivos Office con macros no estan permitidos.")
            content_types = archive.read("[Content_Types].xml").decode("utf-8", errors="ignore").lower()
            if "macroenabled" in content_types or "vnd.ms-office.vbaproject" in content_types:
                raise OfficeDocumentProfileError("Los archivos Office con macros no estan permitidos.")
    except zipfile.BadZipFile as exc:
        raise OfficeDocumentProfileError(
            f"El archivo {profile.extension.upper()} recibido no es un ZIP OOXML valido."
        ) from exc
