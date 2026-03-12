from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.laboratorio import Resultado, MuestraEnsayo

bp = Blueprint("resultados", __name__, url_prefix="/resultados")


@bp.route("/muestra-ensayo/<int:muestra_ensayo_id>")
@login_required
def index(muestra_ensayo_id):

    muestra_ensayo = MuestraEnsayo.query.get_or_404(muestra_ensayo_id)

    resultados = (
        Resultado.query
        .filter_by(muestra_ensayo_id=muestra_ensayo_id)
        .order_by(Resultado.parametro.asc())
        .all()
    )

    return render_template(
        "resultados/index.html",
        resultados=resultados,
        muestra_ensayo=muestra_ensayo
    )


@bp.route("/muestra-ensayo/<int:muestra_ensayo_id>/nuevo", methods=["GET", "POST"])
@login_required
def nuevo(muestra_ensayo_id):

    muestra_ensayo = MuestraEnsayo.query.get_or_404(muestra_ensayo_id)

    if request.method == "POST":

        parametro = request.form.get("parametro")
        valor = request.form.get("valor")
        unidad = request.form.get("unidad")
        limite_min = request.form.get("limite_min") or None
        limite_max = request.form.get("limite_max") or None
        observaciones = request.form.get("observaciones")

        conforme = request.form.get("conforme") == "on"

        resultado = Resultado(
            empresa_id=current_user.empresa_id,
            muestra_ensayo_id=muestra_ensayo_id,
            parametro=parametro,
            valor=valor,
            unidad=unidad,
            limite_min=limite_min,
            limite_max=limite_max,
            conforme=conforme,
            observaciones=observaciones
        )

        db.session.add(resultado)
        db.session.commit()

        flash("Resultado registrado correctamente.", "success")

        return redirect(
            url_for("resultados.index", muestra_ensayo_id=muestra_ensayo_id)
        )

    return render_template(
        "resultados/form.html",
        muestra_ensayo=muestra_ensayo,
        item=None
    )


@bp.route("/<int:resultado_id>/editar", methods=["GET", "POST"])
@login_required
def editar(resultado_id):

    item = Resultado.query.get_or_404(resultado_id)

    if request.method == "POST":

        item.parametro = request.form.get("parametro")
        item.valor = request.form.get("valor")
        item.unidad = request.form.get("unidad")
        item.limite_min = request.form.get("limite_min") or None
        item.limite_max = request.form.get("limite_max") or None
        item.conforme = request.form.get("conforme") == "on"
        item.observaciones = request.form.get("observaciones")

        db.session.commit()

        flash("Resultado actualizado.", "success")

        return redirect(
            url_for(
                "resultados.index",
                muestra_ensayo_id=item.muestra_ensayo_id
            )
        )

    return render_template(
        "resultados/form.html",
        item=item,
        muestra_ensayo=item.muestra_ensayo
    )


@bp.route("/<int:resultado_id>/eliminar", methods=["POST"])
@login_required
def eliminar(resultado_id):

    item = Resultado.query.get_or_404(resultado_id)

    muestra_ensayo_id = item.muestra_ensayo_id

    db.session.delete(item)
    db.session.commit()

    flash("Resultado eliminado.", "warning")

    return redirect(
        url_for(
            "resultados.index",
            muestra_ensayo_id=muestra_ensayo_id
        )
    )