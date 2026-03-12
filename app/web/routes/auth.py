from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required

from app.models.seguridad import Usuario

bp = Blueprint("web_auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Usuario y contraseña son obligatorios.", "warning")
            return redirect(url_for("web_auth.login"))

        usuario = Usuario.query.filter_by(username=username, activo=True).first()

        if not usuario or not usuario.check_password(password):
            flash("Credenciales inválidas.", "danger")
            return redirect(url_for("web_auth.login"))

        login_user(usuario)
        flash("Bienvenido al sistema.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("web_auth.login"))