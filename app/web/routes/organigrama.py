from flask import Blueprint, render_template
from flask_login import current_user, login_required
from app.models.organigrama import Personal

bp = Blueprint("organigrama", __name__, url_prefix="/organigrama")

@bp.route("/")
@login_required
def index():
    personal = Personal.query.filter_by(empresa_id=current_user.empresa_id).all()
    return render_template("organigrama/index.html", personal=personal)
