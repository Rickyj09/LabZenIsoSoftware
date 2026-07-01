"""unica version documental en preparacion

Revision ID: c3d8a1f42e76
Revises: b7a2e4c91d30
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "c3d8a1f42e76"
down_revision = "b7a2e4c91d30"
branch_labels = None
depends_on = None


def upgrade():
    # Conserva como preparación únicamente la versión activa más reciente.
    op.execute(sa.text("""
        WITH preparaciones AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY documento_id
                       ORDER BY id DESC
                   ) AS posicion
            FROM documento_versiones
            WHERE estado IN ('BORRADOR', 'EN_REVISION')
        )
        UPDATE documento_versiones AS dv
        SET estado = 'SUSTITUIDO',
            fecha_obsolescencia = COALESCE(dv.fecha_obsolescencia, NOW()),
            updated_at = NOW()
        FROM preparaciones AS p
        WHERE dv.id = p.id
          AND p.posicion > 1
    """))

    op.create_index(
        "uq_documento_version_preparacion_activa",
        "documento_versiones",
        ["documento_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('BORRADOR', 'EN_REVISION')"),
    )


def downgrade():
    op.drop_index(
        "uq_documento_version_preparacion_activa",
        table_name="documento_versiones",
    )
