"""Clasificacion de control documental

Revision ID: 1a2b3c4d5e6f
Revises: 0f1e2d3c4b5a
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e6f"
down_revision = "0f1e2d3c4b5a"
branch_labels = None
depends_on = None


DOCUMENTO_EVENTOS_ACCIONES_ANTERIORES = (
    "'CREAR_VERSION', 'ENVIAR_REVISION', 'DAR_CONFORMIDAD', 'APROBAR', "
    "'RECHAZAR', 'SOLICITAR_CORRECCIONES', 'RECHAZAR_APROBACION', "
    "'DEVOLVER_BORRADOR', 'OBSOLETAR', 'SUSTITUIR_VERSION', "
    "'PUBLICAR_VIGENTE', 'VERSION_ANTERIOR_OBSOLETA', 'PUBLICACION_PREPARADA', "
    "'QR_GENERADO', 'PDF_QR_GENERADO', 'DISTRIBUCION_ENCOLADA', "
    "'PUBLICACION_CONSULTADA', 'PDF_VIGENTE_DESCARGADO', 'PUBLICACION_REVOCADA'"
)

DOCUMENTO_EVENTOS_ACCIONES_NUEVAS = (
    DOCUMENTO_EVENTOS_ACCIONES_ANTERIORES + ", 'CLASIFICAR_CONTROL'"
)


def _replace_event_action_constraint(actions):
    op.drop_constraint(
        "ck_documento_eventos_accion_valida",
        "documento_aprobaciones",
        type_="check",
    )
    op.create_check_constraint(
        "ck_documento_eventos_accion_valida",
        "documento_aprobaciones",
        f"accion IN ({actions})",
    )


def upgrade():
    op.add_column(
        "documentos",
        sa.Column("clasificacion_control", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_documentos_clasificacion_control_valida",
        "documentos",
        "clasificacion_control IS NULL OR clasificacion_control IN ('INTERNO', 'FORMATO')",
    )
    _replace_event_action_constraint(DOCUMENTO_EVENTOS_ACCIONES_NUEVAS)


def downgrade():
    _replace_event_action_constraint(DOCUMENTO_EVENTOS_ACCIONES_ANTERIORES)
    op.drop_constraint(
        "ck_documentos_clasificacion_control_valida",
        "documentos",
        type_="check",
    )
    op.drop_column("documentos", "clasificacion_control")
