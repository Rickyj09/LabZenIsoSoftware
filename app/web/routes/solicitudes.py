from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models.clientes import Cliente, Solicitud

bp = Blueprint("solicitudes", __name__, url_prefix="/solicitudes")


@bp.route("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "").strip()

    query = (
        Solicitud.query
        .filter(Solicitud.empresa_id == current_user.empresa_id)
        .join(Cliente, Solicitud.cliente_id == Cliente.id)
    )

    if estado:
        query = query.filter(Solicitud.estado == estado)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Solicitud.codigo.ilike(like),
                Solicitud.tipo_servicio.ilike(like),
                Solicitud.descripcion.ilike(like),
                Cliente.nombre_razon_social.ilike(like),
                Cliente.identificacion.ilike(like),
            )
        )

    solicitudes = query.order_by(Solicitud.id.desc()).all()

    return render_template(
        "solicitudes/index.html",
        solicitudes=solicitudes,
        q=q,
        estado=estado
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    clientes = (
        Cliente.query
        .filter_by(empresa_id=current_user.empresa_id, estado="activo")
        .order_by(Cliente.nombre_razon_social.asc())
        .all()
    )

    if request.method == "POST":
        cliente_id = request.form.get("cliente_id", type=int)
        codigo = request.form.get("codigo", "").strip()
        fecha_solicitud = request.form.get("fecha_solicitud", "").strip()
        fecha_recepcion = request.form.get("fecha_recepcion", "").strip() or None
        tipo_servicio = request.form.get("tipo_servicio", "").strip() or None
        descripcion = request.form.get("descripcion", "").strip() or None
        estado = request.form.get("estado", "recibida").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not cliente_id:
            flash("Debes seleccionar un cliente.", "warning")
            return render_template("solicitudes/form.html", item=None, clientes=clientes)

        cliente = Cliente.query.filter_by(
            id=cliente_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not cliente:
            flash("El cliente seleccionado no es válido.", "danger")
            return render_template("solicitudes/form.html", item=None, clientes=clientes)

        if not codigo:
            flash("El código de la solicitud es obligatorio.", "warning")
            return render_template("solicitudes/form.html", item=None, clientes=clientes)

        if not fecha_solicitud:
            flash("La fecha de solicitud es obligatoria.", "warning")
            return render_template("solicitudes/form.html", item=None, clientes=clientes)

        existe = Solicitud.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo=codigo
        ).first()

        if existe:
            flash("Ya existe una solicitud con ese código.", "danger")
            return render_template("solicitudes/form.html", item=None, clientes=clientes)

        solicitud = Solicitud(
            empresa_id=current_user.empresa_id,
            cliente_id=cliente_id,
            codigo=codigo,
            fecha_solicitud=fecha_solicitud,
            fecha_recepcion=fecha_recepcion,
            tipo_servicio=tipo_servicio,
            descripcion=descripcion,
            estado=estado,
            observaciones=observaciones,
            creado_por_id=current_user.id
        )

        db.session.add(solicitud)
        db.session.commit()

        flash("Solicitud creada correctamente.", "success")
        return redirect(url_for("solicitudes.detalle", solicitud_id=solicitud.id))

    return render_template("solicitudes/form.html", item=None, clientes=clientes)


@bp.route("/<int:solicitud_id>")
@login_required
def detalle(solicitud_id):
    item = (
        Solicitud.query
        .filter_by(id=solicitud_id, empresa_id=current_user.empresa_id)
        .first_or_404()
    )
    return render_template("solicitudes/detalle.html", item=item)


@bp.route("/<int:solicitud_id>/editar", methods=["GET", "POST"])
@login_required
def editar(solicitud_id):
    item = Solicitud.query.filter_by(
        id=solicitud_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    clientes = (
        Cliente.query
        .filter_by(empresa_id=current_user.empresa_id, estado="activo")
        .order_by(Cliente.nombre_razon_social.asc())
        .all()
    )

    if request.method == "POST":
        cliente_id = request.form.get("cliente_id", type=int)
        codigo = request.form.get("codigo", "").strip()
        fecha_solicitud = request.form.get("fecha_solicitud", "").strip()
        fecha_recepcion = request.form.get("fecha_recepcion", "").strip() or None
        tipo_servicio = request.form.get("tipo_servicio", "").strip() or None
        descripcion = request.form.get("descripcion", "").strip() or None
        estado = request.form.get("estado", "recibida").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not cliente_id:
            flash("Debes seleccionar un cliente.", "warning")
            return render_template("solicitudes/form.html", item=item, clientes=clientes)

        cliente = Cliente.query.filter_by(
            id=cliente_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not cliente:
            flash("El cliente seleccionado no es válido.", "danger")
            return render_template("solicitudes/form.html", item=item, clientes=clientes)

        if not codigo:
            flash("El código de la solicitud es obligatorio.", "warning")
            return render_template("solicitudes/form.html", item=item, clientes=clientes)

        if not fecha_solicitud:
            flash("La fecha de solicitud es obligatoria.", "warning")
            return render_template("solicitudes/form.html", item=item, clientes=clientes)

        existe = (
            Solicitud.query
            .filter(
                Solicitud.empresa_id == current_user.empresa_id,
                Solicitud.codigo == codigo,
                Solicitud.id != item.id
            )
            .first()
        )

        if existe:
            flash("Ya existe otra solicitud con ese código.", "danger")
            return render_template("solicitudes/form.html", item=item, clientes=clientes)

        item.cliente_id = cliente_id
        item.codigo = codigo
        item.fecha_solicitud = fecha_solicitud
        item.fecha_recepcion = fecha_recepcion
        item.tipo_servicio = tipo_servicio
        item.descripcion = descripcion
        item.estado = estado
        item.observaciones = observaciones

        db.session.commit()

        flash("Solicitud actualizada correctamente.", "success")
        return redirect(url_for("solicitudes.detalle", solicitud_id=item.id))

    return render_template("solicitudes/form.html", item=item, clientes=clientes)