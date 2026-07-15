import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv(override=True)


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un entero válido.") from exc


def _env_list(name, default):
    value = os.getenv(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def validate_onlyoffice_config(config):
    if not config.get("ONLYOFFICE_ENABLED"):
        return

    required_url_keys = (
        "ONLYOFFICE_PUBLIC_URL",
        "ONLYOFFICE_INTERNAL_URL",
        "ONLYOFFICE_CALLBACK_BASE_URL",
    )
    for key in required_url_keys:
        value = (config.get(key) or "").strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"{key} debe ser una URL absoluta http(s) válida.")

    secret = (config.get("ONLYOFFICE_JWT_SECRET") or "").strip()
    if not secret or secret == "change-this-in-local-env":
        raise RuntimeError(
            "ONLYOFFICE_JWT_SECRET es obligatorio y no puede usar el valor de ejemplo "
            "cuando ONLYOFFICE_ENABLED=true."
        )

    if int(config.get("ONLYOFFICE_REQUEST_TIMEOUT_SECONDS", 0)) <= 0:
        raise RuntimeError("ONLYOFFICE_REQUEST_TIMEOUT_SECONDS debe ser mayor que cero.")
    if int(config.get("ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS", 0)) <= 0:
        raise RuntimeError("ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS debe ser mayor que cero.")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "labzeniso-dev-secret-key")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:1234@localhost:5432/labzeniso"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Los documentos controlados se almacenan fuera de /static para que toda
    # lectura pase por una ruta autenticada y validada por empresa.
    DOCUMENT_STORAGE_ROOT = os.getenv(
        "DOCUMENT_STORAGE_ROOT",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage", "documentos"))
    )
    DOCUMENT_LEGACY_STORAGE_ROOT = os.getenv(
        "DOCUMENT_LEGACY_STORAGE_ROOT",
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "web", "static", "uploads", "documentos")
        )
    )
    DOCUMENT_MAX_FILE_SIZE = int(os.getenv("DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", DOCUMENT_MAX_FILE_SIZE))

    ONLYOFFICE_ENABLED = _env_bool("ONLYOFFICE_ENABLED", False)
    ONLYOFFICE_PUBLIC_URL = os.getenv("ONLYOFFICE_PUBLIC_URL", "http://localhost:8082")
    ONLYOFFICE_INTERNAL_URL = os.getenv("ONLYOFFICE_INTERNAL_URL", "http://localhost:8082")
    ONLYOFFICE_CALLBACK_BASE_URL = os.getenv(
        "ONLYOFFICE_CALLBACK_BASE_URL",
        "http://host.docker.internal:5000",
    )
    ONLYOFFICE_JWT_SECRET = os.getenv("ONLYOFFICE_JWT_SECRET", "")
    ONLYOFFICE_VERIFY_SSL = _env_bool("ONLYOFFICE_VERIFY_SSL", False)
    ONLYOFFICE_REQUEST_TIMEOUT_SECONDS = _env_int("ONLYOFFICE_REQUEST_TIMEOUT_SECONDS", 10)
    ONLYOFFICE_ALLOWED_HOSTS = _env_list(
        "ONLYOFFICE_ALLOWED_HOSTS",
        ("localhost", "127.0.0.1", "host.docker.internal"),
    )
    ONLYOFFICE_HEALTHCHECK_PATH = os.getenv("ONLYOFFICE_HEALTHCHECK_PATH", "/healthcheck")
    ONLYOFFICE_PING_JWT_AUDIENCE = os.getenv(
        "ONLYOFFICE_PING_JWT_AUDIENCE",
        "labzeniso-onlyoffice-ping",
    )
    ONLYOFFICE_PING_JWT_ISSUER = os.getenv(
        "ONLYOFFICE_PING_JWT_ISSUER",
        "labzeniso",
    )
    ONLYOFFICE_PING_TOKEN_TTL_SECONDS = _env_int("ONLYOFFICE_PING_TOKEN_TTL_SECONDS", 120)
    ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS = _env_int("ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS", 300)

    # Opcional: mejora el comportamiento del engine
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://postgres:1234@localhost:5432/labzeniso"
    )


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    return config_by_name.get(env, DevelopmentConfig)
