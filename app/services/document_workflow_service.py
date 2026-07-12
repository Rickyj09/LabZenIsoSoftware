from datetime import datetime, timezone

from app.extensions import db
from app.models.documentos import DocumentoAprobacion, DocumentoVersion
from app.services.document_versioning_service import (
    DocumentVersioningError,
    approve_version as apply_approval,
    get_current_version,
    get_preparation_version,
)


class DocumentWorkflowError(DocumentVersioningError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _require_comment(comment, message):
    normalized = (comment or "").strip()
    if not normalized:
        raise DocumentWorkflowError(message)
    return normalized


def _validate_context(documento, version_doc, usuario):
    if not usuario or not getattr(usuario, "id", None):
        raise DocumentWorkflowError("No se encontró un usuario válido para la transición.")
    if usuario.empresa_id != documento.empresa_id:
        raise DocumentWorkflowError("El usuario no pertenece a la empresa del documento.")
    if version_doc.documento_id != documento.id or version_doc.empresa_id != documento.empresa_id:
        raise DocumentWorkflowError("La versión no pertenece al documento o empresa indicados.")


def record_document_event(
    *,
    documento,
    version_doc,
    usuario,
    accion,
    estado_anterior,
    estado_nuevo,
    comentario=None,
    ip=None,
    user_agent=None,
):
    _validate_context(documento, version_doc, usuario)
    event = DocumentoAprobacion(
        empresa_id=documento.empresa_id,
        documento_id=documento.id,
        documento_version_id=version_doc.id,
        usuario_id=usuario.id,
        accion=accion,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        fecha_accion=_now(),
        comentario=(comentario or "").strip() or None,
        ip=ip,
        user_agent=user_agent,
    )
    db.session.add(event)
    return event


def get_latest_rejected_version(documento):
    return (
        DocumentoVersion.query
        .filter_by(
            documento_id=documento.id,
            empresa_id=documento.empresa_id,
            estado="RECHAZADO",
        )
        .order_by(DocumentoVersion.id.desc())
        .first()
    )


def send_for_review(*, documento, version_doc, usuario, comentario=None, ip=None, user_agent=None):
    _validate_context(documento, version_doc, usuario)
    if documento.estado == "OBSOLETO":
        raise DocumentWorkflowError("No se puede revisar un documento obsoleto.")
    if version_doc.estado != "EN_ELABORACION":
        raise DocumentWorkflowError("Solo una versión en elaboración puede enviarse a revisión.")
    if version_doc.id != getattr(get_preparation_version(documento), "id", None):
        raise DocumentWorkflowError("La versión seleccionada no es la preparación activa.")

    previous_state = version_doc.estado
    version_doc.estado = "EN_REVISION"
    version_doc.fecha_envio_revision = _now()
    version_doc.comentario_revision = (comentario or "").strip() or None
    documento.estado = "EN_REVISION"
    return record_document_event(
        documento=documento,
        version_doc=version_doc,
        usuario=usuario,
        accion="ENVIAR_REVISION",
        estado_anterior=previous_state,
        estado_nuevo=version_doc.estado,
        comentario=comentario,
        ip=ip,
        user_agent=user_agent,
    )


def approve_version(*, documento, version_doc, usuario, comentario=None, ip=None, user_agent=None):
    _validate_context(documento, version_doc, usuario)
    previous_state = version_doc.estado
    previous_current = get_current_version(documento)
    try:
        replaced = apply_approval(
            documento=documento,
            version_doc=version_doc,
            user_id=usuario.id,
        )
    except DocumentVersioningError as exc:
        raise DocumentWorkflowError(str(exc)) from exc

    version_doc.revisado_por_id = version_doc.revisado_por_id or usuario.id
    version_doc.comentario_aprobacion = (comentario or "").strip() or None
    approval_event = record_document_event(
        documento=documento,
        version_doc=version_doc,
        usuario=usuario,
        accion="APROBAR",
        estado_anterior=previous_state,
        estado_nuevo="APROBADO",
        comentario=comentario,
        ip=ip,
        user_agent=user_agent,
    )
    if replaced and previous_current and replaced.id == previous_current.id:
        record_document_event(
            documento=documento,
            version_doc=replaced,
            usuario=usuario,
            accion="SUSTITUIR_VERSION",
            estado_anterior="APROBADO",
            estado_nuevo="SUSTITUIDO",
            comentario=f"Sustituida por la versión {version_doc.version}.",
            ip=ip,
            user_agent=user_agent,
        )
    return approval_event


def reject_version(*, documento, version_doc, usuario, comentario, ip=None, user_agent=None):
    comment = _require_comment(comentario, "El comentario de rechazo es obligatorio.")
    _validate_context(documento, version_doc, usuario)
    if version_doc.estado != "EN_REVISION":
        raise DocumentWorkflowError("Solo una versión en revisión puede rechazarse.")
    if version_doc.id != getattr(get_preparation_version(documento), "id", None):
        raise DocumentWorkflowError("La versión seleccionada no es la preparación activa.")

    previous_state = version_doc.estado
    version_doc.estado = "RECHAZADO"
    version_doc.fecha_rechazo = _now()
    version_doc.rechazado_por_id = usuario.id
    version_doc.revisado_por_id = version_doc.revisado_por_id or usuario.id
    version_doc.comentario_rechazo = comment
    documento.estado = "APROBADO" if get_current_version(documento) else "RECHAZADO"
    return record_document_event(
        documento=documento,
        version_doc=version_doc,
        usuario=usuario,
        accion="RECHAZAR",
        estado_anterior=previous_state,
        estado_nuevo=version_doc.estado,
        comentario=comment,
        ip=ip,
        user_agent=user_agent,
    )


def return_to_draft(*, documento, version_doc, usuario, comentario, ip=None, user_agent=None):
    comment = _require_comment(comentario, "El comentario de devolución es obligatorio.")
    _validate_context(documento, version_doc, usuario)
    if version_doc.estado != "RECHAZADO":
        raise DocumentWorkflowError("Solo una versión rechazada puede devolverse a elaboración.")
    if version_doc.id != getattr(get_latest_rejected_version(documento), "id", None):
        raise DocumentWorkflowError("La versión rechazada seleccionada no es la más reciente.")
    if get_preparation_version(documento):
        raise DocumentWorkflowError("Ya existe otra versión activa en preparación.")

    previous_state = version_doc.estado
    version_doc.estado = "EN_ELABORACION"
    documento.estado = "APROBADO" if get_current_version(documento) else "EN_ELABORACION"
    return record_document_event(
        documento=documento,
        version_doc=version_doc,
        usuario=usuario,
        accion="DEVOLVER_BORRADOR",
        estado_anterior=previous_state,
        estado_nuevo=version_doc.estado,
        comentario=comment,
        ip=ip,
        user_agent=user_agent,
    )


def obsolete_document(*, documento, usuario, motivo, ip=None, user_agent=None):
    reason = _require_comment(motivo, "El motivo de obsolescencia es obligatorio.")
    if usuario.empresa_id != documento.empresa_id:
        raise DocumentWorkflowError("El usuario no pertenece a la empresa del documento.")
    if documento.estado != "APROBADO":
        raise DocumentWorkflowError("Solo un documento aprobado puede obsoletarse.")

    current = get_current_version(documento)
    if not current:
        raise DocumentWorkflowError("El documento no tiene una versión aprobada vigente.")

    preparation = get_preparation_version(documento)
    if preparation:
        previous_preparation_state = preparation.estado
        preparation.estado = "OBSOLETO"
        preparation.fecha_obsolescencia = _now()
        preparation.obsoletado_por_id = usuario.id
        preparation.motivo_obsolescencia = reason
        record_document_event(
            documento=documento,
            version_doc=preparation,
            usuario=usuario,
            accion="OBSOLETAR",
            estado_anterior=previous_preparation_state,
            estado_nuevo="OBSOLETO",
            comentario=f"Preparación cancelada: {reason}",
            ip=ip,
            user_agent=user_agent,
        )

    previous_state = current.estado
    current.estado = "OBSOLETO"
    current.fecha_obsolescencia = _now()
    current.obsoletado_por_id = usuario.id
    current.motivo_obsolescencia = reason
    documento.estado = "OBSOLETO"
    documento.version_vigente_id = None
    documento.version_vigente = None
    return record_document_event(
        documento=documento,
        version_doc=current,
        usuario=usuario,
        accion="OBSOLETAR",
        estado_anterior=previous_state,
        estado_nuevo="OBSOLETO",
        comentario=reason,
        ip=ip,
        user_agent=user_agent,
    )
