from flask import Blueprint, render_template
from flask_login import login_required
from app.models.organigrama import Personal

bp = Blueprint("organigrama", __name__, url_prefix="/organigrama")

@bp.route("/")
@login_required
def index():
    personal = Personal.query.all()
    return render_template("organigrama/index.html", personal=personal)