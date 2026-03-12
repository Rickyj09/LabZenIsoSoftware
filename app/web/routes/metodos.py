from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.laboratorio import Metodo

bp = Blueprint("metodos", __name__, url_prefix="/metodos")


@bp.route("/")
@login_required
def index():
    items = (
        Metodo.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Metodo.nombre.asc())
        .all()
    )
    return render_template("metodos/index.html", items=items)


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        nombre = request.form.get("nombre", "").strip()
        version = request.form.get("version", "").strip() or None
        tipo = request.form.get("tipo", "").strip() or None
        norma_referencia = request.form.get("norma_referencia", "").strip() or None
        descripcion = request.form.get("descripcion", "").strip() or None
        fecha_vigencia = request.form.get("fecha_vigencia", "").strip() or None
        activo = True if request.form.get("activo") == "on" else False

        if not codigo:
            flash("El código es obligatorio.", "warning")
            return render_template("metodos/form.html", item=None)

        if not nombre:
            flash("El nombre es obligatorio.", "warning")
            return render_template("metodos/form.html", item=None)

        existe = Metodo.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo=codigo
        ).first()

        if existe:
            flash("Ya existe un método con ese código.", "danger")
            return render_template("metodos/form.html", item=None)

        item = Metodo(
            empresa_id=current_user.empresa_id,
            codigo=codigo,
            nombre=nombre,
            version=version,
            tipo=tipo,
            norma_referencia=norma_referencia,
            descripcion=descripcion,
            activo=activo,
            fecha_vigencia=fecha_vigencia
        )

        db.session.add(item)
        db.session.commit()

        flash("Método creado correctamente.", "success")
        return redirect(url_for("metodos.index"))

    return render_template("metodos/form.html", item=None)


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = Metodo.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        nombre = request.form.get("nombre", "").strip()
        version = request.form.get("version", "").strip() or None
        tipo = request.form.get("tipo", "").strip() or None
        norma_referencia = request.form.get("norma_referencia", "").strip() or None
        descripcion = request.form.get("descripcion", "").strip() or None
        fecha_vigencia = request.form.get("fecha_vigencia", "").strip() or None
        activo = True if request.form.get("activo") == "on" else False

        if not codigo:
            flash("El código es obligatorio.", "warning")
            return render_template("metodos/form.html", item=item)

        if not nombre:
            flash("El nombre es obligatorio.", "warning")
            return render_template("metodos/form.html", item=item)

        existe = (
            Metodo.query
            .filter(
                Metodo.empresa_id == current_user.empresa_id,
                Metodo.codigo == codigo,
                Metodo.id != item.id
            )
            .first()
        )

        if existe:
            flash("Ya existe otro método con ese código.", "danger")
            return render_template("metodos/form.html", item=item)

        item.codigo = codigo
        item.nombre = nombre
        item.version = version
        item.tipo = tipo
        item.norma_referencia = norma_referencia
        item.descripcion = descripcion
        item.fecha_vigencia = fecha_vigencia
        item.activo = activo

        db.session.commit()

        flash("Método actualizado correctamente.", "success")
        return redirect(url_for("metodos.index"))

    return render_template("metodos/form.html", item=item)


@bp.route("/<int:item_id>/desactivar", methods=["POST"])
@login_required
def desactivar(item_id):
    item = Metodo.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    item.activo = False
    db.session.commit()

    flash("Método desactivado correctamente.", "warning")
    return redirect(url_for("metodos.index"))


@bp.route("/<int:item_id>/activar", methods=["POST"])
@login_required
def activar(item_id):
    item = Metodo.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    item.activo = True
    db.session.commit()

    flash("Método activado correctamente.", "success")
    return redirect(url_for("metodos.index"))