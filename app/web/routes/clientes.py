from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models.clientes import Cliente

bp = Blueprint("clientes", __name__, url_prefix="/clientes")


@bp.route("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "activos").strip()

    query = Cliente.query.filter_by(empresa_id=current_user.empresa_id)

    if estado == "activos":
        query = query.filter(Cliente.estado == "activo")
    elif estado == "inactivos":
        query = query.filter(Cliente.estado == "inactivo")

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Cliente.identificacion.ilike(like),
                Cliente.nombre_razon_social.ilike(like),
                Cliente.contacto_nombre.ilike(like),
                Cliente.contacto_email.ilike(like),
                Cliente.contacto_telefono.ilike(like),
                Cliente.ciudad.ilike(like),
            )
        )

    clientes = query.order_by(Cliente.nombre_razon_social.asc()).all()

    return render_template(
        "clientes/index.html",
        clientes=clientes,
        q=q,
        estado=estado
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if request.method == "POST":
        tipo_cliente = request.form.get("tipo_cliente", "").strip() or None
        identificacion = request.form.get("identificacion", "").strip() or None
        nombre_razon_social = request.form.get("nombre_razon_social", "").strip()
        contacto_nombre = request.form.get("contacto_nombre", "").strip() or None
        contacto_email = request.form.get("contacto_email", "").strip() or None
        contacto_telefono = request.form.get("contacto_telefono", "").strip() or None
        direccion = request.form.get("direccion", "").strip() or None
        ciudad = request.form.get("ciudad", "").strip() or None
        estado = request.form.get("estado", "activo").strip()

        if not nombre_razon_social:
            flash("El nombre o razón social es obligatorio.", "warning")
            return render_template("clientes/form.html", item=None)

        if identificacion:
            existente = Cliente.query.filter_by(
                empresa_id=current_user.empresa_id,
                identificacion=identificacion
            ).first()
            if existente:
                flash("Ya existe un cliente con esa identificación en esta empresa.", "warning")
                return render_template("clientes/form.html", item=None)

        cliente = Cliente(
            empresa_id=current_user.empresa_id,
            tipo_cliente=tipo_cliente,
            identificacion=identificacion,
            nombre_razon_social=nombre_razon_social,
            contacto_nombre=contacto_nombre,
            contacto_email=contacto_email,
            contacto_telefono=contacto_telefono,
            direccion=direccion,
            ciudad=ciudad,
            estado=estado,
        )

        db.session.add(cliente)
        db.session.commit()

        flash("Cliente creado correctamente.", "success")
        return redirect(url_for("clientes.detalle", cliente_id=cliente.id))

    return render_template("clientes/form.html", item=None)


@bp.route("/<int:cliente_id>")
@login_required
def detalle(cliente_id):
    item = Cliente.query.filter_by(
        id=cliente_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    return render_template("clientes/detalle.html", item=item)


@bp.route("/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required
def editar(cliente_id):
    item = Cliente.query.filter_by(
        id=cliente_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if request.method == "POST":
        tipo_cliente = request.form.get("tipo_cliente", "").strip() or None
        identificacion = request.form.get("identificacion", "").strip() or None
        nombre_razon_social = request.form.get("nombre_razon_social", "").strip()
        contacto_nombre = request.form.get("contacto_nombre", "").strip() or None
        contacto_email = request.form.get("contacto_email", "").strip() or None
        contacto_telefono = request.form.get("contacto_telefono", "").strip() or None
        direccion = request.form.get("direccion", "").strip() or None
        ciudad = request.form.get("ciudad", "").strip() or None
        estado = request.form.get("estado", "activo").strip()

        if not nombre_razon_social:
            flash("El nombre o razón social es obligatorio.", "warning")
            return render_template("clientes/form.html", item=item)

        if identificacion:
            existente = Cliente.query.filter(
                Cliente.empresa_id == current_user.empresa_id,
                Cliente.identificacion == identificacion,
                Cliente.id != item.id
            ).first()
            if existente:
                flash("Ya existe otro cliente con esa identificación en esta empresa.", "warning")
                return render_template("clientes/form.html", item=item)

        item.tipo_cliente = tipo_cliente
        item.identificacion = identificacion
        item.nombre_razon_social = nombre_razon_social
        item.contacto_nombre = contacto_nombre
        item.contacto_email = contacto_email
        item.contacto_telefono = contacto_telefono
        item.direccion = direccion
        item.ciudad = ciudad
        item.estado = estado

        db.session.commit()

        flash("Cliente actualizado correctamente.", "success")
        return redirect(url_for("clientes.detalle", cliente_id=item.id))

    return render_template("clientes/form.html", item=item)


@bp.route("/<int:cliente_id>/desactivar", methods=["POST"])
@login_required
def desactivar(cliente_id):
    item = Cliente.query.filter_by(
        id=cliente_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    item.estado = "inactivo"
    db.session.commit()

    flash("Cliente desactivado correctamente.", "warning")
    return redirect(url_for("clientes.detalle", cliente_id=item.id))


@bp.route("/<int:cliente_id>/activar", methods=["POST"])
@login_required
def activar(cliente_id):
    item = Cliente.query.filter_by(
        id=cliente_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    item.estado = "activo"
    db.session.commit()

    flash("Cliente activado correctamente.", "success")
    return redirect(url_for("clientes.detalle", cliente_id=item.id))