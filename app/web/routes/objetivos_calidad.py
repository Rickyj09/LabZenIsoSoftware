from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.objetivos_calidad import ObjetivoCalidad
from app.models.seguridad import Usuario

bp = Blueprint("objetivos_calidad", __name__, url_prefix="/objetivos-calidad")


@bp.route("/")
@login_required
def index():
    objetivos = (
        ObjetivoCalidad.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(ObjetivoCalidad.id.desc())
        .all()
    )
    return render_template("objetivos_calidad/index.html", objetivos=objetivos)


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    usuarios = (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Usuario.nombre.asc())
        .all()
    )

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        indicador = request.form.get("indicador", "").strip()
        meta = request.form.get("meta", "").strip()
        unidad = request.form.get("unidad", "").strip()
        frecuencia = request.form.get("frecuencia", "").strip()
        responsable_id = request.form.get("responsable_id", type=int)
        fecha_inicio = request.form.get("fecha_inicio", "").strip()
        fecha_fin = request.form.get("fecha_fin", "").strip()
        estado = request.form.get("estado", "activo").strip()
        resultado_actual = request.form.get("resultado_actual", "").strip()
        observaciones = request.form.get("observaciones", "").strip()

        if not nombre or not indicador or not meta or not frecuencia or not fecha_inicio:
            flash("Nombre, indicador, meta, frecuencia y fecha inicio son obligatorios.", "danger")
            return render_template("objetivos_calidad/form.html", item=None, usuarios=usuarios)

        item = ObjetivoCalidad(
            empresa_id=current_user.empresa_id,
            nombre=nombre,
            descripcion=descripcion,
            indicador=indicador,
            meta=meta,
            unidad=unidad,
            frecuencia=frecuencia,
            responsable_id=responsable_id,
            fecha_inicio=datetime.strptime(fecha_inicio, "%Y-%m-%d").date(),
            fecha_fin=datetime.strptime(fecha_fin, "%Y-%m-%d").date() if fecha_fin else None,
            estado=estado,
            resultado_actual=resultado_actual,
            observaciones=observaciones,
        )

        db.session.add(item)
        db.session.commit()

        flash("Objetivo de calidad creado correctamente.", "success")
        return redirect(url_for("objetivos_calidad.index"))

    return render_template("objetivos_calidad/form.html", item=None, usuarios=usuarios)


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = ObjetivoCalidad.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    usuarios = (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Usuario.nombre.asc())
        .all()
    )

    if request.method == "POST":
        item.nombre = request.form.get("nombre", "").strip()
        item.descripcion = request.form.get("descripcion", "").strip()
        item.indicador = request.form.get("indicador", "").strip()
        item.meta = request.form.get("meta", "").strip()
        item.unidad = request.form.get("unidad", "").strip()
        item.frecuencia = request.form.get("frecuencia", "").strip()
        item.responsable_id = request.form.get("responsable_id", type=int)
        fecha_inicio = request.form.get("fecha_inicio", "").strip()
        fecha_fin = request.form.get("fecha_fin", "").strip()
        item.estado = request.form.get("estado", "activo").strip()
        item.resultado_actual = request.form.get("resultado_actual", "").strip()
        item.observaciones = request.form.get("observaciones", "").strip()

        if not item.nombre or not item.indicador or not item.meta or not item.frecuencia or not fecha_inicio:
            flash("Nombre, indicador, meta, frecuencia y fecha inicio son obligatorios.", "danger")
            return render_template("objetivos_calidad/form.html", item=item, usuarios=usuarios)

        item.fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        item.fecha_fin = datetime.strptime(fecha_fin, "%Y-%m-%d").date() if fecha_fin else None

        db.session.commit()

        flash("Objetivo de calidad actualizado correctamente.", "success")
        return redirect(url_for("objetivos_calidad.index"))

    return render_template("objetivos_calidad/form.html", item=item, usuarios=usuarios)