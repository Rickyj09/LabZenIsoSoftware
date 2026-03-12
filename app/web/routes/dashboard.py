from flask import Blueprint, render_template
from flask_login import login_required, current_user

bp = Blueprint("dashboard", __name__, url_prefix="/")


@bp.route("/")
@login_required
def index():
    return render_template("dashboard/index.html", current_user=current_user)