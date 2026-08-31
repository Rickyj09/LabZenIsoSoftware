import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models.equipos import Equipo
from app.models.organigrama import (
    Cargo,
    ESTADOS_AUTORIZACION_TECNICA,
    ESTADOS_CAPACITACION_PERSONAL,
    ESTADOS_PARTICIPACION_CAPACITACION,
    ESTADOS_PERSONAL,
    METODOS_EVALUACION_COMPETENCIA,
    MODALIDADES_CAPACITACION_PERSONAL,
    Personal,
    PersonalAutorizacionTecnica,
    PersonalCapacitacion,
    PersonalCapacitacionParticipante,
    PersonalEvaluacionCompetencia,
    RESULTADOS_EVALUACION_COMPETENCIA,
    TIPOS_AUTORIZACION_TECNICA,
    TIPOS_CALIFICACION_PERSONAL,
    TIPOS_CAPACITACION_PERSONAL,
    TIPOS_COMPETENCIA_PERSONAL,
    TIPOS_EVIDENCIA_CAPACITACION,
    TIPOS_EVIDENCIA_AUTORIZACION_TECNICA,
    TIPOS_EVIDENCIA_EVALUACION_COMPETENCIA,
)
from app.security.permissions import require_permission
from app.services import personal_service
from app.services.personal_service import PersonalError
from app.services.storage_service import DocumentStorageError, resolve_document_path


bp = Blueprint("personal", __name__, url_prefix="/personal")

CSRF_SESSION_KEY = "personal_csrf"


def _csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _validate_csrf():
    expected = session.get(CSRF_SESSION_KEY)
    provided = request.form.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, provided):
        abort(403)


def _personal_context(**extra):
    context = {
        "csrf_token": _csrf_token(),
        "estados_personal": ESTADOS_PERSONAL,
        "tipos_calificacion": TIPOS_CALIFICACION_PERSONAL,
        "tipos_capacitacion": TIPOS_CAPACITACION_PERSONAL,
        "modalidades_capacitacion": MODALIDADES_CAPACITACION_PERSONAL,
        "estados_capacitacion": ESTADOS_CAPACITACION_PERSONAL,
        "estados_participacion": ESTADOS_PARTICIPACION_CAPACITACION,
        "tipos_evidencia_capacitacion": TIPOS_EVIDENCIA_CAPACITACION,
        "tipos_competencia": TIPOS_COMPETENCIA_PERSONAL,
        "metodos_evaluacion": METODOS_EVALUACION_COMPETENCIA,
        "resultados_evaluacion": RESULTADOS_EVALUACION_COMPETENCIA,
        "tipos_evidencia_evaluacion": TIPOS_EVIDENCIA_EVALUACION_COMPETENCIA,
        "tipos_autorizacion": TIPOS_AUTORIZACION_TECNICA,
        "estados_autorizacion": ESTADOS_AUTORIZACION_TECNICA,
        "estados_autorizacion_efectivos": ("VIGENTE", "SUSPENDIDA", "REVOCADA", "VENCIDA"),
        "tipos_evidencia_autorizacion": TIPOS_EVIDENCIA_AUTORIZACION_TECNICA,
        "cargos": Cargo.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cargo.codigo.asc()).all(),
        "usuarios": personal_service.company_users(current_user),
        "estado_badge_class": _estado_badge_class,
        "autorizacion_badge_class": _autorizacion_badge_class,
    }
    context.update(extra)
    return context


def _estado_badge_class(estado):
    return {
        "ACTIVO": "text-bg-success",
        "INACTIVO": "text-bg-secondary",
    }.get(estado, "text-bg-light")


def _autorizacion_badge_class(estado):
    return {
        "VIGENTE": "text-bg-success",
        "SUSPENDIDA": "text-bg-warning",
        "REVOCADA": "text-bg-danger",
        "VENCIDA": "text-bg-secondary",
    }.get(estado, "text-bg-light")


