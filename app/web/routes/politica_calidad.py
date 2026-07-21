from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.seguridad import Usuario
from app.security.permissions import require_permission
from app.services.document_versioning_service import (
    DocumentVersioningError,
    create_draft_version,
    create_initial_version,
    get_current_version,
    get_preparation_version,
    validate_document_responsibles,
)
from app.services.document_workflow_service import record_document_event

bp = Blueprint("politica_calidad", __name__, url_prefix="/politica-calidad")


def _responsables_documentales():
    return (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(Usuario.nombre.asc(), Usuario.apellido.asc(), Usuario.id.asc())
        .all()
    )


def _form_context(*, modo, documento=None, version=None, form_data=None):
    return {
        "modo": modo,
        "documento": documento,
        "version": version,
        "responsables_documentales": _responsables_documentales(),
        "form_data": form_data or {},
    }


def _request_metadata():
    return {
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
    }


@bp.route("/")
@login_required
@require_permission("documentos.ver")
def index():
    documento = Documento.query.filter_by(
        empresa_id=current_user.empresa_id,
        codigo="POL-CAL-001",
        tipo_documento="POLITICA",
    ).first()

    versiones = []
    version_vigente = None

    if documento:
        versiones = (
            DocumentoVersion.query
            .filter_by(documento_id=documento.id, empresa_id=current_user.empresa_id)
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
        tipo_documento="POLITICA",
    ).first()

    if existente:
        flash("La Politica de Calidad ya existe. Crea una nueva version.", "warning")
        return redirect(url_for("politica_calidad.index"))

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        version = request.form.get("version", "").strip()
        contenido = request.form.get("contenido", "").strip()
        cambios = request.form.get("cambios", "").strip()
        form_data = request.form

        if not titulo or not version or not contenido:
            flash("Titulo, version y contenido son obligatorios.", "danger")
            return render_template("politica_calidad/form.html", **_form_context(modo="nuevo", form_data=form_data))

        try:
            responsables = validate_document_responsibles(
                empresa_id=current_user.empresa_id,
                elaborado_por_id=request.form.get("elaborado_por_id"),
                revisado_por_id=request.form.get("revisado_por_id"),
                aprobado_por_id=request.form.get("aprobado_por_id"),
            )
            documento = Documento(
                empresa_id=current_user.empresa_id,
                codigo="POL-CAL-001",
                titulo=titulo,
                tipo_documento="POLITICA",
                proceso="SGC",
                estado="EN_ELABORACION",
                version_actual=version,
                elaborado_por_id=responsables["elaborado_por_id"],
            )
            db.session.add(documento)
            db.session.flush()

            version_doc = create_initial_version(
                documento=documento,
                version=version,
                contenido=contenido,
                cambios=cambios,
                user_id=current_user.id,
                elaborado_por_id=responsables["elaborado_por_id"],
                revisado_por_id=responsables["revisado_por_id"],
                aprobado_por_id=responsables["aprobado_por_id"],
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
                **_request_metadata(),
            )
            db.session.commit()
        except DocumentVersioningError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template("politica_calidad/form.html", **_form_context(modo="nuevo", form_data=form_data))

        flash("Politica de Calidad creada correctamente.", "success")
        return redirect(url_for("politica_calidad.index"))

    return render_template("politica_calidad/form.html", **_form_context(modo="nuevo"))


@bp.route("/nueva-version", methods=["GET", "POST"])
@login_required
@require_permission("documentos.editar")
def nueva_version():
    documento = Documento.query.filter_by(
        empresa_id=current_user.empresa_id,
        codigo="POL-CAL-001",
        tipo_documento="POLITICA",
    ).first()

    if not documento:
        flash("Primero debes crear la Politica de Calidad.", "warning")
        return redirect(url_for("politica_calidad.nuevo"))

    if request.method == "POST":
        version = request.form.get("version", "").strip()
        contenido = request.form.get("contenido", "").strip()
        cambios = request.form.get("cambios", "").strip()
        form_data = request.form

        if not version or not contenido:
            flash("Version y contenido son obligatorios.", "danger")
            return render_template(
                "politica_calidad/form.html",
                **_form_context(modo="version", documento=documento, form_data=form_data),
            )

        try:
            responsables = validate_document_responsibles(
                empresa_id=current_user.empresa_id,
                elaborado_por_id=request.form.get("elaborado_por_id"),
                revisado_por_id=request.form.get("revisado_por_id"),
                aprobado_por_id=request.form.get("aprobado_por_id"),
            )
            version_doc = create_draft_version(
                documento=documento,
                version=version,
                contenido=contenido,
                cambios=cambios,
                user_id=current_user.id,
                elaborado_por_id=responsables["elaborado_por_id"],
                revisado_por_id=responsables["revisado_por_id"],
                aprobado_por_id=responsables["aprobado_por_id"],
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
                **_request_metadata(),
            )
            db.session.commit()
        except DocumentVersioningError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "politica_calidad/form.html",
                **_form_context(modo="version", documento=documento, form_data=form_data),
            )

        flash("Nueva version registrada correctamente.", "success")
        return redirect(url_for("politica_calidad.index"))

    return render_template("politica_calidad/form.html", **_form_context(modo="version", documento=documento))
