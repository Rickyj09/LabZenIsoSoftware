from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.documentos import (
    PUBLICACION_ACCESO_AUTENTICADO,
    PUBLICACION_ACCESO_TOKEN_PUBLICO,
    PUBLICACION_ACTIVA,
    PUBLICACION_OBSOLETA,
    PUBLICACION_PREPARADA,
    PUBLICACION_REVOCADA,
    Documento,
    DocumentoDistribucionDestinatario,
    DocumentoPublicacion,
    DocumentoVersion,
)
from app.security.permissions import current_user_can, require_permission
from app.services.document_distribution_service import (
    DocumentDistributionError,
    DocumentDistributionService,
    MANAGE_DISTRIBUTION_PERMISSION,
    RETRY_DISTRIBUTION_PERMISSION,
)
from app.services.document_email_service import DocumentEmailService
from app.services.document_publication_service import (
    DocumentPublicationError,
    DocumentPublicationService,
    PUBLISH_PERMISSION,
    REVOKE_PERMISSION,
)
from app.services.storage_service import resolve_document_path


bp = Blueprint("documentacion_publicaciones", __name__, url_prefix="/documentos/publicados")


def _request_metadata():
    return {
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
    }


def _load_publication(public_id):
    return DocumentoPublicacion.query.filter_by(public_id=public_id).first_or_404()


def _assert_publication_access(publicacion):
    if publicacion.estado == PUBLICACION_REVOCADA:
        return
    if publicacion.modo_acceso == PUBLICACION_ACCESO_TOKEN_PUBLICO:
        token = request.args.get("token", "")
        if not token or token != publicacion.token:
            abort(404)
        return
    if not current_user.is_authenticated:
        abort(403)
    if current_user.empresa_id != publicacion.empresa_id:
        abort(404)
    if not current_user_can("documentos.ver"):
        abort(403)


@bp.route("/<public_id>")
def ver_publicacion(public_id):
    publicacion = _load_publication(public_id)
    _assert_publication_access(publicacion)
    vigente_actual = DocumentPublicationService().active_publication_for_document(publicacion.documento)
    return render_template(
        "documentacion/publicacion.html",
        publicacion=publicacion,
        vigente_actual=vigente_actual if vigente_actual and vigente_actual.id != publicacion.id else None,
        can_download=(
            publicacion.estado == PUBLICACION_ACTIVA
            and publicacion.pdf_publicado
            and (publicacion.modo_acceso == PUBLICACION_ACCESO_TOKEN_PUBLICO or current_user_can("documentos.descargar"))
        ),
        publication_states={
            "PREPARADA": PUBLICACION_PREPARADA,
            "ACTIVA": PUBLICACION_ACTIVA,
            "OBSOLETA": PUBLICACION_OBSOLETA,
            "REVOCADA": PUBLICACION_REVOCADA,
        },
    )


@bp.route("/<public_id>/pdf")
def descargar_pdf_publicado(public_id):
    publicacion = _load_publication(public_id)
    _assert_publication_access(publicacion)
    if publicacion.estado != PUBLICACION_ACTIVA or not publicacion.pdf_publicado:
        abort(404)
    if publicacion.modo_acceso == PUBLICACION_ACCESO_AUTENTICADO and not current_user_can("documentos.descargar"):
        abort(403)
    path = resolve_document_path(publicacion.pdf_publicado.storage_path)
    return send_file(
        path,
        as_attachment=not bool(request.args.get("inline")),
        download_name=publicacion.pdf_publicado.archivo_nombre_visible or f"{publicacion.documento.codigo}-vigente.pdf",
        mimetype="application/pdf",
        conditional=False,
    )


@bp.route("/<public_id>/qr")
@login_required
@require_permission("documentos.ver")
def descargar_qr(public_id):
    publicacion = DocumentoPublicacion.query.filter_by(public_id=public_id, empresa_id=current_user.empresa_id).first_or_404()
    if not publicacion.qr_storage_key:
        abort(404)
    path = resolve_document_path(publicacion.qr_storage_key)
    return send_file(path, as_attachment=True, download_name=f"{publicacion.documento.codigo}-qr.png", mimetype="image/png")


