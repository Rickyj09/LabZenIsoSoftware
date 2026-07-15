from datetime import datetime, timezone

from app.extensions import db
from app.models.documentos import DocumentoAprobacion, DocumentoVersion
from app.services.document_versioning_service import (
    DocumentVersioningError,
    approve_version as apply_approval,
    get_current_version,
    get_preparation_version,
)
from app.services.onlyoffice_document_edit_service import has_blocking_edit
from app.services.document_snapshot_service import DocumentSnapshotError, DocumentSnapshotService


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
        raise DocumentWorkflowError("No se encontro un usuario valido para la transicion.")
    if usuario.empresa_id != documento.empresa_id:
        raise DocumentWorkflowError("El usuario no pertenece a la empresa del documento.")
    if version_doc.documento_id != documento.id or version_doc.empresa_id != documento.empresa_id:
        raise DocumentWorkflowError("La version no pertenece al documento o empresa indicados.")


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


def send_for_review(
    *,
    documento,
    version_doc,
    usuario,
    comentario=None,
    resumen_cambios=None,
    hojas_modificadas=None,
    ip=None,
    user_agent=None,
):
    _validate_context(documento, version_doc, usuario)
    if documento.estado == "OBSOLETO":
        raise DocumentWorkflowError("No se puede revisar un documento obsoleto.")
    if version_doc.estado != "EN_ELABORACION":
        raise DocumentWorkflowError("Solo una version en elaboracion puede enviarse a revision.")
    if version_doc.id != getattr(get_preparation_version(documento), "id", None):
        raise DocumentWorkflowError("La version seleccionada no es la preparacion activa.")
    if has_blocking_edit(version_doc):
        raise DocumentWorkflowError(
            "El documento esta abierto para edicion. Guarda y cierra la sesion antes de continuar."
        )

    snapshot_service = DocumentSnapshotService()
    try:
        snapshot = snapshot_service.create_review_snapshot(
            documento=documento,
            version_doc=version_doc,
            usuario=usuario,
            resumen_cambios=resumen_cambios if resumen_cambios is not None else comentario,
            hojas_modificadas=hojas_modificadas,
        )
    except DocumentSnapshotError as exc:
        raise DocumentWorkflowError(str(exc)) from exc

    previous_state = version_doc.estado
    version_doc.estado = "EN_REVISION"
    version_doc.fecha_envio_revision = _now()
    version_doc.comentario_revision = (comentario or "").strip() or None
    documento.estado = "EN_REVISION"
    event = record_document_event(
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
    snapshot_service.attach_event(snapshot, event)
    return event


def approve_version(*, documento, version_doc, usuario, comentario=None, ip=None, user_agent=None):
    _validate_context(documento, version_doc, usuario)
    previous_state = version_doc.estado
    previous_current = get_current_version(documento)
    snapshot_service = DocumentSnapshotService()
    try:
        approved_snapshot = snapshot_service.create_approved_snapshot(
            documento=documento,
            version_doc=version_doc,
            usuario=usuario,
            comentario=comentario,
        )
    except DocumentSnapshotError as exc:
        raise DocumentWorkflowError(str(exc)) from exc
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
    snapshot_service.attach_event(approved_snapshot, approval_event)
    if replaced and previous_current and replaced.id == previous_current.id:
        record_document_event(
            documento=documento,
            version_doc=replaced,
            usuario=usuario,
            accion="SUSTITUIR_VERSION",
            estado_anterior="APROBADO",
            estado_nuevo="SUSTITUIDO",
            comentario=f"Sustituida por la version {version_doc.version}.",
            ip=ip,
            user_agent=user_agent,
        )
    return approval_event


def reject_version(*, documento, version_doc, usuario, comentario, ip=None, user_agent=None):
    comment = _require_comment(comentario, "El comentario de rechazo es obligatorio.")
    _validate_context(documento, version_doc, usuario)
    if version_doc.estado != "EN_REVISION":
        raise DocumentWorkflowError("Solo una version en revision puede rechazarse.")
    if version_doc.id != getattr(get_preparation_version(documento), "id", None):
        raise DocumentWorkflowError("La version seleccionada no es la preparacion activa.")

    snapshot_service = DocumentSnapshotService()
    try:
        rejected_snapshot = snapshot_service.create_rejection_marker(
            documento=documento,
            version_doc=version_doc,
            usuario=usuario,
            comentario=comment,
        )
    except DocumentSnapshotError as exc:
        raise DocumentWorkflowError(str(exc)) from exc

    previous_state = version_doc.estado
    version_doc.estado = "RECHAZADO"
    version_doc.fecha_rechazo = _now()
    version_doc.rechazado_por_id = usuario.id
    version_doc.revisado_por_id = version_doc.revisado_por_id or usuario.id
    version_doc.comentario_rechazo = comment
    documento.estado = "APROBADO" if get_current_version(documento) else "RECHAZADO"
    event = record_document_event(
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
    snapshot_service.attach_event(rejected_snapshot, event)
    return event


def return_to_draft(*, documento, version_doc, usuario, comentario, ip=None, user_agent=None):
    comment = _require_comment(comentario, "El comentario de devolucion es obligatorio.")
    _validate_context(documento, version_doc, usuario)
    if version_doc.estado != "RECHAZADO":
        raise DocumentWorkflowError("Solo una version rechazada puede devolverse a elaboracion.")
    if version_doc.id != getattr(get_latest_rejected_version(documento), "id", None):
        raise DocumentWorkflowError("La version rechazada seleccionada no es la mas reciente.")
    if get_preparation_version(documento):
        raise DocumentWorkflowError("Ya existe otra version activa en preparacion.")

    snapshot_service = DocumentSnapshotService()
    try:
        snapshot_service.restore_working_from_latest_review_if_needed(
            documento=documento,
            version_doc=version_doc,
        )
    except DocumentSnapshotError as exc:
        raise DocumentWorkflowError(str(exc)) from exc

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
        raise DocumentWorkflowError("El documento no tiene una version aprobada vigente.")

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
            comentario=f"Preparacion cancelada: {reason}",
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
