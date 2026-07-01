import os
from dotenv import load_dotenv

load_dotenv(override=True)

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
