from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.clientes import Solicitud
from app.models.laboratorio import Muestra

bp = Blueprint("muestras", __name__, url_prefix="/muestras")


@bp.route("/")
@login_required
def index():
    muestras = (
        Muestra.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Muestra.id.desc())
        .all()
    )
    return render_template("muestras/index.html", muestras=muestras)


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
        codigo_interno = request.form.get("codigo_interno", "").strip()
        codigo_cliente = request.form.get("codigo_cliente", "").strip() or None
        tipo_muestra = request.form.get("tipo_muestra", "").strip() or None
        descripcion = request.form.get("descripcion", "").strip() or None
        fecha_recepcion = request.form.get("fecha_recepcion", "").strip() or None
        fecha_muestreo = request.form.get("fecha_muestreo", "").strip() or None
        condicion_recepcion = request.form.get("condicion_recepcion", "").strip() or None
        ubicacion_almacenamiento = request.form.get("ubicacion_almacenamiento", "").strip() or None
        estado = request.form.get("estado", "recibida").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not solicitud_id:
            flash("Debes seleccionar una solicitud.", "warning")
            return render_template("muestras/form.html", item=None, solicitudes=solicitudes)

        solicitud = Solicitud.query.filter_by(
            id=solicitud_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not solicitud:
            flash("La solicitud seleccionada no es válida.", "danger")
            return render_template("muestras/form.html", item=None, solicitudes=solicitudes)

        if not codigo_interno:
            flash("El código interno es obligatorio.", "warning")
            return render_template("muestras/form.html", item=None, solicitudes=solicitudes)

        existe = Muestra.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo_interno=codigo_interno
        ).first()

        if existe:
            flash("Ya existe una muestra con ese código interno.", "danger")
            return render_template("muestras/form.html", item=None, solicitudes=solicitudes)

        muestra = Muestra(
            empresa_id=current_user.empresa_id,
            solicitud_id=solicitud_id,
            codigo_interno=codigo_interno,
            codigo_cliente=codigo_cliente,
            tipo_muestra=tipo_muestra,
            descripcion=descripcion,
            fecha_recepcion=fecha_recepcion,
            fecha_muestreo=fecha_muestreo,
            recibido_por_id=current_user.id,
            condicion_recepcion=condicion_recepcion,
            ubicacion_almacenamiento=ubicacion_almacenamiento,
            estado=estado,
            observaciones=observaciones,
        )

        db.session.add(muestra)
        db.session.commit()

        flash("Muestra creada correctamente.", "success")
        return redirect(url_for("muestras.index"))

    return render_template("muestras/form.html", item=None, solicitudes=solicitudes)


@bp.route("/<int:muestra_id>/editar", methods=["GET", "POST"])
@login_required
def editar(muestra_id):
    item = Muestra.query.filter_by(
        id=muestra_id,
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
        codigo_interno = request.form.get("codigo_interno", "").strip()
        codigo_cliente = request.form.get("codigo_cliente", "").strip() or None
        tipo_muestra = request.form.get("tipo_muestra", "").strip() or None
        descripcion = request.form.get("descripcion", "").strip() or None
        fecha_recepcion = request.form.get("fecha_recepcion", "").strip() or None
        fecha_muestreo = request.form.get("fecha_muestreo", "").strip() or None
        condicion_recepcion = request.form.get("condicion_recepcion", "").strip() or None
        ubicacion_almacenamiento = request.form.get("ubicacion_almacenamiento", "").strip() or None
        estado = request.form.get("estado", "recibida").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not solicitud_id:
            flash("Debes seleccionar una solicitud.", "warning")
            return render_template("muestras/form.html", item=item, solicitudes=solicitudes)

        solicitud = Solicitud.query.filter_by(
            id=solicitud_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not solicitud:
            flash("La solicitud seleccionada no es válida.", "danger")
            return render_template("muestras/form.html", item=item, solicitudes=solicitudes)

        if not codigo_interno:
            flash("El código interno es obligatorio.", "warning")
            return render_template("muestras/form.html", item=item, solicitudes=solicitudes)

        existe = (
            Muestra.query
            .filter(
                Muestra.empresa_id == current_user.empresa_id,
                Muestra.codigo_interno == codigo_interno,
                Muestra.id != item.id
            )
            .first()
        )

        if existe:
            flash("Ya existe otra muestra con ese código interno.", "danger")
            return render_template("muestras/form.html", item=item, solicitudes=solicitudes)

        item.solicitud_id = solicitud_id
        item.codigo_interno = codigo_interno
        item.codigo_cliente = codigo_cliente
        item.tipo_muestra = tipo_muestra
        item.descripcion = descripcion
        item.fecha_recepcion = fecha_recepcion
        item.fecha_muestreo = fecha_muestreo
        item.condicion_recepcion = condicion_recepcion
        item.ubicacion_almacenamiento = ubicacion_almacenamiento
        item.estado = estado
        item.observaciones = observaciones

        db.session.commit()

        flash("Muestra actualizada correctamente.", "success")
        return redirect(url_for("muestras.index"))

    return render_template("muestras/form.html", item=item, solicitudes=solicitudes)