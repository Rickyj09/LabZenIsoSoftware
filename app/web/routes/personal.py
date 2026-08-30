import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models.organigrama import Cargo, ESTADOS_PERSONAL, Personal, TIPOS_CALIFICACION_PERSONAL
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
        "cargos": Cargo.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cargo.codigo.asc()).all(),
        "usuarios": personal_service.company_users(current_user),
        "estado_badge_class": _estado_badge_class,
    }
    context.update(extra)
    return context


def _estado_badge_class(estado):
    return {
        "ACTIVO": "text-bg-success",
        "INACTIVO": "text-bg-secondary",
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
