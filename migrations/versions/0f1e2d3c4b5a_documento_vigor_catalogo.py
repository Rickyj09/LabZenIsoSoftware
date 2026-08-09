"""Catalogo de documentos y formatos en vigor

Revision ID: 0f1e2d3c4b5a
Revises: f2b3c4d5e6a7
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0f1e2d3c4b5a"
down_revision = "f2b3c4d5e6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documento_vigor_catalogo",
        sa.Column("tipo_listado", sa.String(length=20), nullable=False),
        sa.Column("clave_importacion", sa.String(length=255), nullable=False),
        sa.Column("identidad_estable", sa.String(length=255), nullable=False),
        sa.Column("ordinal_identidad", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=80), nullable=True),
        sa.Column("titulo", sa.String(length=500), nullable=True),
        sa.Column("revision", sa.String(length=50), nullable=True),
        sa.Column("fecha_vigencia", sa.Date(), nullable=True),
        sa.Column("custodio", sa.String(length=255), nullable=True),
        sa.Column("acceso_documento", sa.String(length=500), nullable=True),
        sa.Column("lugar_almacenamiento", sa.String(length=500), nullable=True),
        sa.Column("proteccion", sa.String(length=255), nullable=True),
        sa.Column("medio", sa.String(length=120), nullable=True),
        sa.Column("destino_final", sa.String(length=500), nullable=True),
        sa.Column("seccion", sa.String(length=255), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("documento_id", sa.BigInteger(), nullable=True),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=True),
        sa.Column("fuente_archivo", sa.String(length=255), nullable=False),
        sa.Column("fuente_hoja", sa.String(length=255), nullable=False),
        sa.Column("fuente_fila", sa.Integer(), nullable=False),
        sa.Column("importado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("importado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actualizado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("codigo IS NULL OR codigo <> ''", name="ck_documento_vigor_codigo_no_vacio"),
        sa.CheckConstraint("codigo IS NOT NULL OR titulo IS NOT NULL", name="ck_documento_vigor_codigo_o_titulo"),
        sa.CheckConstraint("ordinal_identidad > 0", name="ck_documento_vigor_ordinal_identidad_positivo"),
        sa.CheckConstraint("titulo IS NULL OR titulo <> ''", name="ck_documento_vigor_titulo_no_vacio"),
        sa.CheckConstraint(
            "tipo_listado IN ('INTERNO', 'EXTERNO', 'FORMATO')",
            name="ck_documento_vigor_tipo_listado_valido",
        ),
        sa.ForeignKeyConstraint(["actualizado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["importado_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "empresa_id",
            "tipo_listado",
            "clave_importacion",
            name="uq_documento_vigor_empresa_tipo_clave",
        ),
        sa.UniqueConstraint(
            "empresa_id",
            "tipo_listado",
            "identidad_estable",
            name="uq_documento_vigor_empresa_tipo_identidad",
        ),
    )
    op.create_index("ix_documento_vigor_documento_id", "documento_vigor_catalogo", ["documento_id"])
    op.create_index("ix_documento_vigor_documento_version_id", "documento_vigor_catalogo", ["documento_version_id"])
    op.create_index("ix_documento_vigor_empresa_codigo", "documento_vigor_catalogo", ["empresa_id", "codigo"])
    op.create_index("ix_documento_vigor_empresa_tipo", "documento_vigor_catalogo", ["empresa_id", "tipo_listado"])
    op.create_index(
        "ix_documento_vigor_empresa_tipo_identidad",
        "documento_vigor_catalogo",
        ["empresa_id", "tipo_listado", "identidad_estable"],
    )
    op.create_index(
        "ix_documento_vigor_empresa_tipo_activo",
        "documento_vigor_catalogo",
        ["empresa_id", "tipo_listado", "activo"],
    )
    op.create_index(op.f("ix_documento_vigor_catalogo_empresa_id"), "documento_vigor_catalogo", ["empresa_id"])


def downgrade():
    op.drop_index(op.f("ix_documento_vigor_catalogo_empresa_id"), table_name="documento_vigor_catalogo")
    op.drop_index("ix_documento_vigor_empresa_tipo_activo", table_name="documento_vigor_catalogo")
    op.execute("DROP INDEX IF EXISTS ix_documento_vigor_empresa_tipo_identidad")
    op.drop_index("ix_documento_vigor_empresa_tipo", table_name="documento_vigor_catalogo")
    op.drop_index("ix_documento_vigor_empresa_codigo", table_name="documento_vigor_catalogo")
    op.drop_index("ix_documento_vigor_documento_version_id", table_name="documento_vigor_catalogo")
    op.drop_index("ix_documento_vigor_documento_id", table_name="documento_vigor_catalogo")
    op.drop_table("documento_vigor_catalogo")
