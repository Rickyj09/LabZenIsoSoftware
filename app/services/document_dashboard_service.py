from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import joinedload

from app.models.documentos import Documento, DocumentoVersion
from app.services.document_pending_service import get_pending_documents_for_user


TECHNICAL_DOCUMENT_STATES = ("BORRADOR", "EN_REVISION", "APROBADO", "RECHAZADO", "OBSOLETO")
FLOW_DOCUMENT_STATES = ("BORRADOR", "EN_REVISION", "RECHAZADO", "VIGENTE", "EN_ACTUALIZACION", "OBSOLETO")
PREPARATION_STATES = ("BORRADOR", "EN_REVISION", "RECHAZADO")


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
    counts["BORRADOR"] = _company_documents_query(user).filter(Documento.estado == "BORRADOR").count()
    counts["EN_REVISION"] = _company_documents_query(user).filter(Documento.estado == "EN_REVISION").count()
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
    return (
        _company_documents_query(user)
        .options(
            joinedload(Documento.elaborado_por),
            joinedload(Documento.version_vigente),
        )
        .order_by(Documento.updated_at.desc(), Documento.id.desc())
        .limit(limit)
        .all()
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
    pending_documents = get_pending_documents_for_user(user)
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
        "pending_count": len(pending_documents),
        "pending_documents": pending_documents[:5],
        "recent_documents": get_recent_documents(user, limit=5),
        "recent_obsolete_documents": get_recent_obsolete_documents(user, limit=5),
        "documents_without_file_count": get_documents_without_file_count(user),
        "documents_in_update_count": flow_status["EN_ACTUALIZACION"],
        "documents_with_current_version_count": current_version_count,
    }