@bp.route("/")
@login_required
@require_permission(personal_service.PERM_VER)
def index():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "cargo_id", "estado")}
    query = Personal.query.filter_by(empresa_id=current_user.empresa_id)
    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.filter(or_(
            Personal.codigo.ilike(like),
            Personal.nombres.ilike(like),
            Personal.apellidos.ilike(like),
            Personal.email.ilike(like),
        ))
    if filters["cargo_id"]:
        query = query.filter(Personal.cargo_id == int(filters["cargo_id"]))
    if filters["estado"]:
        query = query.filter(Personal.estado == filters["estado"])
    items = query.order_by(Personal.apellidos.asc(), Personal.nombres.asc()).all()
    return render_template("personal/index.html", **_personal_context(items=items, filters=filters))


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def nuevo():
    if request.method == "POST":
        _validate_csrf()
        try:
            item = personal_service.create_personal(current_user, request.form)
            db.session.commit()
            flash("Personal creado correctamente.", "success")
            return redirect(url_for("personal.detalle", item_id=item.id))
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/form.html", **_personal_context(item=None, form_data=request.form))
    return render_template("personal/form.html", **_personal_context(item=None, form_data={}))


@bp.route("/<int:item_id>")
@login_required
@require_permission(personal_service.PERM_VER)
def detalle(item_id):
    item = personal_service.get_personal(current_user, item_id)
    if not item:
        abort(404)
    return render_template("personal/detalle.html", **_personal_context(item=item))


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def editar(item_id):
    item = personal_service.get_personal(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.update_personal(current_user, item, request.form)
            db.session.commit()
            flash("Personal actualizado correctamente.", "success")
            return redirect(url_for("personal.detalle", item_id=item.id))
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/form.html", **_personal_context(item=item, form_data=request.form))
    return render_template("personal/form.html", **_personal_context(item=item, form_data={}))


@bp.route("/<int:item_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado(item_id):
    _validate_csrf()
    item = personal_service.get_personal(current_user, item_id)
    if not item:
        abort(404)
    nuevo_estado = "INACTIVO" if item.estado == "ACTIVO" else "ACTIVO"
    personal_service.set_personal_status(current_user, item, nuevo_estado)
    db.session.commit()
    flash("Estado del personal actualizado correctamente.", "success")
    return redirect(url_for("personal.detalle", item_id=item.id))


def _redirect_personal_detail(personal_id):
    return redirect(url_for("personal.detalle", item_id=personal_id))


def _redirect_capacitacion_detail(capacitacion_id):
    return redirect(url_for("personal.detalle_capacitacion", capacitacion_id=capacitacion_id))


def _redirect_evaluacion_detail(evaluacion_id):
    return redirect(url_for("personal.detalle_evaluacion_competencia", evaluacion_id=evaluacion_id))


def _personal_activo():
    return (
        Personal.query
        .filter_by(empresa_id=current_user.empresa_id, estado="ACTIVO")
        .order_by(Personal.apellidos.asc(), Personal.nombres.asc())
        .all()
    )


def _capacitaciones_empresa():
    return (
        PersonalCapacitacion.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(PersonalCapacitacion.fecha_inicio.desc(), PersonalCapacitacion.nombre.asc())
        .all()
    )


def _participaciones_empresa():
    return (
        PersonalCapacitacionParticipante.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(PersonalCapacitacionParticipante.fecha_registro.desc())
        .all()
    )


def _equipos_empresa():
    return (
        Equipo.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Equipo.codigo.asc(), Equipo.nombre.asc())
        .all()
    )


def _evaluaciones_compatibles(personal_id=None):
    query = PersonalEvaluacionCompetencia.query.filter(
        PersonalEvaluacionCompetencia.empresa_id == current_user.empresa_id,
        PersonalEvaluacionCompetencia.resultado.in_(("COMPETENTE", "COMPETENTE_CON_OBSERVACIONES")),
    )
    if personal_id:
        query = query.filter(PersonalEvaluacionCompetencia.personal_id == personal_id)
    return query.order_by(
        PersonalEvaluacionCompetencia.fecha_evaluacion.desc(),
        PersonalEvaluacionCompetencia.id.desc(),
    ).all()


@bp.route("/capacitaciones")
@login_required
@require_permission(personal_service.PERM_VER)
def capacitaciones():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "estado", "tipo")}
    items = personal_service.capacitaciones_query(current_user, filters).all()
    return render_template("personal/capacitaciones_index.html", **_personal_context(items=items, filters=filters))


