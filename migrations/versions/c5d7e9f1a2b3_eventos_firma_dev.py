"""eventos firma dev

Revision ID: c5d7e9f1a2b3
Revises: b4e6f8a1c9d0
Create Date: 2026-07-20
"""
from alembic import op


revision = "c5d7e9f1a2b3"
down_revision = "b4e6f8a1c9d0"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_documento_firma_eventos_tipo_valido"
BASE_EVENTS = (
    "PROCESO_CREADO",
    "PASO_HABILITADO",
    "PDF_DESCARGADO",
    "PDF_SUBIDO",
    "VALIDACION_OK",
    "VALIDACION_ERROR",
    "PASO_FIRMADO",
    "PROCESO_COMPLETADO",
    "RECHAZADO",
    "CANCELADO",
    "VENCIDO",
    "ERROR",
)
DEV_EVENTS = (
    "DEV_TEST_SIGNATURE_REQUESTED",
    "DEV_TEST_SIGNATURE_VALIDATED",
    "DEV_TEST_SIGNATURE_REJECTED",
)


def _check_sql(events):
    values = ", ".join(f"'{event}'" for event in events)
    return f"tipo_evento IN ({values})"


def _replace_constraint(events):
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("documento_firma_eventos") as batch:
            batch.drop_constraint(CONSTRAINT_NAME, type_="check")
            batch.create_check_constraint(CONSTRAINT_NAME, _check_sql(events))
        return
    op.drop_constraint(CONSTRAINT_NAME, "documento_firma_eventos", type_="check")
    op.create_check_constraint(CONSTRAINT_NAME, "documento_firma_eventos", _check_sql(events))


def upgrade():
    _replace_constraint((*BASE_EVENTS, *DEV_EVENTS))


def downgrade():
    _replace_constraint(BASE_EVENTS)
