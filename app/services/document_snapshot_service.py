from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func

from app.extensions import db
from app.models.documentos import (
    DocumentoSnapshot,
    DocumentoEdicion,
    DocumentoVersion,
    ESTADO_EDICION_ACTIVA,
    ESTADO_EDICION_ERROR,
    ESTADO_EN_APROBACION,
    ESTADO_EN_ELABORACION,
    ESTADO_EN_REVISION,
    ESTADO_APROBADO,
    ESTADO_RECHAZADO,
    SNAPSHOT_APROBADO,
    SNAPSHOT_DISPONIBLE,
    SNAPSHOT_ENVIO_REVISION,
    SNAPSHOT_RECHAZADO,
)
from app.services.office_document_profile import DOCX_MIME, get_onlyoffice_document_profile
from app.services.storage_service import (
    DocumentStorageError,
    delete_snapshot_file,
    file_digest_and_size,
    finalize_document_file_replacement,
    resolve_document_path,
    restore_document_file_replacement,
    restore_working_copy_from_snapshot,
    store_snapshot_copy,
    validate_onlyoffice_file_path,
)


class DocumentSnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class OfficialDocumentSource:
    kind: str
    documento: object
    version: object
    snapshot: DocumentoSnapshot | None
    storage_path: str
    sha256: str
    size: int | None
    mime_type: str | None
    filename: str


def _now():
    return datetime.now(timezone.utc)


def _normalize_required(value, message, *, max_length=None):
    normalized = (value or "").strip()
    if not normalized:
        raise DocumentSnapshotError(message)
    if max_length and len(normalized) > max_length:
        raise DocumentSnapshotError(f"{message} Longitud mÃ¡xima: {max_length}.")
    return normalized


def _hash_is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


