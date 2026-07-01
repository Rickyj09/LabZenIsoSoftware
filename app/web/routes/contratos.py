from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models.ofertas import Oferta
from app.models.contratos import Contrato

bp = Blueprint("contratos", __name__, url_prefix="/contratos")


@bp.route("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "").strip()

    query = (
        Contrato.query
        .filter(Contrato.empresa_id == current_user.empresa_id)
        .join(Oferta, Contrato.oferta_id == Oferta.id)
    )

    if estado:
        query = query.filter(Contrato.estado == estado)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Contrato.codigo.ilike(like),
                Contrato.objeto.ilike(like),
                Oferta.codigo.ilike(like),
            )
        )

    contratos = query.order_by(Contrato.id.desc()).all()

    return render_template(
        "contratos/index.html",
        contratos=contratos,
        q=q,
        estado=estado
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    ofertas = (
        Oferta.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Oferta.id.desc())
        .all()
    )

    if request.method == "POST":
        oferta_id = request.form.get("oferta_id", type=int)
        codigo = request.form.get("codigo", "").strip()
        fecha_inicio = request.form.get("fecha_inicio", "").strip()
        fecha_fin = request.form.get("fecha_fin", "").strip() or None
        objeto = request.form.get("objeto", "").strip() or None
        condiciones = request.form.get("condiciones", "").strip() or None
        estado = request.form.get("estado", "borrador").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not oferta_id:
            flash("Debes seleccionar una oferta.", "warning")
            return render_template("contratos/form.html", item=None, ofertas=ofertas)

        oferta = Oferta.query.filter_by(
            id=oferta_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not oferta:
            flash("La oferta seleccionada no es válida.", "danger")
            return render_template("contratos/form.html", item=None, ofertas=ofertas)

        if not codigo:
            flash("El código del contrato es obligatorio.", "warning")
            return render_template("contratos/form.html", item=None, ofertas=ofertas)

        if not fecha_inicio:
            flash("La fecha de inicio es obligatoria.", "warning")
            return render_template("contratos/form.html", item=None, ofertas=ofertas)

        existe = Contrato.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo=codigo
        ).first()

        if existe:
            flash("Ya existe un contrato con ese código.", "danger")
            return render_template("contratos/form.html", item=None, ofertas=ofertas)

        contrato = Contrato(
            empresa_id=current_user.empresa_id,
            oferta_id=oferta.id,
            solicitud_id=oferta.solicitud_id,
            cliente_id=oferta.cliente_id,
            codigo=codigo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            objeto=objeto,
            condiciones=condiciones,
            estado=estado,
            observaciones=observaciones,
            creado_por_id=current_user.id
        )

        db.session.add(contrato)
        db.session.commit()

        flash("Contrato creado correctamente.", "success")
        return redirect(url_for("contratos.detalle", contrato_id=contrato.id))

    return render_template("contratos/form.html", item=None, ofertas=ofertas)


@bp.route("/<int:contrato_id>")
@login_required
def detalle(contrato_id):
    item = Contrato.query.filter_by(
        id=contrato_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    return render_template("contratos/detalle.html", item=item)


@bp.route("/<int:contrato_id>/editar", methods=["GET", "POST"])
@login_required
def editar(contrato_id):
    item = Contrato.query.filter_by(
        id=contrato_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    ofertas = (
        Oferta.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Oferta.id.desc())
        .all()
    )

    if request.method == "POST":
        oferta_id = request.form.get("oferta_id", type=int)
        codigo = request.form.get("codigo", "").strip()
        fecha_inicio = request.form.get("fecha_inicio", "").strip()
        fecha_fin = request.form.get("fecha_fin", "").strip() or None
        objeto = request.form.get("objeto", "").strip() or None
        condiciones = request.form.get("condiciones", "").strip() or None
        estado = request.form.get("estado", "borrador").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not oferta_id:
            flash("Debes seleccionar una oferta.", "warning")
            return render_template("contratos/form.html", item=item, ofertas=ofertas)

        oferta = Oferta.query.filter_by(
            id=oferta_id,
            empresa_id=current_user.empresa_id
        ).first()

        if not oferta:
            flash("La oferta seleccionada no es válida.", "danger")
            return render_template("contratos/form.html", item=item, ofertas=ofertas)

        if not codigo:
            flash("El código del contrato es obligatorio.", "warning")
            return render_template("contratos/form.html", item=item, ofertas=ofertas)

        if not fecha_inicio:
            flash("La fecha de inicio es obligatoria.", "warning")
            return render_template("contratos/form.html", item=item, ofertas=ofertas)

        existe = (
            Contrato.query
            .filter(
                Contrato.empresa_id == current_user.empresa_id,
                Contrato.codigo == codigo,
                Contrato.id != item.id
            )
            .first()
        )

        if existe:
            flash("Ya existe otro contrato con ese código.", "danger")
            return render_template("contratos/form.html", item=item, ofertas=ofertas)

        item.oferta_id = oferta.id
        item.solicitud_id = oferta.solicitud_id
        item.cliente_id = oferta.cliente_id
        item.codigo = codigo
        item.fecha_inicio = fecha_inicio
        item.fecha_fin = fecha_fin
        item.objeto = objeto
        item.condiciones = condiciones
        item.estado = estado
        item.observaciones = observaciones

        db.session.commit()

        flash("Contrato actualizado correctamente.", "success")
        return redirect(url_for("contratos.detalle", contrato_id=item.id))

    return render_template("contratos/form.html", item=item, ofertas=ofertas)