from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.laboratorio import Muestra, EnsayoCatalogo, Metodo, MuestraEnsayo
from app.models.seguridad import Usuario

bp = Blueprint("muestra_ensayos", __name__, url_prefix="/muestra-ensayos")


@bp.route("/")
@login_required
def index():
    items = (
        MuestraEnsayo.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(MuestraEnsayo.id.desc())
        .all()
    )
    return render_template("muestra_ensayos/index.html", items=items)


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    muestras = (
        Muestra.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Muestra.id.desc())
        .all()
    )

    ensayos = (
        EnsayoCatalogo.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(EnsayoCatalogo.nombre.asc())
        .all()
    )

    metodos = (
        Metodo.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(Metodo.nombre.asc())
        .all()
    )

    analistas = (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(Usuario.nombre.asc(), Usuario.apellido.asc())
        .all()
    )

    if request.method == "POST":
        muestra_id = request.form.get("muestra_id", type=int)
        ensayo_id = request.form.get("ensayo_id", type=int)
        metodo_id = request.form.get("metodo_id", type=int)
        analista_id = request.form.get("analista_id", type=int)
        fecha_programada = request.form.get("fecha_programada", "").strip() or None
        fecha_inicio = request.form.get("fecha_inicio", "").strip() or None
        fecha_fin = request.form.get("fecha_fin", "").strip() or None
        estado = request.form.get("estado", "pendiente").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not muestra_id:
            flash("Debes seleccionar una muestra.", "warning")
            return render_template(
                "muestra_ensayos/form.html",
                item=None,
                muestras=muestras,
                ensayos=ensayos,
                metodos=metodos,
                analistas=analistas
            )

        if not ensayo_id:
            flash("Debes seleccionar un ensayo.", "warning")
            return render_template(
                "muestra_ensayos/form.html",
                item=None,
                muestras=muestras,
                ensayos=ensayos,
                metodos=metodos,
                analistas=analistas
            )

        if not metodo_id:
            flash("Debes seleccionar un método.", "warning")
            return render_template(
                "muestra_ensayos/form.html",
                item=None,
                muestras=muestras,
                ensayos=ensayos,
                metodos=metodos,
                analistas=analistas
            )

        muestra = Muestra.query.filter_by(
            id=muestra_id,
            empresa_id=current_user.empresa_id
        ).first()

        ensayo = EnsayoCatalogo.query.filter_by(
            id=ensayo_id,
            empresa_id=current_user.empresa_id,
            activo=True
        ).first()

        metodo = Metodo.query.filter_by(
            id=metodo_id,
            empresa_id=current_user.empresa_id,
            activo=True
        ).first()

        if not muestra or not ensayo or not metodo:
            flash("La relación muestra/ensayo/método no es válida.", "danger")
            return render_template(
                "muestra_ensayos/form.html",
                item=None,
                muestras=muestras,
                ensayos=ensayos,
                metodos=metodos,
                analistas=analistas
            )

        item = MuestraEnsayo(
            empresa_id=current_user.empresa_id,
            muestra_id=muestra_id,
            ensayo_id=ensayo_id,
            metodo_id=metodo_id,
            analista_id=analista_id or None,
            fecha_programada=fecha_programada,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            estado=estado,
            observaciones=observaciones,
        )

        db.session.add(item)
        db.session.commit()

        flash("Ensayo asignado correctamente a la muestra.", "success")
        return redirect(url_for("muestra_ensayos.index"))

    return render_template(
        "muestra_ensayos/form.html",
        item=None,
        muestras=muestras,
        ensayos=ensayos,
        metodos=metodos,
        analistas=analistas
    )


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = MuestraEnsayo.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    muestras = (
        Muestra.query
        .filter_by(empresa_id=current_user.empresa_id)
        .order_by(Muestra.id.desc())
        .all()
    )

    ensayos = (
        EnsayoCatalogo.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(EnsayoCatalogo.nombre.asc())
        .all()
    )

    metodos = (
        Metodo.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(Metodo.nombre.asc())
        .all()
    )

    analistas = (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(Usuario.nombre.asc(), Usuario.apellido.asc())
        .all()
    )

    if request.method == "POST":
        muestra_id = request.form.get("muestra_id", type=int)
        ensayo_id = request.form.get("ensayo_id", type=int)
        metodo_id = request.form.get("metodo_id", type=int)
        analista_id = request.form.get("analista_id", type=int)
        fecha_programada = request.form.get("fecha_programada", "").strip() or None
        fecha_inicio = request.form.get("fecha_inicio", "").strip() or None
        fecha_fin = request.form.get("fecha_fin", "").strip() or None
        estado = request.form.get("estado", "pendiente").strip()
        observaciones = request.form.get("observaciones", "").strip() or None

        if not muestra_id or not ensayo_id or not metodo_id:
            flash("Muestra, ensayo y método son obligatorios.", "warning")
            return render_template(
                "muestra_ensayos/form.html",
                item=item,
                muestras=muestras,
                ensayos=ensayos,
                metodos=metodos,
                analistas=analistas
            )

        item.muestra_id = muestra_id
        item.ensayo_id = ensayo_id
        item.metodo_id = metodo_id
        item.analista_id = analista_id or None
        item.fecha_programada = fecha_programada
        item.fecha_inicio = fecha_inicio
        item.fecha_fin = fecha_fin
        item.estado = estado
        item.observaciones = observaciones

        db.session.commit()

        flash("Asignación actualizada correctamente.", "success")
        return redirect(url_for("muestra_ensayos.index"))

    return render_template(
        "muestra_ensayos/form.html",
        item=item,
        muestras=muestras,
        ensayos=ensayos,
        metodos=metodos,
        analistas=analistas
    )