"""documento pdf conversion

Revision ID: c4e7a9d1b2f3
Revises: b9f2d4c8a6e1
Create Date: 2026-07-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c4e7a9d1b2f3"
down_revision = "b9f2d4c8a6e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documento_artefactos",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("source_snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=True),
        sa.Column("archivo_nombre_interno", sa.String(length=255), nullable=True),
        sa.Column("archivo_nombre_visible", sa.String(length=255), nullable=True),
        sa.Column("archivo_mime", sa.String(length=255), nullable=True),
        sa.Column("archivo_size", sa.BigInteger(), nullable=True),
        sa.Column("archivo_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_version", sa.String(length=50), nullable=True),
        sa.Column("creado_por_id", sa.BigInteger(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disponible_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inmutable", sa.Boolean(), nullable=False),
        sa.Column("error_codigo", sa.String(length=80), nullable=True),
        sa.Column("error_mensaje", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.CheckConstraint("tipo IN ('PDF_APROBADO')", name="ck_documento_artefactos_tipo_valido"),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE', 'CONVIRTIENDO', 'DISPONIBLE', 'ERROR', 'CANCELADO')",
            name="ck_documento_artefactos_estado_valido",
        ),
        sa.CheckConstraint("archivo_size IS NULL OR archivo_size > 0", name="ck_documento_artefactos_size_positivo"),
        sa.CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_documento_artefactos_page_count_positivo"),
        sa.CheckConstraint(
            "archivo_sha256 IS NULL OR length(archivo_sha256) = 64",
            name="ck_documento_artefactos_sha256_valido",
        ),
        sa.CheckConstraint(
            "source_snapshot_sha256 IS NULL OR length(source_snapshot_sha256) = 64",
            name="ck_documento_artefactos_source_sha256_valido",
        ),
        sa.CheckConstraint(
            "estado <> 'DISPONIBLE' OR inmutable = true",
            name="ck_documento_artefactos_disponible_inmutable",
        ),
        sa.CheckConstraint(
            "estado <> 'DISPONIBLE' OR page_count > 0",
            name="ck_documento_artefactos_disponible_page_count",
        ),
        sa.CheckConstraint(
            "estado <> 'DISPONIBLE' OR archivo_size > 0",
            name="ck_documento_artefactos_disponible_size",
        ),
        sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["source_snapshot_id"], ["documento_snapshots.id"]),
        sa.UniqueConstraint("public_id", name="uq_documento_artefactos_public_id"),
        sa.UniqueConstraint("storage_path", name="uq_documento_artefactos_storage_path"),
    )
    op.create_index("ix_documento_artefactos_empresa_id", "documento_artefactos", ["empresa_id"])
    op.create_index("ix_documento_artefactos_documento_id", "documento_artefactos", ["documento_id"])
    op.create_index("ix_documento_artefactos_documento_version_id", "documento_artefactos", ["documento_version_id"])
    op.create_index("ix_documento_artefactos_source_snapshot_id", "documento_artefactos", ["source_snapshot_id"])
    op.create_index("ix_documento_artefactos_tipo", "documento_artefactos", ["tipo"])
    op.create_index("ix_documento_artefactos_estado", "documento_artefactos", ["estado"])
    op.create_index("ix_documento_artefactos_creado_en", "documento_artefactos", ["creado_en"])
    op.create_index("ix_documento_artefactos_archivo_sha256", "documento_artefactos", ["archivo_sha256"])
    op.create_index("ix_documento_artefactos_provider", "documento_artefactos", ["provider"])
    op.create_index(
        "uq_documento_artefactos_pdf_aprobado_disponible",
        "documento_artefactos",
        ["source_snapshot_id", "tipo"],
        unique=True,
        postgresql_where=sa.text("tipo = 'PDF_APROBADO' AND estado = 'DISPONIBLE'"),
        sqlite_where=sa.text("tipo = 'PDF_APROBADO' AND estado = 'DISPONIBLE'"),
    )

    op.create_table(
        "documento_conversiones",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("source_snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("artefacto_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("conversion_key", sa.String(length=128), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=True),
        sa.Column("solicitado_por_id", sa.BigInteger(), nullable=False),
        sa.Column("solicitado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultima_consulta_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("response_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("source_url_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE', 'SOLICITADA', 'EN_PROCESO', 'COMPLETADA', 'ERROR', 'CANCELADA')",
            name="ck_documento_conversiones_estado_valido",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_documento_conversiones_attempt_positivo"),
        sa.CheckConstraint(
            "percent IS NULL OR (percent >= 0 AND percent <= 100)",
            name="ck_documento_conversiones_percent_valido",
        ),
        sa.ForeignKeyConstraint(["artefacto_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["solicitado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["source_snapshot_id"], ["documento_snapshots.id"]),
        sa.UniqueConstraint("conversion_key", name="uq_documento_conversiones_conversion_key"),
        sa.UniqueConstraint("public_id", name="uq_documento_conversiones_public_id"),
    )
    op.create_index("ix_documento_conversiones_empresa_id", "documento_conversiones", ["empresa_id"])
    op.create_index("ix_documento_conversiones_documento_id", "documento_conversiones", ["documento_id"])
    op.create_index("ix_documento_conversiones_documento_version_id", "documento_conversiones", ["documento_version_id"])
    op.create_index("ix_documento_conversiones_source_snapshot_id", "documento_conversiones", ["source_snapshot_id"])
    op.create_index("ix_documento_conversiones_artefacto_id", "documento_conversiones", ["artefacto_id"])
    op.create_index("ix_documento_conversiones_provider", "documento_conversiones", ["provider"])
    op.create_index("ix_documento_conversiones_estado", "documento_conversiones", ["estado"])
    op.create_index("ix_documento_conversiones_attempt_number", "documento_conversiones", ["attempt_number"])
    op.create_index("ix_documento_conversiones_solicitado_en", "documento_conversiones", ["solicitado_en"])


def downgrade():
    op.drop_index("ix_documento_conversiones_solicitado_en", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_attempt_number", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_estado", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_provider", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_artefacto_id", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_source_snapshot_id", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_documento_version_id", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_documento_id", table_name="documento_conversiones")
    op.drop_index("ix_documento_conversiones_empresa_id", table_name="documento_conversiones")
    op.drop_table("documento_conversiones")

    op.drop_index("uq_documento_artefactos_pdf_aprobado_disponible", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_provider", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_archivo_sha256", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_creado_en", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_estado", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_tipo", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_source_snapshot_id", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_documento_version_id", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_documento_id", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_empresa_id", table_name="documento_artefactos")
    op.drop_table("documento_artefactos")
