from sqlalchemy import and_, case, exists, func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion


TECHNICAL_DOCUMENT_STATES = ("EN_ELABORACION", "EN_REVISION", "EN_APROBACION", "APROBADO", "RECHAZADO", "OBSOLETO")
FLOW_DOCUMENT_STATES = ("EN_ELABORACION", "EN_REVISION", "EN_APROBACION", "RECHAZADO", "VIGENTE", "EN_ACTUALIZACION", "OBSOLETO")
PREPARATION_STATES = ("EN_ELABORACION", "EN_REVISION", "EN_APROBACION", "RECHAZADO")


def _company_documents_query(user):
    return Documento.query.filter(Documento.empresa_id == user.empresa_id)


def _company_versions_query(user):
    return (
        DocumentoVersion.query
        .join(Documento, DocumentoVersion.documento_id == Documento.id)
        .filter(
            DocumentoVersion.empresa_id == user.empresa_id,
            Documento.empresa_id == user.empresa_id,
        )
    )


def _assigned_pending_version_conditions(user):
    return (
        DocumentoVersion.empresa_id == user.empresa_id,
        DocumentoVersion.documento_id == Documento.id,
        DocumentoVersion.empresa_id == Documento.empresa_id,
        DocumentoVersion.estado.in_(("EN_REVISION", "EN_APROBACION")),
        or_(
            and_(DocumentoVersion.estado == "EN_REVISION", DocumentoVersion.revisado_por_id == user.id),
            and_(DocumentoVersion.estado == "EN_APROBACION", DocumentoVersion.aprobado_por_id == user.id),
        ),
    )


def _assigned_pending_exists(user):
    return (
        exists()
        .where(and_(*_assigned_pending_version_conditions(user)))
        .correlate(Documento)
    )


def _assigned_pending_date_subquery(user):
    return (
        db.session.query(func.min(DocumentoVersion.fecha_envio_revision))
        .filter(and_(*_assigned_pending_version_conditions(user)))
        .correlate(Documento)
        .scalar_subquery()
    )


def _annotate_assigned_pending_documents(documents, user):
    document_ids = [document.id for document in documents]
    pending_document_ids = set()
    pending_dates_by_document_id = {}
    if document_ids:
        rows = (
            db.session.query(
                DocumentoVersion.documento_id,
                func.min(DocumentoVersion.fecha_envio_revision),
            )
            .join(Documento, DocumentoVersion.documento_id == Documento.id)
            .filter(
                DocumentoVersion.empresa_id == user.empresa_id,
                Documento.empresa_id == user.empresa_id,
                DocumentoVersion.documento_id.in_(document_ids),
                DocumentoVersion.estado.in_(("EN_REVISION", "EN_APROBACION")),
                or_(
                    and_(DocumentoVersion.estado == "EN_REVISION", DocumentoVersion.revisado_por_id == user.id),
                    and_(DocumentoVersion.estado == "EN_APROBACION", DocumentoVersion.aprobado_por_id == user.id),
                ),
            )
            .group_by(DocumentoVersion.documento_id)
            .all()
        )
        pending_document_ids = {document_id for document_id, _pending_date in rows}
        pending_dates_by_document_id = {document_id: pending_date for document_id, pending_date in rows}

    for document in documents:
        pending_date = pending_dates_by_document_id.get(document.id)
        document.pending_for_current_user = document.id in pending_document_ids
        document.pending_for_current_user_date = pending_date
    return documents


def count_by_document_status(user):
    rows = (
        _company_documents_query(user)
        .with_entities(Documento.estado, func.count(Documento.id))
        .group_by(Documento.estado)
        .all()
    )
    counts = {state: 0 for state in TECHNICAL_DOCUMENT_STATES}
    counts.update({state: count for state, count in rows})
    return counts


def get_documents_in_update_count(user):
    preparation_exists = (
        exists()
        .where(
            and_(
                DocumentoVersion.documento_id == Documento.id,
                DocumentoVersion.empresa_id == Documento.empresa_id,
                DocumentoVersion.estado.in_(PREPARATION_STATES),
                DocumentoVersion.id != Documento.version_vigente_id,
            )
        )
        .correlate(Documento)
    )
    return (
        _company_documents_query(user)
        .join(
            DocumentoVersion,
            and_(
                Documento.version_vigente_id == DocumentoVersion.id,
                DocumentoVersion.estado == "APROBADO",
            ),
        )
        .filter(Documento.version_vigente_id.isnot(None), preparation_exists)
        .count()
    )


