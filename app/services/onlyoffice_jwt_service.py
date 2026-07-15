from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from flask import current_app


class OnlyOfficeTokenError(ValueError):
    pass


def _jwt_settings():
    return {
        "secret": current_app.config["ONLYOFFICE_JWT_SECRET"],
        "issuer": current_app.config["ONLYOFFICE_PING_JWT_ISSUER"],
        "audience": current_app.config["ONLYOFFICE_PING_JWT_AUDIENCE"],
        "ttl": int(current_app.config["ONLYOFFICE_PING_TOKEN_TTL_SECONDS"]),
    }


def _document_jwt_settings():
    return {
        "secret": current_app.config["ONLYOFFICE_JWT_SECRET"],
        "issuer": current_app.config["ONLYOFFICE_PING_JWT_ISSUER"],
        "audience": "labzeniso-onlyoffice-document-view",
        "ttl": int(current_app.config["ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS"]),
    }


def _callback_jwt_settings():
    return {
        "secret": current_app.config["ONLYOFFICE_JWT_SECRET"],
        "issuer": current_app.config["ONLYOFFICE_PING_JWT_ISSUER"],
        "audience": "labzeniso-onlyoffice-document-callback",
        "ttl": int(current_app.config["ONLYOFFICE_CALLBACK_TOKEN_TTL_SECONDS"]),
    }


def generate_onlyoffice_ping_token():
    settings = _jwt_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings["issuer"],
        "aud": settings["audience"],
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=settings["ttl"]),
        "jti": uuid4().hex,
        "scope": "onlyoffice:ping",
    }
    return jwt.encode(payload, settings["secret"], algorithm="HS256")


def validate_onlyoffice_ping_token(token):
    if not token:
        raise OnlyOfficeTokenError("Token JWT ausente.")

    settings = _jwt_settings()
    try:
        payload = jwt.decode(
            token,
            settings["secret"],
            algorithms=["HS256"],
            audience=settings["audience"],
            issuer=settings["issuer"],
        )
    except jwt.ExpiredSignatureError as exc:
        raise OnlyOfficeTokenError("Token JWT vencido.") from exc
    except jwt.InvalidTokenError as exc:
        raise OnlyOfficeTokenError("Token JWT inválido.") from exc

    if payload.get("scope") != "onlyoffice:ping":
        raise OnlyOfficeTokenError("Token JWT sin alcance de conectividad.")
    return payload


def generate_onlyoffice_document_token(*, empresa_id, documento_id, version_id, archivo_sha256):
    settings = _document_jwt_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings["issuer"],
        "aud": settings["audience"],
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=settings["ttl"]),
        "jti": uuid4().hex,
        "scope": "onlyoffice:document:view",
        "empresa_id": int(empresa_id),
        "documento_id": int(documento_id),
        "version_id": int(version_id),
        "archivo_sha256": archivo_sha256,
    }
    return jwt.encode(payload, settings["secret"], algorithm="HS256")


def validate_onlyoffice_document_token(token):
    if not token:
        raise OnlyOfficeTokenError("Token JWT ausente.")

    settings = _document_jwt_settings()
    try:
        payload = jwt.decode(
            token,
            settings["secret"],
            algorithms=["HS256"],
            audience=settings["audience"],
            issuer=settings["issuer"],
        )
    except jwt.ExpiredSignatureError as exc:
        raise OnlyOfficeTokenError("Token JWT vencido.") from exc
    except jwt.InvalidTokenError as exc:
        raise OnlyOfficeTokenError("Token JWT inválido.") from exc

    if payload.get("scope") != "onlyoffice:document:view":
        raise OnlyOfficeTokenError("Token JWT sin alcance de visualización documental.")
    return payload


def generate_onlyoffice_callback_token(*, public_id, editor_key):
    settings = _callback_jwt_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings["issuer"],
        "aud": settings["audience"],
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=settings["ttl"]),
        "jti": uuid4().hex,
        "scope": "onlyoffice:document:callback",
        "public_id": public_id,
        "editor_key": editor_key,
    }
    return jwt.encode(payload, settings["secret"], algorithm="HS256")


def validate_onlyoffice_callback_token(token):
    if not token:
        raise OnlyOfficeTokenError("Token JWT ausente.")

    settings = _callback_jwt_settings()
    try:
        payload = jwt.decode(
            token,
            settings["secret"],
            algorithms=["HS256"],
            audience=settings["audience"],
            issuer=settings["issuer"],
        )
    except jwt.ExpiredSignatureError as exc:
        raise OnlyOfficeTokenError("Token JWT vencido.") from exc
    except jwt.InvalidTokenError as exc:
        raise OnlyOfficeTokenError("Token JWT invÃ¡lido.") from exc

    if payload.get("scope") != "onlyoffice:document:callback":
        raise OnlyOfficeTokenError("Token JWT sin alcance de callback documental.")
    return payload


def sign_onlyoffice_config(config):
    return jwt.encode(config, current_app.config["ONLYOFFICE_JWT_SECRET"], algorithm="HS256")
