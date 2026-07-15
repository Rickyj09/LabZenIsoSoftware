from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required

from app.security.permissions import require_permission
from app.services.onlyoffice_health_service import OnlyOfficeHealthService
from app.services.onlyoffice_jwt_service import (
    OnlyOfficeTokenError,
    generate_onlyoffice_ping_token,
    validate_onlyoffice_ping_token,
)


bp = Blueprint(
    "onlyoffice_integration",
    __name__,
    url_prefix="/documentacion/integraciones/onlyoffice",
)

MAX_PING_CONTENT_LENGTH = 4096


def _onlyoffice_public_config():
    return {
        "enabled": bool(current_app.config["ONLYOFFICE_ENABLED"]),
        "public_url": current_app.config["ONLYOFFICE_PUBLIC_URL"],
        "internal_url": current_app.config["ONLYOFFICE_INTERNAL_URL"],
        "callback_base_url": current_app.config["ONLYOFFICE_CALLBACK_BASE_URL"],
        "healthcheck_path": current_app.config["ONLYOFFICE_HEALTHCHECK_PATH"],
        "verify_ssl": bool(current_app.config["ONLYOFFICE_VERIFY_SSL"]),
        "timeout_seconds": int(current_app.config["ONLYOFFICE_REQUEST_TIMEOUT_SECONDS"]),
        "allowed_hosts": list(current_app.config["ONLYOFFICE_ALLOWED_HOSTS"]),
    }


@bp.route("/", methods=["GET"])
@login_required
@require_permission("documentos.ver_historial")
def diagnostico():
    health = OnlyOfficeHealthService().check().to_dict()
    ping_token = generate_onlyoffice_ping_token() if current_app.config["ONLYOFFICE_ENABLED"] else None
    return render_template(
        "documentacion/onlyoffice_diagnostico.html",
        onlyoffice=_onlyoffice_public_config(),
        health=health,
        ping_token=ping_token,
    )


@bp.route("/health", methods=["GET"])
@login_required
@require_permission("documentos.ver_historial")
def health():
    return jsonify(OnlyOfficeHealthService().check().to_dict())


@bp.route("/ping", methods=["POST"])
def ping():
    if not current_app.config["ONLYOFFICE_ENABLED"]:
        return jsonify({
            "ok": False,
            "message": "Integración ONLYOFFICE deshabilitada",
        }), 404

    if request.content_length and request.content_length > MAX_PING_CONTENT_LENGTH:
        return jsonify({
            "ok": False,
            "message": "Payload demasiado grande para ping de conectividad.",
        }), 413

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        json_payload = request.get_json(silent=True) or {}
        token = (json_payload.get("token") or "").strip()

    try:
        payload = validate_onlyoffice_ping_token(token)
    except OnlyOfficeTokenError as exc:
        return jsonify({
            "ok": False,
            "message": str(exc),
        }), 401

    return jsonify({
        "ok": True,
        "message": "Ping ONLYOFFICE recibido por LabZenISO",
        "scope": payload.get("scope"),
    })
