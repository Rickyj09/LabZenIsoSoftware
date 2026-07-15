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
