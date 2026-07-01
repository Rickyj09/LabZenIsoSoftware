"""agregar metadatos storage documental

Revision ID: 8f3c2d1a9b70
Revises: d1ed21cdfc92
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "8f3c2d1a9b70"
down_revision = "d1ed21cdfc92"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documento_versiones", schema=None) as batch_op:
        batch_op.add_column(sa.Column("archivo_nombre_original", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("archivo_nombre_guardado", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("archivo_storage_path", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("archivo_mime", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("archivo_size", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("archivo_sha256", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("documento_versiones", schema=None) as batch_op:
        batch_op.drop_column("archivo_sha256")
        batch_op.drop_column("archivo_size")
        batch_op.drop_column("archivo_mime")
        batch_op.drop_column("archivo_storage_path")
        batch_op.drop_column("archivo_nombre_guardado")
        batch_op.drop_column("archivo_nombre_original")
