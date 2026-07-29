import os
import json
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
    if int(config.get("ONLYOFFICE_CALLBACK_TOKEN_TTL_SECONDS", 0)) <= 0:
        raise RuntimeError("ONLYOFFICE_CALLBACK_TOKEN_TTL_SECONDS debe ser mayor que cero.")

    if config.get("ONLYOFFICE_EDIT_ENABLED"):
        edit_ttl = int(config.get("ONLYOFFICE_EDIT_LOCK_TTL_SECONDS", 0))
        heartbeat = int(config.get("ONLYOFFICE_EDIT_HEARTBEAT_SECONDS", 0))
        debounce = int(config.get("ONLYOFFICE_FORCE_SAVE_DEBOUNCE_SECONDS", 0))
        download_max = int(config.get("ONLYOFFICE_CALLBACK_DOWNLOAD_MAX_BYTES", 0))
        document_max = int(config.get("DOCUMENT_MAX_FILE_SIZE", 0))
        if edit_ttl <= 0:
            raise RuntimeError("ONLYOFFICE_EDIT_LOCK_TTL_SECONDS debe ser mayor que cero.")
        if heartbeat <= 0 or heartbeat >= edit_ttl:
            raise RuntimeError("ONLYOFFICE_EDIT_HEARTBEAT_SECONDS debe ser mayor que cero y menor que el TTL.")
        if debounce <= 0:
            raise RuntimeError("ONLYOFFICE_FORCE_SAVE_DEBOUNCE_SECONDS debe ser mayor que cero.")
        if download_max <= 0 or download_max > document_max:
            raise RuntimeError(
                "ONLYOFFICE_CALLBACK_DOWNLOAD_MAX_BYTES debe ser positivo y no superar DOCUMENT_MAX_FILE_SIZE."
            )

    if config.get("ONLYOFFICE_CONVERSION_ENABLED"):
        converter_path = (config.get("ONLYOFFICE_CONVERTER_PATH") or "").strip()
        if not converter_path.startswith("/") or "://" in converter_path or "\\" in converter_path or ".." in converter_path:
            raise RuntimeError("ONLYOFFICE_CONVERTER_PATH debe ser una ruta relativa absoluta segura, por ejemplo /converter.")
        source_ttl = int(config.get("ONLYOFFICE_CONVERSION_SOURCE_TOKEN_TTL_SECONDS", 0))
        request_timeout = int(config.get("ONLYOFFICE_CONVERSION_REQUEST_TIMEOUT_SECONDS", 0))
        poll_interval = int(config.get("ONLYOFFICE_CONVERSION_POLL_INTERVAL_SECONDS", 0))
        max_wait = int(config.get("ONLYOFFICE_CONVERSION_MAX_WAIT_SECONDS", 0))
        max_attempts = int(config.get("ONLYOFFICE_CONVERSION_MAX_ATTEMPTS", 0))
        backoff = int(config.get("ONLYOFFICE_CONVERSION_RETRY_BACKOFF_SECONDS", 0))
        download_max = int(config.get("ONLYOFFICE_CONVERSION_DOWNLOAD_MAX_BYTES", 0))
        pdf_max = int(config.get("ONLYOFFICE_PDF_MAX_BYTES", 0))
        if source_ttl <= 0 or request_timeout <= 0 or poll_interval <= 0 or max_wait <= 0:
            raise RuntimeError("Los tiempos de conversiÃ³n ONLYOFFICE deben ser mayores que cero.")
        if max_wait <= poll_interval:
            raise RuntimeError("ONLYOFFICE_CONVERSION_MAX_WAIT_SECONDS debe ser mayor al intervalo de polling.")
        if max_attempts <= 0 or max_attempts > 10:
            raise RuntimeError("ONLYOFFICE_CONVERSION_MAX_ATTEMPTS debe estar entre 1 y 10.")
        if backoff < 0:
            raise RuntimeError("ONLYOFFICE_CONVERSION_RETRY_BACKOFF_SECONDS no puede ser negativo.")
        if download_max <= 0 or pdf_max <= 0 or download_max > pdf_max:
            raise RuntimeError("Los limites de descarga/PDF deben ser positivos y consistentes.")


def _app_environment(config):
    return (config.get("APP_ENV") or os.getenv("FLASK_ENV") or "development").strip().lower()


