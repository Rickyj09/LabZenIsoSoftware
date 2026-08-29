import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models.organigrama import Cargo, ESTADOS_PERSONAL, Personal
from app.security.permissions import require_permission
from app.services import personal_service
from app.services.personal_service import PersonalError


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
