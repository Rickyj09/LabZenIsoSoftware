from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.mapa_procesos import Proceso
from app.models.riesgos_oportunidades import RiesgoOportunidad
from app.models.seguridad import Usuario

bp = Blueprint("riesgos_oportunidades", __name__, url_prefix="/riesgos-oportunidades")


@bp.route("/proceso/<int:proceso_id>")
@login_required
def index(proceso_id):
    proceso = Proceso.query.filter_by(
        id=proceso_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    items = (
        RiesgoOportunidad.query
        .filter_by(
            empresa_id=current_user.empresa_id,
            proceso_id=proceso.id
        )
        .order_by(RiesgoOportunidad.id.desc())
        .all()
    )

    return render_template(
        "riesgos_oportunidades/index.html",
        proceso=proceso,
        items=items
    )


@bp.route("/proceso/<int:proceso_id>/nuevo", methods=["GET", "POST"])
@login_required
def nuevo(proceso_id):
    proceso = Proceso.query.filter_by(
        id=proceso_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    usuarios = (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Usuario.nombre.asc())
        .all()
    )

    if request.method == "POST":
        tipo = request.form.get("tipo", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        causa = request.form.get("causa", "").strip()
        efecto = request.form.get("efecto", "").strip()
        probabilidad = request.form.get("probabilidad", type=int)
        impacto = request.form.get("impacto", type=int)
        accion = request.form.get("accion", "").strip()
        responsable_id = request.form.get("responsable_id", type=int)
        fecha_compromiso = request.form.get("fecha_compromiso", "").strip()
        estado = request.form.get("estado", "abierto").strip()

        if not tipo or not descripcion or not probabilidad or not impacto:
            flash("Tipo, descripción, probabilidad e impacto son obligatorios.", "danger")
            return render_template(
                "riesgos_oportunidades/form.html",
                proceso=proceso,
                item=None,
                usuarios=usuarios
            )

        nivel = probabilidad * impacto

        item = RiesgoOportunidad(
            empresa_id=current_user.empresa_id,
            proceso_id=proceso.id,
            tipo=tipo,
            descripcion=descripcion,
            causa=causa,
            efecto=efecto,
            probabilidad=probabilidad,
            impacto=impacto,
            nivel=nivel,
            accion=accion,
            responsable_id=responsable_id,
            fecha_compromiso=datetime.strptime(fecha_compromiso, "%Y-%m-%d").date() if fecha_compromiso else None,
            estado=estado,
        )

        db.session.add(item)
        db.session.commit()

        flash("Riesgo / oportunidad registrado correctamente.", "success")
        return redirect(url_for("riesgos_oportunidades.index", proceso_id=proceso.id))

    return render_template(
        "riesgos_oportunidades/form.html",
        proceso=proceso,
        item=None,
        usuarios=usuarios
    )


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = RiesgoOportunidad.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    proceso = item.proceso

    usuarios = (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Usuario.nombre.asc())
        .all()
    )

    if request.method == "POST":
        item.tipo = request.form.get("tipo", "").strip()
        item.descripcion = request.form.get("descripcion", "").strip()
        item.causa = request.form.get("causa", "").strip()
        item.efecto = request.form.get("efecto", "").strip()
        item.probabilidad = request.form.get("probabilidad", type=int)
        item.impacto = request.form.get("impacto", type=int)
        item.nivel = (item.probabilidad or 0) * (item.impacto or 0)
        item.accion = request.form.get("accion", "").strip()
        item.responsable_id = request.form.get("responsable_id", type=int)

        fecha_compromiso = request.form.get("fecha_compromiso", "").strip()
        item.fecha_compromiso = datetime.strptime(fecha_compromiso, "%Y-%m-%d").date() if fecha_compromiso else None

        item.estado = request.form.get("estado", "abierto").strip()

        if not item.tipo or not item.descripcion or not item.probabilidad or not item.impacto:
            flash("Tipo, descripción, probabilidad e impacto son obligatorios.", "danger")
            return render_template(
                "riesgos_oportunidades/form.html",
                proceso=proceso,
                item=item,
                usuarios=usuarios
            )

        db.session.commit()

        flash("Registro actualizado correctamente.", "success")
        return redirect(url_for("riesgos_oportunidades.index", proceso_id=proceso.id))

    return render_template(
        "riesgos_oportunidades/form.html",
        proceso=proceso,
        item=item,
        usuarios=usuarios
    )