def validate_document_signature_dev_config(config):
    if not config.get("DOCUMENT_SIGNATURES_DEV_TEST_MODE"):
        return

    environment = _app_environment(config)
    if environment not in {"development", "testing"} or config.get("ENV") == "production":
        import logging

        message = "DOCUMENT_SIGNATURES_DEV_TEST_MODE no puede habilitarse en produccion."
        logging.getLogger(__name__).warning(message)
        raise RuntimeError(message)

    password = (config.get("DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD") or "").strip()
    if not password:
        raise RuntimeError(
            "DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD es obligatorio cuando "
            "DOCUMENT_SIGNATURES_DEV_TEST_MODE=true."
        )


class Config:
    APP_ENV = os.getenv("FLASK_ENV", "development").lower()
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
    ONLYOFFICE_EDIT_ENABLED = _env_bool("ONLYOFFICE_EDIT_ENABLED", False)
    ONLYOFFICE_EDIT_LOCK_TTL_SECONDS = _env_int("ONLYOFFICE_EDIT_LOCK_TTL_SECONDS", 300)
    ONLYOFFICE_EDIT_HEARTBEAT_SECONDS = _env_int("ONLYOFFICE_EDIT_HEARTBEAT_SECONDS", 30)
    ONLYOFFICE_FORCE_SAVE_DEBOUNCE_SECONDS = _env_int("ONLYOFFICE_FORCE_SAVE_DEBOUNCE_SECONDS", 45)
    ONLYOFFICE_CALLBACK_TOKEN_TTL_SECONDS = _env_int("ONLYOFFICE_CALLBACK_TOKEN_TTL_SECONDS", 3600)
    ONLYOFFICE_CALLBACK_DOWNLOAD_MAX_BYTES = _env_int(
        "ONLYOFFICE_CALLBACK_DOWNLOAD_MAX_BYTES",
        min(DOCUMENT_MAX_FILE_SIZE, 25 * 1024 * 1024),
    )
    ONLYOFFICE_CONVERSION_ENABLED = _env_bool("ONLYOFFICE_CONVERSION_ENABLED", False)
    ONLYOFFICE_CONVERTER_PATH = os.getenv("ONLYOFFICE_CONVERTER_PATH", "/converter")
    ONLYOFFICE_CONVERSION_ASYNC = _env_bool("ONLYOFFICE_CONVERSION_ASYNC", True)
    ONLYOFFICE_CONVERSION_SOURCE_TOKEN_TTL_SECONDS = _env_int(
        "ONLYOFFICE_CONVERSION_SOURCE_TOKEN_TTL_SECONDS",
        600,
    )
    ONLYOFFICE_CONVERSION_REQUEST_TIMEOUT_SECONDS = _env_int(
        "ONLYOFFICE_CONVERSION_REQUEST_TIMEOUT_SECONDS",
        20,
    )
    ONLYOFFICE_CONVERSION_POLL_INTERVAL_SECONDS = _env_int(
        "ONLYOFFICE_CONVERSION_POLL_INTERVAL_SECONDS",
        2,
    )
    ONLYOFFICE_CONVERSION_MAX_WAIT_SECONDS = _env_int("ONLYOFFICE_CONVERSION_MAX_WAIT_SECONDS", 120)
    ONLYOFFICE_CONVERSION_MAX_ATTEMPTS = _env_int("ONLYOFFICE_CONVERSION_MAX_ATTEMPTS", 3)
    ONLYOFFICE_CONVERSION_RETRY_BACKOFF_SECONDS = _env_int(
        "ONLYOFFICE_CONVERSION_RETRY_BACKOFF_SECONDS",
        5,
    )
    ONLYOFFICE_CONVERSION_DOWNLOAD_MAX_BYTES = _env_int(
        "ONLYOFFICE_CONVERSION_DOWNLOAD_MAX_BYTES",
        50 * 1024 * 1024,
    )
    ONLYOFFICE_PDF_MAX_BYTES = _env_int("ONLYOFFICE_PDF_MAX_BYTES", 50 * 1024 * 1024)
    ONLYOFFICE_PDF_VALIDATE_PAGE_COUNT = _env_bool("ONLYOFFICE_PDF_VALIDATE_PAGE_COUNT", True)
    DOCUMENT_SIGNATURES_ENABLED = _env_bool("DOCUMENT_SIGNATURES_ENABLED", True)
    DOCUMENT_SIGNATURE_PROVIDER = os.getenv("DOCUMENT_SIGNATURE_PROVIDER", "external_controlled")
    DOCUMENT_SIGNATURE_VALIDATION_MODE = os.getenv("DOCUMENT_SIGNATURE_VALIDATION_MODE", "strict")
    DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH = os.getenv("DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH", "")
    DOCUMENT_SIGNATURE_ALLOWED_ISSUERS_PATH = os.getenv("DOCUMENT_SIGNATURE_ALLOWED_ISSUERS_PATH", "")
    DOCUMENT_SIGNATURE_TRUST_ROOTS_DIR = os.getenv("DOCUMENT_SIGNATURE_TRUST_ROOTS_DIR", "")
    DOCUMENT_SIGNATURES_DEV_TEST_MODE = _env_bool("DOCUMENT_SIGNATURES_DEV_TEST_MODE", False)
    DOCUMENT_SIGNATURES_DEV_CERT_DIR = os.getenv(
        "DOCUMENT_SIGNATURES_DEV_CERT_DIR",
        os.path.join("instance", "dev_signature_certificates"),
    )
    DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD = os.getenv("DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD", "")
    DOCUMENT_SIGNATURES_DEV_APPEARANCE_PAGE = os.getenv("DOCUMENT_SIGNATURES_DEV_APPEARANCE_PAGE", "last")
    DOCUMENT_SIGNATURES_DEV_LAYOUT_PROFILE = os.getenv("DOCUMENT_SIGNATURES_DEV_LAYOUT_PROFILE", "")
    DOCUMENT_SIGNATURES_DEV_ELABORADOR_BOX = os.getenv("DOCUMENT_SIGNATURES_DEV_ELABORADOR_BOX", "")
    DOCUMENT_SIGNATURES_DEV_REVISOR_BOX = os.getenv("DOCUMENT_SIGNATURES_DEV_REVISOR_BOX", "")
    DOCUMENT_SIGNATURES_DEV_APROBADOR_BOX = os.getenv("DOCUMENT_SIGNATURES_DEV_APROBADOR_BOX", "")
    DOCUMENT_SIGNATURE_PROCESS_TTL_DAYS = _env_int("DOCUMENT_SIGNATURE_PROCESS_TTL_DAYS", 15)
    DOCUMENT_SIGNATURE_MAX_PDF_BYTES = _env_int("DOCUMENT_SIGNATURE_MAX_PDF_BYTES", 50 * 1024 * 1024)
    DOCUMENT_SIGNATURE_TESTING_ACCEPT_MARKER = os.getenv("DOCUMENT_SIGNATURE_TESTING_ACCEPT_MARKER", "")
    DOCUMENT_SIGNATURE_REVOCATION_MODE = os.getenv("DOCUMENT_SIGNATURE_REVOCATION_MODE", "soft-fail")
    DOCUMENT_PUBLICATION_BASE_URL = os.getenv("DOCUMENT_PUBLICATION_BASE_URL", "")
    DOCUMENT_PUBLICATION_DEFAULT_ACCESS = os.getenv("DOCUMENT_PUBLICATION_DEFAULT_ACCESS", "AUTENTICADO")
    DOCUMENT_PUBLICATION_ALLOW_TEMPORARY_URLS = _env_bool("DOCUMENT_PUBLICATION_ALLOW_TEMPORARY_URLS", False)
    DOCUMENT_PUBLICATION_QR_PAGE = os.getenv("DOCUMENT_PUBLICATION_QR_PAGE", "first")
    DOCUMENT_PUBLICATION_QR_BOX = os.getenv("DOCUMENT_PUBLICATION_QR_BOX", "0.82,0.78,0.96,0.94")
    DOCUMENT_PUBLICATION_QR_LAYOUT_PROFILES = os.getenv(
        "DOCUMENT_PUBLICATION_QR_LAYOUT_PROFILES",
        json.dumps({
            "DEFAULT": {"page": "first", "box": "0.82,0.78,0.96,0.94"},
            "PROCEDIMIENTO": {"page": "first", "box": "0.905,0.78,0.995,0.91"},
        }),
    )
    DOCUMENT_PUBLICATION_QR_PROCEDIMIENTO_PAGE = os.getenv("DOCUMENT_PUBLICATION_QR_PROCEDIMIENTO_PAGE", "")
    DOCUMENT_PUBLICATION_QR_PROCEDIMIENTO_BOX = os.getenv("DOCUMENT_PUBLICATION_QR_PROCEDIMIENTO_BOX", "")
    DOCUMENT_DISTRIBUTION_EMAIL_ENABLED = _env_bool("DOCUMENT_DISTRIBUTION_EMAIL_ENABLED", False)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = _env_int("MAIL_PORT", 587)
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")
    MAIL_TIMEOUT = _env_int("MAIL_TIMEOUT", 20)

    # Opcional: mejora el comportamiento del engine
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }


class DevelopmentConfig(Config):
    APP_ENV = "development"
    DEBUG = True


class ProductionConfig(Config):
    APP_ENV = "production"
    DEBUG = False


class TestingConfig(Config):
    APP_ENV = "testing"
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