def count_by_flow_status(user):
    in_update_count = get_documents_in_update_count(user)
    current_approved_exists = (
        exists()
        .where(
            and_(
                DocumentoVersion.id == Documento.version_vigente_id,
                DocumentoVersion.empresa_id == Documento.empresa_id,
                DocumentoVersion.estado == "APROBADO",
            )
        )
        .correlate(Documento)
    )
    preparation_exists = (
        exists()
        .where(
            and_(
                DocumentoVersion.documento_id == Documento.id,
                DocumentoVersion.empresa_id == Documento.empresa_id,
                DocumentoVersion.estado.in_(PREPARATION_STATES),
                DocumentoVersion.id != Documento.version_vigente_id,
            )
        )
        .correlate(Documento)
    )

    counts = {state: 0 for state in FLOW_DOCUMENT_STATES}
    counts["EN_ELABORACION"] = _company_documents_query(user).filter(Documento.estado == "EN_ELABORACION").count()
    counts["EN_REVISION"] = _company_documents_query(user).filter(Documento.estado == "EN_REVISION").count()
    counts["EN_APROBACION"] = _company_documents_query(user).filter(Documento.estado == "EN_APROBACION").count()
    counts["RECHAZADO"] = _company_documents_query(user).filter(Documento.estado == "RECHAZADO").count()
    counts["OBSOLETO"] = _company_documents_query(user).filter(Documento.estado == "OBSOLETO").count()
    counts["EN_ACTUALIZACION"] = in_update_count
    counts["VIGENTE"] = (
        _company_documents_query(user)
        .filter(
            Documento.estado == "APROBADO",
            Documento.version_vigente_id.isnot(None),
            current_approved_exists,
            ~preparation_exists,
        )
        .count()
    )
    return counts


def count_by_document_type(user):
    rows = (
        _company_documents_query(user)
        .with_entities(Documento.tipo_documento, func.count(Documento.id))
        .group_by(Documento.tipo_documento)
        .order_by(Documento.tipo_documento.asc())
        .all()
    )
    return [(document_type or "SIN_TIPO", count) for document_type, count in rows]


def get_recent_documents(user, limit=5):
    pending_exists = _assigned_pending_exists(user)
    pending_date = _assigned_pending_date_subquery(user)
    documents = (
        _company_documents_query(user)
        .options(
            joinedload(Documento.elaborado_por),
            joinedload(Documento.version_vigente),
        )
        .order_by(
            case((pending_exists, 0), else_=1),
            pending_date.asc(),
            Documento.updated_at.desc(),
            Documento.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return _annotate_assigned_pending_documents(documents, user)


def get_pending_documents_assigned_to_user(user, limit=None):
    query = (
        _company_versions_query(user)
        .filter(
            DocumentoVersion.estado.in_(("EN_REVISION", "EN_APROBACION")),
            or_(
                and_(DocumentoVersion.estado == "EN_REVISION", DocumentoVersion.revisado_por_id == user.id),
                and_(DocumentoVersion.estado == "EN_APROBACION", DocumentoVersion.aprobado_por_id == user.id),
            ),
        )
        .options(joinedload(DocumentoVersion.documento))
        .order_by(
            DocumentoVersion.fecha_envio_revision.asc(),
            DocumentoVersion.id.asc(),
        )
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def count_pending_documents_assigned_to_user(user):
    return (
        _company_versions_query(user)
        .filter(
            DocumentoVersion.estado.in_(("EN_REVISION", "EN_APROBACION")),
            or_(
                and_(DocumentoVersion.estado == "EN_REVISION", DocumentoVersion.revisado_por_id == user.id),
                and_(DocumentoVersion.estado == "EN_APROBACION", DocumentoVersion.aprobado_por_id == user.id),
            ),
        )
        .count()
    )


def get_recent_obsolete_documents(user, limit=5):
    return (
        _company_versions_query(user)
        .filter(DocumentoVersion.estado == "OBSOLETO")
        .options(joinedload(DocumentoVersion.documento))
        .order_by(
            DocumentoVersion.fecha_obsolescencia.desc().nullslast(),
            DocumentoVersion.updated_at.desc(),
            DocumentoVersion.id.desc(),
        )
        .limit(limit)
        .all()
    )


def get_documents_without_file_count(user):
    return (
        _company_versions_query(user)
        .filter(DocumentoVersion.estado.notin_(("OBSOLETO", "SUSTITUIDO")))
        .filter(
            or_(
                and_(
                    DocumentoVersion.archivo_storage_path.is_(None),
                    DocumentoVersion.archivo_url.is_(None),
                ),
                DocumentoVersion.archivo_nombre_guardado.is_(None),
            )
        )
        .count()
    )


def get_document_dashboard_stats(user):
    pending_count = count_pending_documents_assigned_to_user(user)
    technical_status = count_by_document_status(user)
    flow_status = count_by_flow_status(user)
    total_documents = _company_documents_query(user).count()
    current_version_count = (
        _company_documents_query(user)
        .filter(Documento.version_vigente_id.isnot(None))
        .count()
    )
    return {
        "total_documents": total_documents,
        "technical_status": technical_status,
        "flow_status": flow_status,
        "document_types": count_by_document_type(user),
        "pending_count": pending_count,
        "pending_documents": get_pending_documents_assigned_to_user(user, limit=5),
        "recent_documents": get_recent_documents(user, limit=5),
        "recent_obsolete_documents": get_recent_obsolete_documents(user, limit=5),
        "documents_without_file_count": get_documents_without_file_count(user),
        "documents_in_update_count": flow_status["EN_ACTUALIZACION"],
        "documents_with_current_version_count": current_version_count,
    }