class DocumentSnapshotService:
    def validate_context(self, *, documento, version_doc, usuario):
        if not usuario or usuario.empresa_id != documento.empresa_id:
            raise DocumentSnapshotError("El usuario no pertenece a la empresa del documento.")
        if version_doc.documento_id != documento.id or version_doc.empresa_id != documento.empresa_id:
            raise DocumentSnapshotError("La versiÃ³n no pertenece al documento o empresa indicados.")

    def validate_working_copy(self, version_doc):
        profile = get_onlyoffice_document_profile(version_doc)
        if not profile:
            raise DocumentSnapshotError("La version no es compatible con ONLYOFFICE.")
        if not version_doc.archivo_storage_path:
            raise DocumentSnapshotError("La version no tiene copia de trabajo privada.")
        if not _hash_is_sha256(version_doc.archivo_sha256 or ""):
            raise DocumentSnapshotError("La version no tiene hash SHA-256 valido.")

        try:
            physical_path = resolve_document_path(version_doc.archivo_storage_path)
            validate_onlyoffice_file_path(physical_path, profile)
            actual_sha, actual_size = file_digest_and_size(physical_path)
        except (DocumentStorageError, FileNotFoundError) as exc:
            raise DocumentSnapshotError(str(exc)) from exc

        if actual_sha != version_doc.archivo_sha256:
            raise DocumentSnapshotError("La copia de trabajo no coincide con la metadata registrada.")
        if version_doc.archivo_size and int(version_doc.archivo_size) != int(actual_size):
            raise DocumentSnapshotError("El tamano de la copia de trabajo no coincide con la metadata registrada.")
        return physical_path, actual_sha, actual_size

    def ensure_no_blocking_edit(self, version_doc):
        blocking = (
            DocumentoEdicion.query
            .filter(
                DocumentoEdicion.documento_version_id == version_doc.id,
                DocumentoEdicion.empresa_id == version_doc.empresa_id,
                DocumentoEdicion.estado.in_((ESTADO_EDICION_ACTIVA, ESTADO_EDICION_ERROR)),
            )
            .first()
        )
        if blocking:
            raise DocumentSnapshotError(
                "El documento estÃ¡ abierto para ediciÃ³n. Guarda y cierra la sesiÃ³n antes de continuar."
            )

    def next_sequence(self, version_doc):
        last = (
            db.session.query(func.max(DocumentoSnapshot.secuencia))
            .filter_by(documento_version_id=version_doc.id, empresa_id=version_doc.empresa_id)
            .scalar()
        )
        return int(last or 0) + 1

    def next_review_cycle(self, version_doc):
        last = (
            db.session.query(func.max(DocumentoSnapshot.ciclo_revision))
            .filter(
                DocumentoSnapshot.documento_version_id == version_doc.id,
                DocumentoSnapshot.empresa_id == version_doc.empresa_id,
                DocumentoSnapshot.tipo == SNAPSHOT_ENVIO_REVISION,
            )
            .scalar()
        )
        return int(last or 0) + 1

    def latest_review_snapshot(self, version_doc):
        return (
            DocumentoSnapshot.query
            .filter_by(
                documento_version_id=version_doc.id,
                empresa_id=version_doc.empresa_id,
                tipo=SNAPSHOT_ENVIO_REVISION,
                estado=SNAPSHOT_DISPONIBLE,
            )
            .order_by(DocumentoSnapshot.ciclo_revision.desc(), DocumentoSnapshot.secuencia.desc())
            .first()
        )

    def approved_snapshot(self, version_doc):
        return (
            DocumentoSnapshot.query
            .filter_by(
                documento_version_id=version_doc.id,
                empresa_id=version_doc.empresa_id,
                tipo=SNAPSHOT_APROBADO,
                estado=SNAPSHOT_DISPONIBLE,
            )
            .order_by(DocumentoSnapshot.secuencia.desc())
            .first()
        )

    def rejection_snapshot(self, version_doc):
        return (
            DocumentoSnapshot.query
            .filter_by(
                documento_version_id=version_doc.id,
                empresa_id=version_doc.empresa_id,
                tipo=SNAPSHOT_RECHAZADO,
                estado=SNAPSHOT_DISPONIBLE,
            )
            .order_by(DocumentoSnapshot.secuencia.desc())
            .first()
        )

    def create_review_snapshot(self, *, documento, version_doc, usuario, resumen_cambios, hojas_modificadas):
        self.validate_context(documento=documento, version_doc=version_doc, usuario=usuario)
        if version_doc.estado != ESTADO_EN_ELABORACION:
            raise DocumentSnapshotError("Solo una versiÃ³n en elaboraciÃ³n puede congelarse para revisiÃ³n.")
        self.ensure_no_blocking_edit(version_doc)
        resumen = _normalize_required(resumen_cambios, "El resumen de modificaciones es obligatorio.", max_length=2000)
        hojas = _normalize_required(hojas_modificadas, "Las hojas modificadas son obligatorias o indica No aplica.", max_length=500)
        source_path, source_sha, source_size = self.validate_working_copy(version_doc)
        sequence = self.next_sequence(version_doc)
        cycle = self.next_review_cycle(version_doc)
        return self._create_physical_snapshot(
            documento=documento,
            version_doc=version_doc,
            usuario=usuario,
            tipo=SNAPSHOT_ENVIO_REVISION,
            ciclo_revision=cycle,
            secuencia=sequence,
            source_path=source_path,
            hash_origen=source_sha,
            resumen_cambios=resumen,
            hojas_modificadas=hojas,
            comentario=resumen,
            metadata_json={"source": "working_copy", "source_size": source_size},
        )

    def create_approved_snapshot(self, *, documento, version_doc, usuario, comentario=None):
        self.validate_context(documento=documento, version_doc=version_doc, usuario=usuario)
        if version_doc.estado != ESTADO_EN_APROBACION:
            raise DocumentSnapshotError("Solo una versiÃ³n en revisiÃ³n puede aprobarse.")
        self.ensure_no_blocking_edit(version_doc)
        review_snapshot = self.latest_review_snapshot(version_doc)
        if not review_snapshot:
            raise DocumentSnapshotError("No existe snapshot de revisiÃ³n para aprobar.")
        if self.approved_snapshot(version_doc):
            return self.approved_snapshot(version_doc)
        source_path = self.resolve_snapshot_path(review_snapshot)
        sequence = self.next_sequence(version_doc)
        return self._create_physical_snapshot(
            documento=documento,
            version_doc=version_doc,
            usuario=usuario,
            tipo=SNAPSHOT_APROBADO,
            ciclo_revision=review_snapshot.ciclo_revision,
            secuencia=sequence,
            source_path=source_path,
            hash_origen=review_snapshot.archivo_sha256,
            comentario=(comentario or "").strip() or None,
            snapshot_origen_id=review_snapshot.id,
            resumen_cambios=review_snapshot.resumen_cambios,
            hojas_modificadas=review_snapshot.hojas_modificadas,
            metadata_json={"source": "review_snapshot", "review_snapshot_id": review_snapshot.id},
        )

    def create_rejection_marker(self, *, documento, version_doc, usuario, comentario):
        self.validate_context(documento=documento, version_doc=version_doc, usuario=usuario)
        if version_doc.estado not in (ESTADO_EN_REVISION, ESTADO_EN_APROBACION):
            raise DocumentSnapshotError("Solo una versiÃ³n en revisiÃ³n puede rechazarse.")
        comment = _normalize_required(comentario, "El comentario de rechazo es obligatorio.", max_length=2000)
        review_snapshot = self.latest_review_snapshot(version_doc)
        if not review_snapshot:
            raise DocumentSnapshotError("No existe snapshot de revisiÃ³n para rechazar.")
        existing = (
            DocumentoSnapshot.query
            .filter_by(
                documento_version_id=version_doc.id,
                empresa_id=version_doc.empresa_id,
                tipo=SNAPSHOT_RECHAZADO,
                ciclo_revision=review_snapshot.ciclo_revision,
            )
            .first()
        )
        if existing:
            return existing
        snapshot = DocumentoSnapshot(
            empresa_id=documento.empresa_id,
            public_id=uuid4().hex,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            secuencia=self.next_sequence(version_doc),
            ciclo_revision=review_snapshot.ciclo_revision,
            tipo=SNAPSHOT_RECHAZADO,
            estado=SNAPSHOT_DISPONIBLE,
            storage_path=None,
            archivo_nombre_interno=None,
            archivo_nombre_original=review_snapshot.archivo_nombre_original,
            archivo_mime=review_snapshot.archivo_mime,
            archivo_size=review_snapshot.archivo_size,
            archivo_sha256=review_snapshot.archivo_sha256,
            hash_origen=review_snapshot.archivo_sha256,
            creado_por_id=usuario.id,
            creado_en=_now(),
            snapshot_origen_id=review_snapshot.id,
            comentario=comment,
            resumen_cambios=review_snapshot.resumen_cambios,
            hojas_modificadas=review_snapshot.hojas_modificadas,
            metadata_json={"source": "review_snapshot_reference", "review_snapshot_id": review_snapshot.id},
            inmutable=True,
        )
        db.session.add(snapshot)
        db.session.flush()
        return snapshot

    def restore_working_from_latest_review_if_needed(self, *, documento, version_doc):
        review_snapshot = self.latest_review_snapshot(version_doc)
        if not review_snapshot:
            raise DocumentSnapshotError("No existe snapshot de revisiÃ³n para restaurar la copia de trabajo.")
        if version_doc.archivo_sha256 == review_snapshot.archivo_sha256:
            return False

        replacement = restore_working_copy_from_snapshot(
            snapshot_storage_path=review_snapshot.storage_path,
            version_doc=version_doc,
        )
        try:
            version_doc.archivo_sha256 = replacement.sha256
            version_doc.archivo_size = replacement.size
            profile = get_onlyoffice_document_profile(version_doc)
            version_doc.archivo_mime = version_doc.archivo_mime or (profile.mime_type if profile else DOCX_MIME)
            db.session.flush()
        except Exception:
            restore_document_file_replacement(replacement)
            raise
        finalize_document_file_replacement(replacement)
        return True

    def attach_event(self, snapshot, event):
        if snapshot and event:
            db.session.flush()
            snapshot.workflow_evento_id = event.id
            db.session.flush()
        return snapshot

    def resolve_snapshot_path(self, snapshot):
        if snapshot.snapshot_origen_id and not snapshot.storage_path:
            snapshot = snapshot.snapshot_origen
        if not snapshot or not snapshot.storage_path:
            raise DocumentSnapshotError("El snapshot no tiene archivo fÃ­sico asociado.")
        try:
            path = resolve_document_path(snapshot.storage_path)
            profile = get_onlyoffice_document_profile(snapshot.archivo_nombre_original or snapshot.archivo_nombre_interno or snapshot.storage_path)
            validate_onlyoffice_file_path(path, profile)
        except (DocumentStorageError, FileNotFoundError) as exc:
            raise DocumentSnapshotError(str(exc)) from exc
        actual_sha, actual_size = file_digest_and_size(path)
        if actual_sha != snapshot.archivo_sha256:
            raise DocumentSnapshotError("El hash fÃ­sico del snapshot no coincide con la metadata.")
        if snapshot.archivo_size and int(snapshot.archivo_size) != int(actual_size):
            raise DocumentSnapshotError("El tamaÃ±o fÃ­sico del snapshot no coincide con la metadata.")
        return path

    def official_source_for_version(self, *, documento, version_doc):
        if version_doc.estado == ESTADO_EN_ELABORACION:
            return OfficialDocumentSource(
                kind="working",
                documento=documento,
                version=version_doc,
                snapshot=None,
                storage_path=version_doc.archivo_storage_path,
                sha256=version_doc.archivo_sha256,
                size=version_doc.archivo_size,
                mime_type=version_doc.archivo_mime,
                filename=version_doc.archivo_nombre_original or "documento",
            )
        snapshot = None
        if version_doc.estado in (ESTADO_EN_REVISION, ESTADO_EN_APROBACION):
            snapshot = self.latest_review_snapshot(version_doc)
        elif version_doc.estado == ESTADO_APROBADO:
            snapshot = self.approved_snapshot(version_doc) or self.latest_review_snapshot(version_doc)
        elif version_doc.estado == ESTADO_RECHAZADO:
            snapshot = self.rejection_snapshot(version_doc) or self.latest_review_snapshot(version_doc)
        else:
            snapshot = self.approved_snapshot(version_doc) or self.latest_review_snapshot(version_doc)
        if not snapshot:
            return self.official_source_for_version_as_working(documento=documento, version_doc=version_doc)
        physical_snapshot = snapshot.snapshot_origen if snapshot.snapshot_origen_id and not snapshot.storage_path else snapshot
        return OfficialDocumentSource(
            kind="snapshot",
            documento=documento,
            version=version_doc,
            snapshot=snapshot,
            storage_path=physical_snapshot.storage_path,
            sha256=physical_snapshot.archivo_sha256,
            size=physical_snapshot.archivo_size,
            mime_type=physical_snapshot.archivo_mime,
            filename=snapshot.archivo_nombre_original or version_doc.archivo_nombre_original or "documento",
        )

    def official_source_for_version_as_working(self, *, documento, version_doc):
        return OfficialDocumentSource(
            kind="working",
            documento=documento,
            version=version_doc,
            snapshot=None,
            storage_path=version_doc.archivo_storage_path,
            sha256=version_doc.archivo_sha256,
            size=version_doc.archivo_size,
            mime_type=version_doc.archivo_mime,
            filename=version_doc.archivo_nombre_original or "documento",
        )

    def list_snapshots(self, *, documento):
        return (
            DocumentoSnapshot.query
            .filter_by(documento_id=documento.id, empresa_id=documento.empresa_id)
            .order_by(DocumentoSnapshot.secuencia.asc(), DocumentoSnapshot.id.asc())
            .all()
        )

    def _create_physical_snapshot(
        self,
        *,
        documento,
        version_doc,
        usuario,
        tipo,
        ciclo_revision,
        secuencia,
        source_path: Path,
        hash_origen,
        comentario=None,
        resumen_cambios=None,
        hojas_modificadas=None,
        snapshot_origen_id=None,
        metadata_json=None,
    ):
        stored = None
        try:
            stored = store_snapshot_copy(
                source_path=source_path,
                documento=documento,
                version_doc=version_doc,
                secuencia=secuencia,
                tipo=tipo,
            )
            if stored.sha256 != hash_origen:
                raise DocumentSnapshotError("El snapshot no coincide con el hash de origen.")
            snapshot = DocumentoSnapshot(
                empresa_id=documento.empresa_id,
                public_id=uuid4().hex,
                documento_id=documento.id,
                documento_version_id=version_doc.id,
                secuencia=secuencia,
                ciclo_revision=ciclo_revision,
                tipo=tipo,
                estado=SNAPSHOT_DISPONIBLE,
                storage_path=stored.storage_path,
                archivo_nombre_interno=stored.stored_name,
                archivo_nombre_original=version_doc.archivo_nombre_original or f"{documento.codigo}_v{version_doc.version}.{get_onlyoffice_document_profile(version_doc).extension}",
                archivo_mime=stored.mime_type,
                archivo_size=stored.size,
                archivo_sha256=stored.sha256,
                hash_origen=hash_origen,
                creado_por_id=usuario.id,
                creado_en=_now(),
                snapshot_origen_id=snapshot_origen_id,
                comentario=(comentario or "").strip() or None,
                resumen_cambios=(resumen_cambios or "").strip() or None,
                hojas_modificadas=(hojas_modificadas or "").strip() or None,
                metadata_json=metadata_json or {},
                inmutable=True,
            )
            db.session.add(snapshot)
            db.session.flush()
            return snapshot
        except Exception:
            if stored:
                delete_snapshot_file(stored.storage_path)
            raise


