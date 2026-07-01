from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models.clientes import Cliente, Solicitud
from app.models.ofertas import Oferta

bp = Blueprint("ofertas", __name__, url_prefix="/ofertas")


def to_decimal(value, default="0.00"):
    raw = (value or "").strip()
    if not raw:
        raw = default
    raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal(default)


@bp.route("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "").strip()

    query = (
        Oferta.query
        .filter(Oferta.empresa_id == current_user.empresa_id)
        .join(Cliente, Oferta.cliente_id == Cliente.id)
        .join(Solicitud, Oferta.solicitud_id == Solicitud.id)
    )

    if estado:
        query = query.filter(Oferta.estado == estado)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Oferta.codigo.ilike(like),
                Oferta.objeto.ilike(like),
                Cliente.nombre_razon_social.ilike(like),
                Solicitud.codigo.ilike(like),
            )
        )

    ofertas = query.order_by(Oferta.id.desc()).all()

    return render_template(
        "ofertas/index.html",
        ofertas=ofertas,
        q=q,
        estado=estado
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    solicitudes = (
        Solicitud.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Solicitud.id.desc())
        .all()
    )

    if request.method == "POST":
        solicitud_id = request.form.get("solicitud_id", type=int)
        codigo = request.form.get("codigo", "").strip()
        fecha_emision = request.form.get("fecha_emision", "").strip()
        fecha_vencimiento = request.form.get("fecha_vencimiento", "").strip() or None
        objeto = request.form.get("objeto", "").strip() or None
        alcance = request.form.get("alcance", "").strip() or None
        condiciones = request.form.get("condiciones", "").strip() or None
        subtotal = to_decimal(request.form.get("subtotal"))
        impuestos = to_decimal(request.form.get("impuestos"))
        total = to_decimal(request.form.get("total"))
        estado = request.form.get("estado", "borrador").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not solicitud_id:
            flash("Debes seleccionar una solicitud.", "warning")
            return render_template("ofertas/form.html", item=None, solicitudes=solicitudes)

        solicitud = Solicitud.query.filter_by(
            id=solicitud_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not solicitud:
            flash("La solicitud seleccionada no es válida.", "danger")
            return render_template("ofertas/form.html", item=None, solicitudes=solicitudes)

        if not codigo:
            flash("El código de la oferta es obligatorio.", "warning")
            return render_template("ofertas/form.html", item=None, solicitudes=solicitudes)

        if not fecha_emision:
            flash("La fecha de emisión es obligatoria.", "warning")
            return render_template("ofertas/form.html", item=None, solicitudes=solicitudes)

        existe = Oferta.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo=codigo
        ).first()

        if existe:
            flash("Ya existe una oferta con ese código.", "danger")
            return render_template("ofertas/form.html", item=None, solicitudes=solicitudes)

        oferta = Oferta(
            empresa_id=current_user.empresa_id,
            solicitud_id=solicitud.id,
            cliente_id=solicitud.cliente_id,
            codigo=codigo,
            fecha_emision=fecha_emision,
            fecha_vencimiento=fecha_vencimiento,
            objeto=objeto,
            alcance=alcance,
            condiciones=condiciones,
            subtotal=subtotal,
            impuestos=impuestos,
            total=total,
            estado=estado,
            observaciones=observaciones,
            creado_por_id=current_user.id
        )

        db.session.add(oferta)
        db.session.commit()

        flash("Oferta creada correctamente.", "success")
        return redirect(url_for("ofertas.detalle", oferta_id=oferta.id))

    return render_template("ofertas/form.html", item=None, solicitudes=solicitudes)


@bp.route("/<int:oferta_id>")
@login_required
def detalle(oferta_id):
    item = Oferta.query.filter_by(
        id=oferta_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    return render_template("ofertas/detalle.html", item=item)


@bp.route("/<int:oferta_id>/editar", methods=["GET", "POST"])
@login_required
def editar(oferta_id):
    item = Oferta.query.filter_by(
        id=oferta_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    solicitudes = (
        Solicitud.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Solicitud.id.desc())
        .all()
    )

    if request.method == "POST":
        solicitud_id = request.form.get("solicitud_id", type=int)
        codigo = request.form.get("codigo", "").strip()
        fecha_emision = request.form.get("fecha_emision", "").strip()
        fecha_vencimiento = request.form.get("fecha_vencimiento", "").strip() or None
        objeto = request.form.get("objeto", "").strip() or None
        alcance = request.form.get("alcance", "").strip() or None
        condiciones = request.form.get("condiciones", "").strip() or None
        subtotal = to_decimal(request.form.get("subtotal"))
        impuestos = to_decimal(request.form.get("impuestos"))
        total = to_decimal(request.form.get("total"))
        estado = request.form.get("estado", "borrador").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not solicitud_id:
            flash("Debes seleccionar una solicitud.", "warning")
            return render_template("ofertas/form.html", item=item, solicitudes=solicitudes)

        solicitud = Solicitud.query.filter_by(
            id=solicitud_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not solicitud:
            flash("La solicitud seleccionada no es válida.", "danger")
            return render_template("ofertas/form.html", item=item, solicitudes=solicitudes)

        if not codigo:
            flash("El código de la oferta es obligatorio.", "warning")
            return render_template("ofertas/form.html", item=item, solicitudes=solicitudes)

        if not fecha_emision:
            flash("La fecha de emisión es obligatoria.", "warning")
            return render_template("ofertas/form.html", item=item, solicitudes=solicitudes)

        existe = (
            Oferta.query
            .filter(
                Oferta.empresa_id == current_user.empresa_id,
                Oferta.codigo == codigo,
                Oferta.id != item.id
            )
            .first()
        )

        if existe:
            flash("Ya existe otra oferta con ese código.", "danger")
            return render_template("ofertas/form.html", item=item, solicitudes=solicitudes)

        item.solicitud_id = solicitud.id
        item.cliente_id = solicitud.cliente_id
        item.codigo = codigo
        item.fecha_emision = fecha_emision
        item.fecha_vencimiento = fecha_vencimiento
        item.objeto = objeto
        item.alcance = alcance
        item.condiciones = condiciones
        item.subtotal = subtotal
        item.impuestos = impuestos
        item.total = total
        item.estado = estado
        item.observaciones = observaciones

        db.session.commit()

        flash("Oferta actualizada correctamente.", "success")
        return redirect(url_for("ofertas.detalle", oferta_id=item.id))

    return render_template("ofertas/form.html", item=item, solicitudes=solicitudes)