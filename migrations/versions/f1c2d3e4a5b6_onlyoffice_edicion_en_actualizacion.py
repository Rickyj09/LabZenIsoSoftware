"""permitir edicion onlyoffice en actualizacion

Revision ID: f1c2d3e4a5b6
Revises: e5a7c9d2f4b1
Create Date: 2026-07-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f1c2d3e4a5b6"
down_revision = "e5a7c9d2f4b1"
branch_labels = None
depends_on = None


DOCUMENTOS_ESTADOS = "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')"
VERSIONES_ESTADOS = (
    "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')"
)
DOCUMENTOS_ESTADOS_ANTERIOR = "estado IN ('EN_ELABORACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')"
VERSIONES_ESTADOS_ANTERIOR = (
    "estado IN ('EN_ELABORACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')"
)


def upgrade():
    op.drop_index("uq_documento_version_preparacion_activa", table_name="documento_versiones")
    with op.batch_alter_table("documento_versiones") as batch:
        batch.drop_constraint("ck_documento_versiones_estado_valido", type_="check")
        batch.create_check_constraint("ck_documento_versiones_estado_valido", VERSIONES_ESTADOS)
    with op.batch_alter_table("documentos") as batch:
        batch.drop_constraint("ck_documentos_estado_valido", type_="check")
        batch.create_check_constraint("ck_documentos_estado_valido", DOCUMENTOS_ESTADOS)
    op.create_index(
        "uq_documento_version_preparacion_activa",
        "documento_versiones",
        ["documento_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION')"),
        sqlite_where=sa.text("estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION')"),
    )


def downgrade():
    op.drop_index("uq_documento_version_preparacion_activa", table_name="documento_versiones")
    op.execute("UPDATE documento_versiones SET estado = 'EN_ELABORACION' WHERE estado = 'EN_ACTUALIZACION'")
    op.execute("UPDATE documentos SET estado = 'EN_ELABORACION' WHERE estado = 'EN_ACTUALIZACION'")
    with op.batch_alter_table("documento_versiones") as batch:
        batch.drop_constraint("ck_documento_versiones_estado_valido", type_="check")
        batch.create_check_constraint("ck_documento_versiones_estado_valido", VERSIONES_ESTADOS_ANTERIOR)
    with op.batch_alter_table("documentos") as batch:
        batch.drop_constraint("ck_documentos_estado_valido", type_="check")
        batch.create_check_constraint("ck_documentos_estado_valido", DOCUMENTOS_ESTADOS_ANTERIOR)
    op.create_index(
        "uq_documento_version_preparacion_activa",
        "documento_versiones",
        ["documento_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('EN_ELABORACION', 'EN_REVISION')"),
        sqlite_where=sa.text("estado IN ('EN_ELABORACION', 'EN_REVISION')"),
    )
