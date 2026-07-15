"""documento snapshots workflow

Revision ID: b9f2d4c8a6e1
Revises: a7c9e4d2f6b1
Create Date: 2026-07-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b9f2d4c8a6e1"
down_revision = "a7c9e4d2f6b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documento_snapshots",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("secuencia", sa.Integer(), nullable=False),
        sa.Column("ciclo_revision", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=True),
        sa.Column("archivo_nombre_interno", sa.String(length=255), nullable=True),
        sa.Column("archivo_nombre_original", sa.String(length=255), nullable=True),
        sa.Column("archivo_mime", sa.String(length=255), nullable=True),
        sa.Column("archivo_size", sa.BigInteger(), nullable=True),
        sa.Column("archivo_sha256", sa.String(length=64), nullable=True),
        sa.Column("hash_origen", sa.String(length=64), nullable=True),
        sa.Column("creado_por_id", sa.BigInteger(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workflow_evento_id", sa.BigInteger(), nullable=True),
        sa.Column("snapshot_origen_id", sa.BigInteger(), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("resumen_cambios", sa.Text(), nullable=True),
        sa.Column("hojas_modificadas", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("inmutable", sa.Boolean(), nullable=False),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.CheckConstraint("archivo_sha256 IS NULL OR length(archivo_sha256) = 64", name="ck_documento_snapshots_sha256_valido"),
        sa.CheckConstraint("archivo_size IS NULL OR archivo_size > 0", name="ck_documento_snapshots_size_positivo"),
        sa.CheckConstraint("ciclo_revision > 0", name="ck_documento_snapshots_ciclo_positivo"),
        sa.CheckConstraint("estado <> 'DISPONIBLE' OR inmutable = true", name="ck_documento_snapshots_disponible_inmutable"),
        sa.CheckConstraint("estado IN ('CREANDO', 'DISPONIBLE', 'ERROR', 'INVALIDADO')", name="ck_documento_snapshots_estado_valido"),
        sa.CheckConstraint("hash_origen IS NULL OR length(hash_origen) = 64", name="ck_documento_snapshots_hash_origen_valido"),
        sa.CheckConstraint("secuencia > 0", name="ck_documento_snapshots_secuencia_positiva"),
        sa.CheckConstraint("tipo IN ('ENVIO_REVISION', 'APROBADO', 'RECHAZADO')", name="ck_documento_snapshots_tipo_valido"),
        sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["snapshot_origen_id"], ["documento_snapshots.id"]),
        sa.ForeignKeyConstraint(["workflow_evento_id"], ["documento_aprobaciones.id"]),
        sa.UniqueConstraint("documento_version_id", "secuencia", name="uq_documento_snapshots_version_secuencia"),
        sa.UniqueConstraint("documento_version_id", "tipo", "ciclo_revision", name="uq_documento_snapshots_version_tipo_ciclo"),
        sa.UniqueConstraint("public_id", name="uq_documento_snapshots_public_id"),
        sa.UniqueConstraint("storage_path", name="uq_documento_snapshots_storage_path"),
    )
    op.create_index("ix_documento_snapshots_archivo_sha256", "documento_snapshots", ["archivo_sha256"], unique=False)
    op.create_index("ix_documento_snapshots_ciclo_revision", "documento_snapshots", ["ciclo_revision"], unique=False)
    op.create_index("ix_documento_snapshots_creado_en", "documento_snapshots", ["creado_en"], unique=False)
    op.create_index("ix_documento_snapshots_documento_id", "documento_snapshots", ["documento_id"], unique=False)
    op.create_index("ix_documento_snapshots_documento_version_id", "documento_snapshots", ["documento_version_id"], unique=False)
    op.create_index("ix_documento_snapshots_empresa_id", "documento_snapshots", ["empresa_id"], unique=False)
    op.create_index("ix_documento_snapshots_secuencia", "documento_snapshots", ["secuencia"], unique=False)
    op.create_index("ix_documento_snapshots_tipo", "documento_snapshots", ["tipo"], unique=False)
    op.create_index("ix_documento_snapshots_workflow_evento_id", "documento_snapshots", ["workflow_evento_id"], unique=False)
    op.create_index(
        "uq_documento_snapshots_aprobado_unico",
        "documento_snapshots",
        ["documento_version_id"],
        unique=True,
        postgresql_where=sa.text("tipo = 'APROBADO' AND estado = 'DISPONIBLE'"),
        sqlite_where=sa.text("tipo = 'APROBADO' AND estado = 'DISPONIBLE'"),
    )


def downgrade():
    op.drop_index("uq_documento_snapshots_aprobado_unico", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_workflow_evento_id", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_tipo", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_secuencia", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_empresa_id", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_documento_version_id", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_documento_id", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_creado_en", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_ciclo_revision", table_name="documento_snapshots")
    op.drop_index("ix_documento_snapshots_archivo_sha256", table_name="documento_snapshots")
    op.drop_table("documento_snapshots")
