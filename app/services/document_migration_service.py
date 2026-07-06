import mimetypes
from dataclasses import dataclass

from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.documentos import DocumentoVersion
from app.services.storage_service import (
    DocumentStorageError,
    apply_stored_file_metadata,
    delete_document_file,
    resolve_legacy_document_path,
    store_document_file,
)


@dataclass
class HistoricalMigrationSummary:
    encontrados: int = 0
    simulados: int = 0
    migrados: int = 0
    omitidos: int = 0
    no_encontrados: int = 0
    errores: int = 0


def migrate_historical_document_files(*, apply=False, reporter=None, versions=None):
    report = reporter or (lambda message: None)
    summary = HistoricalMigrationSummary()

    if versions is None:
        versions = (
            DocumentoVersion.query
            .filter(
                DocumentoVersion.archivo_url.isnot(None),
                DocumentoVersion.archivo_storage_path.is_(None),
            )
            .order_by(DocumentoVersion.id.asc())
            .all()
        )

    for version_doc in versions:
        summary.encontrados += 1
        stored_file = None

        if version_doc.archivo_storage_path:
            summary.omitidos += 1
            report(f"OMITIDO versión_id={version_doc.id}: ya tiene storage privado.")
            continue

        documento = version_doc.documento
        if not documento or version_doc.empresa_id != documento.empresa_id:
            summary.omitidos += 1
            report(f"OMITIDO versión_id={version_doc.id}: empresa/documento inconsistente.")
            continue

        try:
            source = resolve_legacy_document_path(version_doc.archivo_url)
        except DocumentStorageError as exc:
            summary.omitidos += 1
            report(f"OMITIDO versión_id={version_doc.id}: referencia histórica inválida ({exc})")
            continue

        if not source.is_file():
            summary.no_encontrados += 1
            report(f"NO_ENCONTRADO versión_id={version_doc.id}: no existe el archivo histórico.")
            continue

        if not apply:
            summary.simulados += 1
            report(f"SIMULADO versión_id={version_doc.id}: listo para migrar.")
            continue

        try:
            with source.open("rb") as stream:
                legacy_file = FileStorage(
                    stream=stream,
                    filename=source.name,
                    content_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                )
                stored_file = store_document_file(
                    legacy_file,
                    documento=version_doc.documento,
                    version=version_doc.version,
                )

            apply_stored_file_metadata(version_doc, stored_file)
            db.session.commit()
            summary.migrados += 1
            report(f"MIGRADO versión_id={version_doc.id}: metadatos y storage privado actualizados.")
        except Exception as exc:
            db.session.rollback()
            delete_document_file(stored_file.storage_path if stored_file else None)
            summary.errores += 1
            report(f"ERROR versión_id={version_doc.id}: {exc}")

    return summary