@bp.route("/documentos/<int:item_id>/versiones/<int:version_id>/publicar", methods=["POST"])
@login_required
@require_permission(PUBLISH_PERMISSION)
def publicar_version(item_id, version_id):
    documento = Documento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first_or_404()
    version = DocumentoVersion.query.filter_by(id=version_id, documento_id=documento.id, empresa_id=current_user.empresa_id).first_or_404()
    try:
        publicacion = DocumentPublicationService().publish_as_current(
            documento=documento,
            version_doc=version,
            usuario=current_user,
            **_request_metadata(),
        )
        flash("Documento publicado como VIGENTE. Los correos quedaron en cola de distribucion.", "success")
        DocumentEmailService().process_pending(publicacion_id=publicacion.id, limite=25)
    except DocumentPublicationError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion.detalle", item_id=documento.id))


@bp.route("/documentos/<int:item_id>/destinatarios", methods=["POST"])
@login_required
@require_permission(MANAGE_DISTRIBUTION_PERMISSION)
def agregar_destinatario(item_id):
    documento = Documento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first_or_404()
    service = DocumentDistributionService()
    try:
        if request.form.get("tipo") == "INTERNO":
            service.add_internal_recipient(
                documento=documento,
                usuario_destino_id=request.form.get("usuario_id", type=int),
                usuario_actor=current_user,
            )
        else:
            service.add_external_recipient(
                documento=documento,
                nombre=request.form.get("nombre"),
                email=request.form.get("email"),
                usuario_actor=current_user,
                grupo=request.form.get("grupo"),
            )
        flash("Destinatario agregado a la lista de distribucion.", "success")
    except DocumentDistributionError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion.detalle", item_id=documento.id))


@bp.route("/destinatarios/<int:destinatario_id>/desactivar", methods=["POST"])
@login_required
@require_permission(MANAGE_DISTRIBUTION_PERMISSION)
def desactivar_destinatario(destinatario_id):
    destinatario = DocumentoDistribucionDestinatario.query.filter_by(id=destinatario_id, empresa_id=current_user.empresa_id).first_or_404()
    try:
        DocumentDistributionService().deactivate_recipient(
            destinatario=destinatario,
            usuario_actor=current_user,
            motivo=request.form.get("motivo"),
        )
        flash("Destinatario desactivado.", "success")
    except DocumentDistributionError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion.detalle", item_id=destinatario.documento_id))


@bp.route("/publicaciones/<public_id>/reintentar", methods=["POST"])
@login_required
@require_permission(RETRY_DISTRIBUTION_PERMISSION)
def reintentar_entregas(public_id):
    publicacion = DocumentoPublicacion.query.filter_by(public_id=public_id, empresa_id=current_user.empresa_id).first_or_404()
    result = DocumentEmailService().process_pending(publicacion_id=publicacion.id, solo_fallidos=True)
    flash(f"Reintento procesado: {result['enviadas']} enviados, {result['fallidas']} fallidos.", "info")
    return redirect(url_for("documentacion.detalle", item_id=publicacion.documento_id))


@bp.route("/publicaciones/<public_id>/revocar", methods=["POST"])
@login_required
@require_permission(REVOKE_PERMISSION)
def revocar_publicacion(public_id):
    publicacion = DocumentoPublicacion.query.filter_by(public_id=public_id, empresa_id=current_user.empresa_id).first_or_404()
    try:
        DocumentPublicationService().revoke_publication(
            publicacion=publicacion,
            usuario=current_user,
            motivo=request.form.get("motivo"),
            **_request_metadata(),
        )
        flash("Publicacion revocada.", "success")
    except DocumentPublicationError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion.detalle", item_id=publicacion.documento_id))
