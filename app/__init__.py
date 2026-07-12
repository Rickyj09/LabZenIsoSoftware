from flask import Flask
from flask_login import current_user

from app.config import get_config
from app.extensions import db, migrate, login_manager


def create_app(config_overrides=None):
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )

    app.config.from_object(get_config())
    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Importar modelos para que Flask-Migrate/Alembic los detecte
    from app import models  # noqa: F401

    # Registro de blueprints Flask
    register_blueprints(app)
    register_cli(app)
    register_template_context(app)

    return app


def register_template_context(app: Flask) -> None:
    from app.models.documentos import (
        clase_badge_estado_documental,
        etiqueta_estado_documental,
    )
    from app.security.permissions import current_user_can
    from app.services.document_pending_service import count_pending_documents_for_user

    @app.context_processor
    def document_security_context():
        def can(permission_code):
            return current_user_can(permission_code)

        pending_count = 0
        if (
            current_user.is_authenticated
            and current_user_can("documentos.ver_pendientes")
        ):
            pending_count = count_pending_documents_for_user(current_user)
        return {
            "can": can,
            "documental_pending_count": pending_count,
            "document_state_label": etiqueta_estado_documental,
            "document_state_badge_class": clase_badge_estado_documental,
        }


def register_cli(app: Flask) -> None:
    from app.cli.documentos import documentos_cli

    app.cli.add_command(documentos_cli)


def register_blueprints(app: Flask) -> None:
    from app.web.routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.web.routes.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.web.routes.clientes import bp as clientes_bp
    app.register_blueprint(clientes_bp)

    from app.web.routes.solicitudes import bp as solicitudes_bp
    app.register_blueprint(solicitudes_bp)

    from app.web.routes.muestras import bp as muestras_bp
    app.register_blueprint(muestras_bp)

    from app.web.routes.muestra_ensayos import bp as muestra_ensayos_bp
    app.register_blueprint(muestra_ensayos_bp)

    from app.web.routes.ensayos_catalogo import bp as ensayos_catalogo_bp
    app.register_blueprint(ensayos_catalogo_bp)

    from app.web.routes.metodos import bp as metodos_bp
    app.register_blueprint(metodos_bp)

    from app.web.routes.resultados import bp as resultados_bp
    app.register_blueprint(resultados_bp)

    from app.web.routes.organigrama import bp as organigrama_bp
    app.register_blueprint(organigrama_bp)

    from app.web.routes.politica_calidad import bp as politica_calidad_bp
    app.register_blueprint(politica_calidad_bp)

    from app.models.objetivos_calidad import ObjetivoCalidad, SeguimientoObjetivoCalidad

    from app.web.routes.objetivos_calidad import bp as objetivos_calidad_bp
    app.register_blueprint(objetivos_calidad_bp)

    from app.web.routes.mapa_procesos import bp as mapa_procesos_bp
    app.register_blueprint(mapa_procesos_bp)
    
    from app.web.routes.riesgos_oportunidades import bp as riesgos_oportunidades_bp
    app.register_blueprint(riesgos_oportunidades_bp)

    from app.web.routes.documentacion import bp as documentacion_bp
    app.register_blueprint(documentacion_bp)

    from app.web.routes.ofertas import bp as ofertas_bp
    app.register_blueprint(ofertas_bp)

    from app.web.routes.contratos import bp as contratos_bp
    app.register_blueprint(contratos_bp)
   
    
