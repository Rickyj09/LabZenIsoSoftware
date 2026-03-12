from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.mapa_procesos import Proceso
from app.models.seguridad import Usuario

bp = Blueprint("mapa_procesos", __name__, url_prefix="/mapa-procesos")


@bp.route("/")
@login_required
def index():
    procesos = (
        Proceso.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Proceso.tipo.asc(), Proceso.nombre.asc())
        .all()
    )
    return render_template("mapa_procesos/index.html", procesos=procesos)


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
        codigo = request.form.get("codigo", "").strip()
        tipo = request.form.get("tipo", "").strip()
        objetivo = request.form.get("objetivo", "").strip()
        alcance = request.form.get("alcance", "").strip()
        entradas = request.form.get("entradas", "").strip()
        salidas = request.form.get("salidas", "").strip()
        responsable_id = request.form.get("responsable_id", type=int)
        estado = request.form.get("estado", "activo").strip()

        if not nombre or not tipo:
            flash("Nombre y tipo son obligatorios.", "danger")
            return render_template("mapa_procesos/form.html", item=None, usuarios=usuarios)

        item = Proceso(
            empresa_id=current_user.empresa_id,
            nombre=nombre,
            codigo=codigo,
            tipo=tipo,
            objetivo=objetivo,
            alcance=alcance,
            entradas=entradas,
            salidas=salidas,
            responsable_id=responsable_id,
            estado=estado,
        )

        db.session.add(item)
        db.session.commit()

        flash("Proceso creado correctamente.", "success")
        return redirect(url_for("mapa_procesos.index"))

    return render_template("mapa_procesos/form.html", item=None, usuarios=usuarios)


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = Proceso.query.filter_by(
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
        item.codigo = request.form.get("codigo", "").strip()
        item.tipo = request.form.get("tipo", "").strip()
        item.objetivo = request.form.get("objetivo", "").strip()
        item.alcance = request.form.get("alcance", "").strip()
        item.entradas = request.form.get("entradas", "").strip()
        item.salidas = request.form.get("salidas", "").strip()
        item.responsable_id = request.form.get("responsable_id", type=int)
        item.estado = request.form.get("estado", "activo").strip()

        if not item.nombre or not item.tipo:
            flash("Nombre y tipo son obligatorios.", "danger")
            return render_template("mapa_procesos/form.html", item=item, usuarios=usuarios)

        db.session.commit()

        flash("Proceso actualizado correctamente.", "success")
        return redirect(url_for("mapa_procesos.index"))

    return render_template("mapa_procesos/form.html", item=item, usuarios=usuarios)

@bp.route("/visual")
@login_required
def visual():
        procesos = (
        Proceso.query
        .filter_by(empresa_id=current_user.empresa_id, estado="activo")
        .order_by(Proceso.nombre.asc())
        .all()
        )

        estrategicos = [p for p in procesos if p.tipo == "estrategico"]
        misionales = [p for p in procesos if p.tipo == "misional"]
        apoyo = [p for p in procesos if p.tipo == "apoyo"]

        return render_template(
            "mapa_procesos/visual.html",
            estrategicos=estrategicos,
            misionales=misionales,
            apoyo=apoyo
        )

@bp.route("/<int:item_id>")
@login_required
def detalle(item_id):
    item = Proceso.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    riesgos = [r for r in item.riesgos_oportunidades if r.tipo == "riesgo"]
    oportunidades = [r for r in item.riesgos_oportunidades if r.tipo == "oportunidad"]
    abiertos = [r for r in item.riesgos_oportunidades if r.estado != "cerrado"]

    nivel_maximo = max([r.nivel for r in item.riesgos_oportunidades], default=0)

    return render_template(
        "mapa_procesos/detalle.html",
        item=item,
        total_riesgos=len(riesgos),
        total_oportunidades=len(oportunidades),
        total_abiertos=len(abiertos),
        nivel_maximo=nivel_maximo
    )