@bp.route("/capacitaciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def nueva_capacitacion():
    if request.method == "POST":
        _validate_csrf()
        try:
            item = personal_service.create_capacitacion(current_user, request.form)
            db.session.commit()
            flash("Capacitacion registrada correctamente.", "success")
            return _redirect_capacitacion_detail(item.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/capacitacion_form.html", **_personal_context(item=None, form_data=request.form))
    return render_template("personal/capacitacion_form.html", **_personal_context(item=None, form_data={}))


@bp.route("/capacitaciones/<int:capacitacion_id>")
@login_required
@require_permission(personal_service.PERM_VER)
def detalle_capacitacion(capacitacion_id):
    item = personal_service.get_capacitacion(current_user, capacitacion_id)
    if not item:
        abort(404)
    personal_disponible = (
        Personal.query
        .filter_by(empresa_id=current_user.empresa_id, estado="ACTIVO")
        .order_by(Personal.apellidos.asc(), Personal.nombres.asc())
        .all()
    )
    return render_template(
        "personal/capacitacion_detalle.html",
        **_personal_context(item=item, personal_disponible=personal_disponible),
    )


@bp.route("/capacitaciones/<int:capacitacion_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def editar_capacitacion(capacitacion_id):
    item = personal_service.get_capacitacion(current_user, capacitacion_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.update_capacitacion(current_user, item, request.form)
            db.session.commit()
            flash("Capacitacion actualizada correctamente.", "success")
            return _redirect_capacitacion_detail(item.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/capacitacion_form.html", **_personal_context(item=item, form_data=request.form))
    return render_template("personal/capacitacion_form.html", **_personal_context(item=item, form_data={}))


@bp.route("/capacitaciones/<int:capacitacion_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_capacitacion(capacitacion_id):
    _validate_csrf()
    item = personal_service.get_capacitacion(current_user, capacitacion_id)
    if not item:
        abort(404)
    try:
        personal_service.set_capacitacion_estado(current_user, item, request.form.get("estado"))
        db.session.commit()
        flash("Estado de la capacitacion actualizado correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_capacitacion_detail(item.id)


@bp.route("/capacitaciones/<int:capacitacion_id>/participantes", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def agregar_participante_capacitacion(capacitacion_id):
    _validate_csrf()
    item = personal_service.get_capacitacion(current_user, capacitacion_id)
    if not item:
        abort(404)
    try:
        personal_service.add_capacitacion_participante(current_user, item, request.form.get("personal_id"), request.form)
        db.session.commit()
        flash("Participante agregado correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_capacitacion_detail(item.id)


@bp.route("/capacitaciones/participantes/<int:participante_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_participante_capacitacion(participante_id):
    _validate_csrf()
    participante = personal_service.get_capacitacion_participante(current_user, participante_id)
    if not participante:
        abort(404)
    try:
        personal_service.update_capacitacion_participante(current_user, participante, request.form)
        db.session.commit()
        flash("Participacion actualizada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_capacitacion_detail(participante.capacitacion_id)


@bp.route("/capacitaciones/participantes/<int:participante_id>/estado-registro", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_activo_participante_capacitacion(participante_id):
    _validate_csrf()
    participante = personal_service.get_capacitacion_participante(current_user, participante_id)
    if not participante:
        abort(404)
    personal_service.set_capacitacion_participante_active(current_user, participante, not participante.activo)
    db.session.commit()
    flash("Estado del participante actualizado correctamente.", "success")
    return _redirect_capacitacion_detail(participante.capacitacion_id)


@bp.route("/capacitaciones/<int:capacitacion_id>/evidencias", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def agregar_evidencia_capacitacion(capacitacion_id):
    _validate_csrf()
    item = personal_service.get_capacitacion(current_user, capacitacion_id)
    if not item:
        abort(404)
    try:
        personal_service.add_capacitacion_evidencia(current_user, item, request.files.get("evidencia"), request.form)
        db.session.commit()
        flash("Evidencia de capacitacion cargada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_capacitacion_detail(item.id)


@bp.route("/capacitaciones/evidencias/<int:evidencia_id>/descargar")
@login_required
@require_permission(personal_service.PERM_VER)
def descargar_evidencia_capacitacion(evidencia_id):
    evidencia = personal_service.get_capacitacion_evidencia(current_user, evidencia_id)
    if not evidencia or not evidencia.activo:
        abort(404)
    if evidencia.capacitacion.empresa_id != current_user.empresa_id:
        abort(404)
    if evidencia.participante and (
        evidencia.participante.empresa_id != current_user.empresa_id
        or evidencia.participante.capacitacion_id != evidencia.capacitacion_id
    ):
        abort(404)
    try:
        path = resolve_document_path(evidencia.archivo_storage_path)
    except DocumentStorageError:
        abort(404)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=evidencia.archivo_nombre_original,
        mimetype=evidencia.archivo_mime,
    )


@bp.route("/capacitaciones/evidencias/<int:evidencia_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_evidencia_capacitacion(evidencia_id):
    _validate_csrf()
    evidencia = personal_service.get_capacitacion_evidencia(current_user, evidencia_id)
    if not evidencia:
        abort(404)
    personal_service.set_capacitacion_evidencia_active(current_user, evidencia, not evidencia.activo)
    db.session.commit()
    flash("Estado de la evidencia actualizado correctamente.", "success")
    return _redirect_capacitacion_detail(evidencia.capacitacion_id)


@bp.route("/evaluaciones")
@login_required
@require_permission(personal_service.PERM_VER)
def evaluaciones_competencia():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "persona_id", "resultado", "tipo", "desde", "hasta")}
    items = personal_service.evaluaciones_competencia_query(current_user, filters).all()
    return render_template(
        "personal/evaluaciones_index.html",
        **_personal_context(items=items, filters=filters, personal_disponible=_personal_activo()),
    )


@bp.route("/<int:item_id>/evaluaciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def nueva_evaluacion_competencia(item_id):
    item = personal_service.get_personal(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_csrf()
        try:
            evaluacion = personal_service.create_evaluacion_competencia(current_user, item.id, request.form)
            db.session.commit()
            flash("Evaluacion de competencia registrada correctamente.", "success")
            return _redirect_evaluacion_detail(evaluacion.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "personal/evaluacion_form.html",
                **_personal_context(
                    item=item,
                    evaluacion=None,
                    form_data=request.form,
                    personal_disponible=_personal_activo(),
                    capacitaciones=_capacitaciones_empresa(),
                    participaciones=_participaciones_empresa(),
                ),
            )
    return render_template(
        "personal/evaluacion_form.html",
        **_personal_context(
            item=item,
            evaluacion=None,
            form_data={},
            personal_disponible=_personal_activo(),
            capacitaciones=_capacitaciones_empresa(),
            participaciones=_participaciones_empresa(),
        ),
    )


@bp.route("/evaluaciones/<int:evaluacion_id>")
@login_required
@require_permission(personal_service.PERM_VER)
def detalle_evaluacion_competencia(evaluacion_id):
    evaluacion = personal_service.get_evaluacion_competencia(current_user, evaluacion_id)
    if not evaluacion:
        abort(404)
    return render_template("personal/evaluacion_detalle.html", **_personal_context(evaluacion=evaluacion))


@bp.route("/evaluaciones/<int:evaluacion_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def editar_evaluacion_competencia(evaluacion_id):
    evaluacion = personal_service.get_evaluacion_competencia(current_user, evaluacion_id)
    if not evaluacion:
        abort(404)
    item = evaluacion.personal
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.update_evaluacion_competencia(current_user, evaluacion, request.form)
            db.session.commit()
            flash("Evaluacion de competencia actualizada correctamente.", "success")
            return _redirect_evaluacion_detail(evaluacion.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "personal/evaluacion_form.html",
                **_personal_context(
                    item=item,
                    evaluacion=evaluacion,
                    form_data=request.form,
                    personal_disponible=_personal_activo(),
                    capacitaciones=_capacitaciones_empresa(),
                    participaciones=_participaciones_empresa(),
                ),
            )
    return render_template(
        "personal/evaluacion_form.html",
        **_personal_context(
            item=item,
            evaluacion=evaluacion,
            form_data={},
            personal_disponible=_personal_activo(),
            capacitaciones=_capacitaciones_empresa(),
            participaciones=_participaciones_empresa(),
        ),
    )


@bp.route("/evaluaciones/<int:evaluacion_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_evaluacion_competencia(evaluacion_id):
    _validate_csrf()
    evaluacion = personal_service.get_evaluacion_competencia(current_user, evaluacion_id)
    if not evaluacion:
        abort(404)
    personal_service.set_evaluacion_competencia_active(current_user, evaluacion, not evaluacion.activo)
    db.session.commit()
    flash("Estado de la evaluacion actualizado correctamente.", "success")
    return _redirect_evaluacion_detail(evaluacion.id)


@bp.route("/evaluaciones/<int:evaluacion_id>/evidencias", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def agregar_evidencia_evaluacion_competencia(evaluacion_id):
    _validate_csrf()
    evaluacion = personal_service.get_evaluacion_competencia(current_user, evaluacion_id)
    if not evaluacion:
        abort(404)
    try:
        personal_service.add_evaluacion_competencia_evidencia(
            current_user,
            evaluacion,
            request.files.get("evidencia"),
            request.form,
        )
        db.session.commit()
        flash("Evidencia de evaluacion cargada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_evaluacion_detail(evaluacion.id)


@bp.route("/evaluaciones/evidencias/<int:evidencia_id>/descargar")
@login_required
@require_permission(personal_service.PERM_VER)
def descargar_evidencia_evaluacion_competencia(evidencia_id):
    evidencia = personal_service.get_evaluacion_competencia_evidencia(current_user, evidencia_id)
    if not evidencia or not evidencia.activo:
        abort(404)
    if evidencia.evaluacion.empresa_id != current_user.empresa_id:
        abort(404)
    try:
        path = resolve_document_path(evidencia.archivo_storage_path)
    except DocumentStorageError:
        abort(404)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=evidencia.archivo_nombre_original,
        mimetype=evidencia.archivo_mime,
    )


@bp.route("/evaluaciones/evidencias/<int:evidencia_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_evidencia_evaluacion_competencia(evidencia_id):
    _validate_csrf()
    evidencia = personal_service.get_evaluacion_competencia_evidencia(current_user, evidencia_id)
    if not evidencia:
        abort(404)
    personal_service.set_evaluacion_competencia_evidencia_active(current_user, evidencia, not evidencia.activo)
    db.session.commit()
    flash("Estado de la evidencia actualizado correctamente.", "success")
    return _redirect_evaluacion_detail(evidencia.evaluacion_id)


def _redirect_autorizacion_detail(autorizacion_id):
    return redirect(url_for("personal.detalle_autorizacion_tecnica", autorizacion_id=autorizacion_id))


def _authorization_form_context(item, autorizacion=None, form_data=None):
    return _personal_context(
        item=item,
        autorizacion=autorizacion,
        form_data=form_data or {},
        personal_disponible=_personal_activo(),
        equipos=_equipos_empresa(),
        evaluaciones=_evaluaciones_compatibles(item.id if item else None),
    )


@bp.route("/autorizaciones")
@login_required
@require_permission(personal_service.PERM_VER)
def autorizaciones_tecnicas():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "persona_id", "tipo", "estado", "equipo_id")}
    items = personal_service.autorizaciones_tecnicas_query(current_user, filters).all()
    return render_template(
        "personal/autorizaciones_index.html",
        **_personal_context(
            items=items,
            filters=filters,
            personal_disponible=_personal_activo(),
            equipos=_equipos_empresa(),
        ),
    )


@bp.route("/<int:item_id>/autorizaciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def nueva_autorizacion_tecnica(item_id):
    item = personal_service.get_personal(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_csrf()
        try:
            autorizacion = personal_service.create_autorizacion_tecnica(current_user, item.id, request.form)
            db.session.commit()
            flash("Autorizacion tecnica registrada correctamente.", "success")
            return _redirect_autorizacion_detail(autorizacion.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/autorizacion_form.html", **_authorization_form_context(item, form_data=request.form))

    form_data = {}
    evaluacion_id = request.args.get("evaluacion_competencia_id", "").strip()
    if evaluacion_id:
        evaluacion = personal_service.get_evaluacion_competencia(current_user, evaluacion_id)
        if not evaluacion or evaluacion.personal_id != item.id:
            abort(404)
        form_data = {
            "evaluacion_competencia_id": str(evaluacion.id),
            "actividad": evaluacion.actividad,
            "fundamento": f"Evaluacion de competencia {evaluacion.codigo or evaluacion.id}: {evaluacion.resultado}",
        }
    return render_template("personal/autorizacion_form.html", **_authorization_form_context(item, form_data=form_data))


@bp.route("/autorizaciones/<int:autorizacion_id>")
@login_required
@require_permission(personal_service.PERM_VER)
def detalle_autorizacion_tecnica(autorizacion_id):
    autorizacion = personal_service.get_autorizacion_tecnica(current_user, autorizacion_id)
    if not autorizacion:
        abort(404)
    return render_template("personal/autorizacion_detalle.html", **_personal_context(autorizacion=autorizacion))


@bp.route("/autorizaciones/<int:autorizacion_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def editar_autorizacion_tecnica(autorizacion_id):
    autorizacion = personal_service.get_autorizacion_tecnica(current_user, autorizacion_id)
    if not autorizacion:
        abort(404)
    if autorizacion.estado == "REVOCADA":
        flash("Una autorizacion revocada solo puede consultarse.", "warning")
        return _redirect_autorizacion_detail(autorizacion.id)
    item = autorizacion.personal
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.update_autorizacion_tecnica(current_user, autorizacion, request.form)
            db.session.commit()
            flash("Autorizacion tecnica actualizada correctamente.", "success")
            return _redirect_autorizacion_detail(autorizacion.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "personal/autorizacion_form.html",
                **_authorization_form_context(item, autorizacion=autorizacion, form_data=request.form),
            )
    return render_template(
        "personal/autorizacion_form.html",
        **_authorization_form_context(item, autorizacion=autorizacion, form_data={}),
    )


@bp.route("/autorizaciones/<int:autorizacion_id>/suspender", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def suspender_autorizacion_tecnica(autorizacion_id):
    _validate_csrf()
    autorizacion = personal_service.get_autorizacion_tecnica(current_user, autorizacion_id)
    if not autorizacion:
        abort(404)
    try:
        personal_service.suspender_autorizacion_tecnica(
            current_user,
            autorizacion,
            request.form.get("motivo_estado"),
            request.form.get("fecha_estado"),
        )
        db.session.commit()
        flash("Autorizacion suspendida correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_autorizacion_detail(autorizacion.id)


@bp.route("/autorizaciones/<int:autorizacion_id>/reactivar", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def reactivar_autorizacion_tecnica(autorizacion_id):
    _validate_csrf()
    autorizacion = personal_service.get_autorizacion_tecnica(current_user, autorizacion_id)
    if not autorizacion:
        abort(404)
    try:
        personal_service.reactivar_autorizacion_tecnica(
            current_user,
            autorizacion,
            request.form.get("motivo_estado"),
            request.form.get("fecha_estado"),
        )
        db.session.commit()
        flash("Autorizacion reactivada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_autorizacion_detail(autorizacion.id)


@bp.route("/autorizaciones/<int:autorizacion_id>/revocar", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def revocar_autorizacion_tecnica(autorizacion_id):
    _validate_csrf()
    autorizacion = personal_service.get_autorizacion_tecnica(current_user, autorizacion_id)
    if not autorizacion:
        abort(404)
    try:
        personal_service.revocar_autorizacion_tecnica(
            current_user,
            autorizacion,
            request.form.get("motivo_estado"),
            request.form.get("fecha_estado"),
        )
        db.session.commit()
        flash("Autorizacion revocada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_autorizacion_detail(autorizacion.id)


@bp.route("/autorizaciones/<int:autorizacion_id>/evidencias", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def agregar_evidencia_autorizacion_tecnica(autorizacion_id):
    _validate_csrf()
    autorizacion = personal_service.get_autorizacion_tecnica(current_user, autorizacion_id)
    if not autorizacion:
        abort(404)
    try:
        personal_service.add_autorizacion_tecnica_evidencia(
            current_user,
            autorizacion,
            request.files.get("evidencia"),
            request.form,
        )
        db.session.commit()
        flash("Evidencia de autorizacion cargada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_autorizacion_detail(autorizacion.id)


@bp.route("/autorizaciones/evidencias/<int:evidencia_id>/descargar")
@login_required
@require_permission(personal_service.PERM_VER)
def descargar_evidencia_autorizacion_tecnica(evidencia_id):
    evidencia = personal_service.get_autorizacion_tecnica_evidencia(current_user, evidencia_id)
    if not evidencia or not evidencia.activo:
        abort(404)
    if evidencia.autorizacion.empresa_id != current_user.empresa_id:
        abort(404)
    try:
        path = resolve_document_path(evidencia.archivo_storage_path)
    except DocumentStorageError:
        abort(404)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=evidencia.archivo_nombre_original,
        mimetype=evidencia.archivo_mime,
    )


@bp.route("/autorizaciones/evidencias/<int:evidencia_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_evidencia_autorizacion_tecnica(evidencia_id):
    _validate_csrf()
    evidencia = personal_service.get_autorizacion_tecnica_evidencia(current_user, evidencia_id)
    if not evidencia:
        abort(404)
    personal_service.set_autorizacion_tecnica_evidencia_active(current_user, evidencia, not evidencia.activo)
    db.session.commit()
    flash("Estado de la evidencia actualizado correctamente.", "success")
    return _redirect_autorizacion_detail(evidencia.autorizacion_id)


@bp.route("/<int:item_id>/calificaciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def nueva_calificacion(item_id):
    item = personal_service.get_personal(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_csrf()
        try:
            calificacion = personal_service.create_calificacion(current_user, item.id, request.form)
            db.session.flush()
            file_storage = request.files.get("evidencia")
            if file_storage and file_storage.filename:
                personal_service.add_calificacion_evidencia(
                    current_user,
                    calificacion,
                    file_storage,
                    request.form.get("evidencia_observaciones"),
                )
            db.session.commit()
            flash("Calificacion registrada correctamente.", "success")
            return _redirect_personal_detail(item.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/calificacion_form.html", **_personal_context(item=item, calificacion=None, form_data=request.form))
    return render_template("personal/calificacion_form.html", **_personal_context(item=item, calificacion=None, form_data={}))


@bp.route("/calificaciones/<int:calificacion_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def editar_calificacion(calificacion_id):
    calificacion = personal_service.get_calificacion(current_user, calificacion_id)
    if not calificacion:
        abort(404)
    item = calificacion.personal
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.update_calificacion(current_user, calificacion, request.form)
            db.session.commit()
            flash("Calificacion actualizada correctamente.", "success")
            return _redirect_personal_detail(item.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/calificacion_form.html", **_personal_context(item=item, calificacion=calificacion, form_data=request.form))
    return render_template("personal/calificacion_form.html", **_personal_context(item=item, calificacion=calificacion, form_data={}))


@bp.route("/calificaciones/<int:calificacion_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_calificacion(calificacion_id):
    _validate_csrf()
    calificacion = personal_service.get_calificacion(current_user, calificacion_id)
    if not calificacion:
        abort(404)
    personal_service.set_calificacion_active(current_user, calificacion, not calificacion.activo)
    db.session.commit()
    flash("Estado de la calificacion actualizado correctamente.", "success")
    return _redirect_personal_detail(calificacion.personal_id)


@bp.route("/calificaciones/<int:calificacion_id>/evidencias", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def agregar_evidencia_calificacion(calificacion_id):
    _validate_csrf()
    calificacion = personal_service.get_calificacion(current_user, calificacion_id)
    if not calificacion:
        abort(404)
    try:
        personal_service.add_calificacion_evidencia(
            current_user,
            calificacion,
            request.files.get("evidencia"),
            request.form.get("observaciones"),
        )
        db.session.commit()
        flash("Evidencia cargada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_personal_detail(calificacion.personal_id)


@bp.route("/evidencias/<int:evidencia_id>/descargar")
@login_required
@require_permission(personal_service.PERM_VER)
def descargar_evidencia(evidencia_id):
    evidencia = personal_service.get_evidencia(current_user, evidencia_id)
    if not evidencia or not evidencia.activo:
        abort(404)
    if evidencia.personal.empresa_id != current_user.empresa_id or evidencia.calificacion.empresa_id != current_user.empresa_id:
        abort(404)
    try:
        path = resolve_document_path(evidencia.archivo_storage_path)
    except DocumentStorageError:
        abort(404)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=evidencia.archivo_nombre_original,
        mimetype=evidencia.archivo_mime,
    )


@bp.route("/evidencias/<int:evidencia_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_evidencia(evidencia_id):
    _validate_csrf()
    evidencia = personal_service.get_evidencia(current_user, evidencia_id)
    if not evidencia:
        abort(404)
    personal_service.set_evidencia_active(current_user, evidencia, not evidencia.activo)
    db.session.commit()
    flash("Estado de la evidencia actualizado correctamente.", "success")
    return _redirect_personal_detail(evidencia.personal_id)


@bp.route("/<int:item_id>/experiencias/nueva", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def nueva_experiencia(item_id):
    item = personal_service.get_personal(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.create_experiencia(current_user, item.id, request.form)
            db.session.commit()
            flash("Experiencia registrada correctamente.", "success")
            return _redirect_personal_detail(item.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/experiencia_form.html", item=item, experiencia=None, form_data=request.form, csrf_token=_csrf_token())
    return render_template("personal/experiencia_form.html", item=item, experiencia=None, form_data={}, csrf_token=_csrf_token())


@bp.route("/experiencias/<int:experiencia_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def editar_experiencia(experiencia_id):
    experiencia = personal_service.get_experiencia(current_user, experiencia_id)
    if not experiencia:
        abort(404)
    item = experiencia.personal
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.update_experiencia(current_user, experiencia, request.form)
            db.session.commit()
            flash("Experiencia actualizada correctamente.", "success")
            return _redirect_personal_detail(item.id)
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/experiencia_form.html", item=item, experiencia=experiencia, form_data=request.form, csrf_token=_csrf_token())
    return render_template("personal/experiencia_form.html", item=item, experiencia=experiencia, form_data={}, csrf_token=_csrf_token())


@bp.route("/experiencias/<int:experiencia_id>/cerrar", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cerrar_experiencia(experiencia_id):
    _validate_csrf()
    experiencia = personal_service.get_experiencia(current_user, experiencia_id)
    if not experiencia:
        abort(404)
    try:
        personal_service.cerrar_experiencia_actual(current_user, experiencia, request.form.get("fecha_fin"))
        db.session.commit()
        flash("Experiencia actual cerrada correctamente.", "success")
    except PersonalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_personal_detail(experiencia.personal_id)


@bp.route("/experiencias/<int:experiencia_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_experiencia(experiencia_id):
    _validate_csrf()
    experiencia = personal_service.get_experiencia(current_user, experiencia_id)
    if not experiencia:
        abort(404)
    personal_service.set_experiencia_active(current_user, experiencia, not experiencia.activo)
    db.session.commit()
    flash("Estado de la experiencia actualizado correctamente.", "success")
    return _redirect_personal_detail(experiencia.personal_id)


@bp.route("/cargos")
@login_required
@require_permission(personal_service.PERM_VER)
def cargos():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "activo")}
    query = Cargo.query.filter_by(empresa_id=current_user.empresa_id)
    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.filter(or_(Cargo.codigo.ilike(like), Cargo.nombre.ilike(like)))
    if filters["activo"] == "1":
        query = query.filter(Cargo.activo.is_(True))
    elif filters["activo"] == "0":
        query = query.filter(Cargo.activo.is_(False))
    items = query.order_by(Cargo.codigo.asc()).all()
    return render_template("personal/cargos_index.html", items=items, filters=filters, csrf_token=_csrf_token())


@bp.route("/cargos/nuevo", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def nuevo_cargo():
    if request.method == "POST":
        _validate_csrf()
        try:
            item = personal_service.create_cargo(current_user, request.form)
            db.session.flush()
            personal_service.upsert_perfil(current_user, item, request.form)
            db.session.commit()
            flash("Cargo creado correctamente.", "success")
            return redirect(url_for("personal.detalle_cargo", cargo_id=item.id))
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/cargo_form.html", item=None, form_data=request.form, csrf_token=_csrf_token())
    return render_template("personal/cargo_form.html", item=None, form_data={}, csrf_token=_csrf_token())


@bp.route("/cargos/<int:cargo_id>")
@login_required
@require_permission(personal_service.PERM_VER)
def detalle_cargo(cargo_id):
    item = personal_service.get_cargo(current_user, cargo_id)
    if not item:
        abort(404)
    return render_template("personal/cargo_detalle.html", item=item, csrf_token=_csrf_token())


@bp.route("/cargos/<int:cargo_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def editar_cargo(cargo_id):
    item = personal_service.get_cargo(current_user, cargo_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_csrf()
        try:
            personal_service.update_cargo(current_user, item, request.form)
            personal_service.upsert_perfil(current_user, item, request.form)
            db.session.commit()
            flash("Cargo y perfil actualizados correctamente.", "success")
            return redirect(url_for("personal.detalle_cargo", cargo_id=item.id))
        except PersonalError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("personal/cargo_form.html", item=item, form_data=request.form, csrf_token=_csrf_token())
    return render_template("personal/cargo_form.html", item=item, form_data={}, csrf_token=_csrf_token())


@bp.route("/cargos/<int:cargo_id>/estado", methods=["POST"])
@login_required
@require_permission(personal_service.PERM_GESTIONAR)
def cambiar_estado_cargo(cargo_id):
    _validate_csrf()
    item = personal_service.get_cargo(current_user, cargo_id)
    if not item:
        abort(404)
    personal_service.set_cargo_active(current_user, item, not item.activo)
    db.session.commit()
    flash("Estado del cargo actualizado correctamente.", "success")
    return redirect(url_for("personal.detalle_cargo", cargo_id=item.id))
