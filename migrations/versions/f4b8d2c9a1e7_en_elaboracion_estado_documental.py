"""Renombrar estado documental BORRADOR a EN_ELABORACION.

Revision ID: f4b8d2c9a1e7
Revises: e8a4c7d91f20
Create Date: 2026-07-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f4b8d2c9a1e7"
down_revision = "e8a4c7d91f20"
branch_labels = None
depends_on = None


DOCUMENTOS_ESTADOS = "estado IN ('EN_ELABORACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')"
VERSIONES_ESTADOS = (
    "estado IN ('EN_ELABORACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')"
)
DOCUMENTOS_ESTADOS_ANTERIOR = "estado IN ('BORRADOR', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')"
VERSIONES_ESTADOS_ANTERIOR = (
    "estado IN ('BORRADOR', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')"
)


def upgrade():
    op.drop_index("uq_documento_version_preparacion_activa", table_name="documento_versiones")
    op.drop_constraint("ck_documento_versiones_estado_valido", "documento_versiones", type_="check")
    op.drop_constraint("ck_documentos_estado_valido", "documentos", type_="check")

    op.execute("UPDATE documento_versiones SET estado = 'EN_ELABORACION' WHERE estado = 'BORRADOR'")
    op.execute("UPDATE documentos SET estado = 'EN_ELABORACION' WHERE estado = 'BORRADOR'")
    op.execute(
        "UPDATE documento_aprobaciones SET estado_anterior = 'EN_ELABORACION' "
        "WHERE estado_anterior = 'BORRADOR'"
    )
    op.execute(
        "UPDATE documento_aprobaciones SET estado_nuevo = 'EN_ELABORACION' "
        "WHERE estado_nuevo = 'BORRADOR'"
    )

    op.create_check_constraint("ck_documentos_estado_valido", "documentos", DOCUMENTOS_ESTADOS)
    op.create_check_constraint("ck_documento_versiones_estado_valido", "documento_versiones", VERSIONES_ESTADOS)
    op.create_index(
        "uq_documento_version_preparacion_activa",
        "documento_versiones",
        ["documento_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('EN_ELABORACION', 'EN_REVISION')"),
        sqlite_where=sa.text("estado IN ('EN_ELABORACION', 'EN_REVISION')"),
    )


def downgrade():
    op.drop_index("uq_documento_version_preparacion_activa", table_name="documento_versiones")
    op.drop_constraint("ck_documento_versiones_estado_valido", "documento_versiones", type_="check")
    op.drop_constraint("ck_documentos_estado_valido", "documentos", type_="check")

    op.execute("UPDATE documento_versiones SET estado = 'BORRADOR' WHERE estado = 'EN_ELABORACION'")
    op.execute("UPDATE documentos SET estado = 'BORRADOR' WHERE estado = 'EN_ELABORACION'")
    op.execute(
        "UPDATE documento_aprobaciones SET estado_anterior = 'BORRADOR' "
        "WHERE estado_anterior = 'EN_ELABORACION'"
    )
    op.execute(
        "UPDATE documento_aprobaciones SET estado_nuevo = 'BORRADOR' "
        "WHERE estado_nuevo = 'EN_ELABORACION'"
    )

    op.create_check_constraint("ck_documentos_estado_valido", "documentos", DOCUMENTOS_ESTADOS_ANTERIOR)
    op.create_check_constraint(
        "ck_documento_versiones_estado_valido",
        "documento_versiones",
        VERSIONES_ESTADOS_ANTERIOR,
    )
    op.create_index(
        "uq_documento_version_preparacion_activa",
        "documento_versiones",
        ["documento_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('BORRADOR', 'EN_REVISION')"),
        sqlite_where=sa.text("estado IN ('BORRADOR', 'EN_REVISION')"),
    )
