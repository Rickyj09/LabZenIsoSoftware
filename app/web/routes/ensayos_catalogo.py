from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.laboratorio import EnsayoCatalogo

bp = Blueprint("ensayos_catalogo", __name__, url_prefix="/ensayos-catalogo")


@bp.route("/")
@login_required
def index():
    items = (
        EnsayoCatalogo.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(EnsayoCatalogo.nombre.asc())
        .all()
    )
    return render_template("ensayos_catalogo/index.html", items=items)


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        area = request.form.get("area", "").strip() or None
        activo = True if request.form.get("activo") == "on" else False

        if not codigo:
            flash("El código es obligatorio.", "warning")
            return render_template("ensayos_catalogo/form.html", item=None)

        if not nombre:
            flash("El nombre es obligatorio.", "warning")
            return render_template("ensayos_catalogo/form.html", item=None)

        existe = EnsayoCatalogo.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo=codigo
        ).first()

        if existe:
            flash("Ya existe un ensayo con ese código.", "danger")
            return render_template("ensayos_catalogo/form.html", item=None)

        item = EnsayoCatalogo(
            empresa_id=current_user.empresa_id,
            codigo=codigo,
            nombre=nombre,
            descripcion=descripcion,
            area=area,
            activo=activo
        )

        db.session.add(item)
        db.session.commit()

        flash("Ensayo creado correctamente.", "success")
        return redirect(url_for("ensayos_catalogo.index"))

    return render_template("ensayos_catalogo/form.html", item=None)


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = EnsayoCatalogo.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        area = request.form.get("area", "").strip() or None
        activo = True if request.form.get("activo") == "on" else False

        if not codigo:
            flash("El código es obligatorio.", "warning")
            return render_template("ensayos_catalogo/form.html", item=item)

        if not nombre:
            flash("El nombre es obligatorio.", "warning")
            return render_template("ensayos_catalogo/form.html", item=item)

        existe = (
            EnsayoCatalogo.query
            .filter(
                EnsayoCatalogo.empresa_id == current_user.empresa_id,
                EnsayoCatalogo.codigo == codigo,
                EnsayoCatalogo.id != item.id
            )
            .first()
        )

        if existe:
            flash("Ya existe otro ensayo con ese código.", "danger")
            return render_template("ensayos_catalogo/form.html", item=item)

        item.codigo = codigo
        item.nombre = nombre
        item.descripcion = descripcion
        item.area = area
        item.activo = activo

        db.session.commit()

        flash("Ensayo actualizado correctamente.", "success")
        return redirect(url_for("ensayos_catalogo.index"))

    return render_template("ensayos_catalogo/form.html", item=item)


@bp.route("/<int:item_id>/desactivar", methods=["POST"])
@login_required
def desactivar(item_id):
    item = EnsayoCatalogo.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    item.activo = False
    db.session.commit()

    flash("Ensayo desactivado correctamente.", "warning")
    return redirect(url_for("ensayos_catalogo.index"))


@bp.route("/<int:item_id>/activar", methods=["POST"])
@login_required
def activar(item_id):
    item = EnsayoCatalogo.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    item.activo = True
    db.session.commit()

    flash("Ensayo activado correctamente.", "success")
    return redirect(url_for("ensayos_catalogo.index"))