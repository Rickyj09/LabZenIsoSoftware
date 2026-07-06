from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from app.models.documentos import Documento, DocumentoAprobacion, DocumentoVersion
from app.security.permissions import user_has_permission


def _can_review_documents(user):
    return (
        user_has_permission(user, "documentos.aprobar")
        or user_has_permission(user, "documentos.rechazar")
    )


def _pending_query(user):
    return (
        DocumentoVersion.query
        .join(Documento, DocumentoVersion.documento_id == Documento.id)
        .filter(
            DocumentoVersion.empresa_id == user.empresa_id,
            Documento.empresa_id == user.empresa_id,
            DocumentoVersion.estado == "EN_REVISION",
            Documento.estado != "OBSOLETO",
            or_(
                and_(
                    DocumentoVersion.revisado_por_id.is_(None),
                    DocumentoVersion.aprobado_por_id.is_(None),
                ),
                DocumentoVersion.revisado_por_id == user.id,
                DocumentoVersion.aprobado_por_id == user.id,
            ),
        )
    )


def count_pending_documents_for_user(user):
    if not _can_review_documents(user):
        return 0
    return _pending_query(user).count()


def get_pending_documents_for_user(user):
    if not _can_review_documents(user):
        return []

    versions = (
        _pending_query(user)
        .options(
            joinedload(DocumentoVersion.documento),
            joinedload(DocumentoVersion.elaborado_por),
        )
        .order_by(
            DocumentoVersion.fecha_envio_revision.asc(),
            DocumentoVersion.id.asc(),
        )
        .all()
    )
    if not versions:
        return versions

    events = (
        DocumentoAprobacion.query
        .filter(
            DocumentoAprobacion.empresa_id == user.empresa_id,
            DocumentoAprobacion.documento_version_id.in_([item.id for item in versions]),
            DocumentoAprobacion.accion == "ENVIAR_REVISION",
        )
        .options(joinedload(DocumentoAprobacion.usuario))
        .order_by(DocumentoAprobacion.fecha_accion.desc(), DocumentoAprobacion.id.desc())
        .all()
    )
    sender_by_version = {}
    for event in events:
        sender_by_version.setdefault(event.documento_version_id, event.usuario)
    for version in versions:
        version.pending_submitted_by = sender_by_version.get(version.id) or version.elaborado_por
    return versions


def user_has_document_pending_alert(user):
    return count_pending_documents_for_user(user) > 0
