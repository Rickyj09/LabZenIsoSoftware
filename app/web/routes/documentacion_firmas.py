from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.security.permissions import require_permission
from app.services.document_signature_identity_service import (
    DocumentSignatureIdentityError,
    DocumentSignatureIdentityService,
    SIGNATURE_IDENTITY_PERMISSION,
)


bp = Blueprint("documentacion_firmas", __name__, url_prefix="/documentacion/firmas")


def _request_metadata():
    return {
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
    }


@bp.route("/identidades")
@login_required
@require_permission(SIGNATURE_IDENTITY_PERMISSION)
def identidades():
    service = DocumentSignatureIdentityService()
    return render_template(
        "documentacion/identidades_firma.html",
        user_identity_rows=service.list_company_users_with_identities(actor=current_user),
        signature_identity_permission=SIGNATURE_IDENTITY_PERMISSION,
    )


@bp.route("/identidades", methods=["POST"])
@login_required
@require_permission(SIGNATURE_IDENTITY_PERMISSION)
def crear_identidad():
    service = DocumentSignatureIdentityService()
    try:
        service.create_identity(
            actor=current_user,
            user_id=request.form.get("user_id", type=int),
            identificacion=request.form.get("identificacion"),
            nombre_certificado=request.form.get("nombre_certificado"),
            emisor_certificado=request.form.get("emisor_certificado"),
            certificado_fingerprint_sha256=request.form.get("certificado_fingerprint_sha256"),
            **_request_metadata(),
        )
        flash("Identidad registrada correctamente.", "success")
    except DocumentSignatureIdentityError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion_firmas.identidades"))


@bp.route("/identidades/<int:identity_id>/actualizar", methods=["POST"])
@login_required
@require_permission(SIGNATURE_IDENTITY_PERMISSION)
def actualizar_identidad(identity_id):
    service = DocumentSignatureIdentityService()
    try:
        service.update_identity(
            actor=current_user,
            identity_id=identity_id,
            identificacion=request.form.get("identificacion"),
            nombre_certificado=request.form.get("nombre_certificado"),
            emisor_certificado=request.form.get("emisor_certificado"),
            certificado_fingerprint_sha256=request.form.get("certificado_fingerprint_sha256"),
            **_request_metadata(),
        )
        flash("Identidad actualizada correctamente.", "success")
    except DocumentSignatureIdentityError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion_firmas.identidades"))


@bp.route("/identidades/<int:identity_id>/verificar", methods=["POST"])
@login_required
@require_permission(SIGNATURE_IDENTITY_PERMISSION)
def verificar_identidad(identity_id):
    service = DocumentSignatureIdentityService()
    try:
        service.verify_identity_mock(actor=current_user, identity_id=identity_id, **_request_metadata())
        flash("Identidad verificada localmente. Esta accion no equivale a certificacion criptografica real.", "success")
    except DocumentSignatureIdentityError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion_firmas.identidades"))


@bp.route("/identidades/<int:identity_id>/revocar", methods=["POST"])
@login_required
@require_permission(SIGNATURE_IDENTITY_PERMISSION)
def revocar_identidad(identity_id):
    service = DocumentSignatureIdentityService()
    try:
        service.revoke_identity(actor=current_user, identity_id=identity_id, **_request_metadata())
        flash("Identidad revocada correctamente.", "success")
    except DocumentSignatureIdentityError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion_firmas.identidades"))
