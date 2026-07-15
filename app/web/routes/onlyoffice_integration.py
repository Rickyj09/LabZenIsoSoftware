from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_file
from flask_login import login_required

from app.models.documentos import Documento, DocumentoVersion
from app.security.permissions import require_permission
from app.services.onlyoffice_document_view_service import (
    DOCX_MIME,
    is_docx_version,
    resolve_viewable_docx_path,
)
from app.services.onlyoffice_health_service import OnlyOfficeHealthService
from app.services.onlyoffice_jwt_service import (
    OnlyOfficeTokenError,
    generate_onlyoffice_ping_token,
    validate_onlyoffice_document_token,
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


@bp.route("/versiones/<int:version_id>/archivo", methods=["GET"])
def document_file(version_id):
    try:
        payload = validate_onlyoffice_document_token(request.args.get("token", ""))
    except OnlyOfficeTokenError:
        abort(401)

    if int(payload.get("version_id", 0)) != int(version_id):
        abort(401)

    version = (
        DocumentoVersion.query
        .join(Documento, DocumentoVersion.documento_id == Documento.id)
        .filter(
            DocumentoVersion.id == int(payload["version_id"]),
            DocumentoVersion.documento_id == int(payload["documento_id"]),
            DocumentoVersion.empresa_id == int(payload["empresa_id"]),
            Documento.id == int(payload["documento_id"]),
            Documento.empresa_id == int(payload["empresa_id"]),
        )
        .first()
    )
    if not version:
        abort(404)
    if version.archivo_sha256 != payload.get("archivo_sha256"):
        abort(401)
    if not is_docx_version(version):
        abort(422)

    try:
        physical_path = resolve_viewable_docx_path(version)
    except FileNotFoundError:
        abort(404)
    except ValueError:
        abort(422)

    response = send_file(
        physical_path,
        as_attachment=False,
        download_name=version.archivo_nombre_original or "documento.docx",
        mimetype=version.archivo_mime or DOCX_MIME,
        conditional=True,
    )
    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if version.archivo_size:
        response.headers["Content-Length"] = str(version.archivo_size)
    return response
