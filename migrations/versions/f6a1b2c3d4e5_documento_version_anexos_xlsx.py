"""Documento version anexos XLSX

Revision ID: f6a1b2c3d4e5
Revises: a2b3c4d5e6f7
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a1b2c3d4e5"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documento_version_anexos",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre_visible", sa.String(length=255), nullable=False),
        sa.Column("archivo_nombre_original", sa.String(length=255), nullable=False),
        sa.Column("archivo_nombre_guardado", sa.String(length=255), nullable=False),
        sa.Column("archivo_storage_path", sa.String(length=500), nullable=False),
        sa.Column("archivo_mime", sa.String(length=255), nullable=False),
        sa.Column("archivo_size", sa.BigInteger(), nullable=False),
        sa.Column("archivo_sha256", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("creado_por_id", sa.BigInteger(), nullable=False),
        sa.Column("actualizado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("aprobado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("aprobado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eliminado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("eliminado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inmutable", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("archivo_sha256 IS NULL OR length(archivo_sha256) = 64", name="ck_documento_version_anexos_sha256_valido"),
        sa.CheckConstraint("archivo_size IS NULL OR archivo_size > 0", name="ck_documento_version_anexos_size_positivo"),
        sa.CheckConstraint("estado IN ('ACTIVO', 'APROBADO', 'ELIMINADO')", name="ck_documento_version_anexos_estado_valido"),
        sa.CheckConstraint("tipo IN ('XLSX')", name="ck_documento_version_anexos_tipo_valido"),
        sa.ForeignKeyConstraint(["actualizado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["aprobado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["eliminado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_documento_version_anexos_public_id"),
    )
    op.create_index(op.f("ix_documento_version_anexos_empresa_id"), "documento_version_anexos", ["empresa_id"], unique=False)
    op.create_index("ix_documento_version_anexos_archivo_sha256", "documento_version_anexos", ["archivo_sha256"], unique=False)
    op.create_index("ix_documento_version_anexos_documento_id", "documento_version_anexos", ["documento_id"], unique=False)
    op.create_index("ix_documento_version_anexos_documento_version_id", "documento_version_anexos", ["documento_version_id"], unique=False)
    op.create_index("ix_documento_version_anexos_estado", "documento_version_anexos", ["estado"], unique=False)
    op.add_column("documento_ediciones", sa.Column("documento_version_anexo_id", sa.BigInteger(), nullable=True))
    op.drop_index("uq_documento_ediciones_version_activa", table_name="documento_ediciones")
    op.create_foreign_key(
        "fk_documento_ediciones_documento_version_anexo_id",
        "documento_ediciones",
        "documento_version_anexos",
        ["documento_version_anexo_id"],
        ["id"],
    )
    op.create_index(
        "ix_documento_ediciones_documento_version_anexo_id",
        "documento_ediciones",
        ["documento_version_anexo_id"],
        unique=False,
    )
    op.create_index(
        "uq_documento_ediciones_version_activa",
        "documento_ediciones",
        ["documento_version_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'ACTIVA' AND documento_version_anexo_id IS NULL"),
        sqlite_where=sa.text("estado = 'ACTIVA' AND documento_version_anexo_id IS NULL"),
    )
    op.create_index(
        "uq_documento_ediciones_anexo_activa",
        "documento_ediciones",
        ["documento_version_anexo_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'ACTIVA' AND documento_version_anexo_id IS NOT NULL"),
        sqlite_where=sa.text("estado = 'ACTIVA' AND documento_version_anexo_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_documento_ediciones_anexo_activa", table_name="documento_ediciones")
    op.drop_index("uq_documento_ediciones_version_activa", table_name="documento_ediciones")
    op.create_index(
        "uq_documento_ediciones_version_activa",
        "documento_ediciones",
        ["documento_version_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'ACTIVA'"),
        sqlite_where=sa.text("estado = 'ACTIVA'"),
    )
    op.drop_index("ix_documento_ediciones_documento_version_anexo_id", table_name="documento_ediciones")
    op.drop_constraint("fk_documento_ediciones_documento_version_anexo_id", "documento_ediciones", type_="foreignkey")
    op.drop_column("documento_ediciones", "documento_version_anexo_id")
    op.drop_index("ix_documento_version_anexos_estado", table_name="documento_version_anexos")
    op.drop_index("ix_documento_version_anexos_documento_version_id", table_name="documento_version_anexos")
    op.drop_index("ix_documento_version_anexos_documento_id", table_name="documento_version_anexos")
    op.drop_index("ix_documento_version_anexos_archivo_sha256", table_name="documento_version_anexos")
    op.drop_index(op.f("ix_documento_version_anexos_empresa_id"), table_name="documento_version_anexos")
    op.drop_table("documento_version_anexos")
