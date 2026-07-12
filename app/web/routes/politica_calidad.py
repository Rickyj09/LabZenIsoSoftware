from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.security.permissions import require_permission
from app.services.document_versioning_service import (
    DocumentVersioningError,
    create_draft_version,
    create_initial_version,
    get_current_version,
    get_preparation_version,
)
from app.services.document_workflow_service import record_document_event

bp = Blueprint("politica_calidad", __name__, url_prefix="/politica-calidad")


@bp.route("/")
@login_required
@require_permission("documentos.ver")
def index():
    documento = Documento.query.filter_by(
        empresa_id=current_user.empresa_id,
        codigo="POL-CAL-001",
        tipo_documento="POLITICA"
    ).first()

    versiones = []
    version_vigente = None

    if documento:
        versiones = (
            DocumentoVersion.query
            .filter_by(
                documento_id=documento.id,
                empresa_id=current_user.empresa_id,
            )
            .order_by(DocumentoVersion.fecha_version.desc(), DocumentoVersion.id.desc())
            .all()
        )

        version_vigente = get_current_version(documento)

    return render_template(
        "politica_calidad/index.html",
        documento=documento,
        versiones=versiones,
        version_vigente=version_vigente,
        version_preparacion=get_preparation_version(documento) if documento else None,
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
@require_permission("documentos.crear")
def nuevo():
    existente = Documento.query.filter_by(
        empresa_id=current_user.empresa_id,
        codigo="POL-CAL-001",
        tipo_documento="POLITICA"
    ).first()

    if existente:
        flash("La Política de Calidad ya existe. Crea una nueva versión.", "warning")
        return redirect(url_for("politica_calidad.index"))

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        version = request.form.get("version", "").strip()
        contenido = request.form.get("contenido", "").strip()
        cambios = request.form.get("cambios", "").strip()

        if not titulo or not version or not contenido:
            flash("Título, versión y contenido son obligatorios.", "danger")
            return render_template("politica_calidad/form.html", modo="nuevo", documento=None, version=None)

        documento = Documento(
            empresa_id=current_user.empresa_id,
            codigo="POL-CAL-001",
            titulo=titulo,
            tipo_documento="POLITICA",
            proceso="SGC",
            estado="EN_ELABORACION",
            version_actual=version,
            elaborado_por_id=current_user.id,
        )
        db.session.add(documento)
        db.session.flush()

        try:
            version_doc = create_initial_version(
                documento=documento,
                version=version,
                contenido=contenido,
                cambios=cambios,
                user_id=current_user.id,
            )
            db.session.flush()
            record_document_event(
                documento=documento,
                version_doc=version_doc,
                usuario=current_user,
                accion="CREAR_VERSION",
                estado_anterior=None,
                estado_nuevo="EN_ELABORACION",
                comentario=cambios,
                ip=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=request.headers.get("User-Agent"),
            )
            db.session.commit()
        except DocumentVersioningError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template("politica_calidad/form.html", modo="nuevo", documento=None, version=None)

        flash("Política de Calidad creada correctamente.", "success")
        return redirect(url_for("politica_calidad.index"))

    return render_template("politica_calidad/form.html", modo="nuevo", documento=None, version=None)


@bp.route("/nueva-version", methods=["GET", "POST"])
@login_required
@require_permission("documentos.editar")
def nueva_version():
    documento = Documento.query.filter_by(
        empresa_id=current_user.empresa_id,
        codigo="POL-CAL-001",
        tipo_documento="POLITICA"
    ).first()

    if not documento:
        flash("Primero debes crear la Política de Calidad.", "warning")
        return redirect(url_for("politica_calidad.nuevo"))

    if request.method == "POST":
        version = request.form.get("version", "").strip()
        contenido = request.form.get("contenido", "").strip()
        cambios = request.form.get("cambios", "").strip()

        if not version or not contenido:
            flash("Versión y contenido son obligatorios.", "danger")
            return render_template("politica_calidad/form.html", modo="version", documento=documento, version=None)

        try:
            version_doc = create_draft_version(
                documento=documento,
                version=version,
                contenido=contenido,
                cambios=cambios,
                user_id=current_user.id,
            )
            db.session.flush()
            record_document_event(
                documento=documento,
                version_doc=version_doc,
                usuario=current_user,
                accion="CREAR_VERSION",
                estado_anterior=None,
                estado_nuevo="EN_ELABORACION",
                comentario=cambios,
                ip=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=request.headers.get("User-Agent"),
            )
            db.session.commit()
        except DocumentVersioningError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template("politica_calidad/form.html", modo="version", documento=documento, version=None)

        flash("Nueva versión registrada correctamente.", "success")
        return redirect(url_for("politica_calidad.index"))

    return render_template("politica_calidad/form.html", modo="version", documento=documento, version=None)
