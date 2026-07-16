"""documento firma externa controlada

Revision ID: e5a7c9d2f4b1
Revises: c4e7a9d1b2f3
Create Date: 2026-07-16 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e5a7c9d2f4b1"
down_revision = "c4e7a9d1b2f3"
branch_labels = None
depends_on = None


ARTEFACTO_TIPOS = "tipo IN ('PDF_APROBADO', 'PDF_FIRMADO_PARCIAL', 'PDF_FIRMADO_FINAL')"


def upgrade():
    with op.batch_alter_table("documento_artefactos") as batch:
        batch.drop_constraint("ck_documento_artefactos_tipo_valido", type_="check")
        batch.add_column(sa.Column("source_artifact_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("firma_proceso_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("firma_paso_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("source_artifact_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("signature_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("validation_state", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("signed_revision", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("signed_by_user_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_documento_artefactos_tipo_valido", ARTEFACTO_TIPOS)
        batch.create_check_constraint(
            "ck_documento_artefactos_source_artifact_sha256_valido",
            "source_artifact_sha256 IS NULL OR length(source_artifact_sha256) = 64",
        )
        batch.create_check_constraint(
            "ck_documento_artefactos_signature_count_valido",
            "signature_count IS NULL OR signature_count >= 0",
        )
        batch.create_check_constraint(
            "ck_documento_artefactos_signed_revision_valido",
            "signed_revision IS NULL OR signed_revision > 0",
        )
        batch.create_foreign_key("fk_documento_artefactos_source_artifact_id", "documento_artefactos", ["source_artifact_id"], ["id"])
        batch.create_foreign_key("fk_documento_artefactos_signed_by_user_id", "usuarios", ["signed_by_user_id"], ["id"])

    op.create_index("ix_documento_artefactos_source_artifact_id", "documento_artefactos", ["source_artifact_id"])
    op.create_index("ix_documento_artefactos_firma_proceso_id", "documento_artefactos", ["firma_proceso_id"])
    op.create_index("ix_documento_artefactos_firma_paso_id", "documento_artefactos", ["firma_paso_id"])

    op.create_table(
        "usuario_identidades_firma",
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("identificacion", sa.String(length=50), nullable=False),
        sa.Column("nombre_certificado", sa.String(length=255), nullable=True),
        sa.Column("emisor_certificado", sa.String(length=255), nullable=True),
        sa.Column("certificado_fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("verificado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("verificado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.CheckConstraint("estado IN ('PENDIENTE', 'VERIFICADA', 'RECHAZADA', 'REVOCADA')", name="ck_usuario_identidades_firma_estado_valido"),
        sa.CheckConstraint("certificado_fingerprint_sha256 IS NULL OR length(certificado_fingerprint_sha256) = 64", name="ck_usuario_identidades_firma_fingerprint_valido"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["verificado_por_id"], ["usuarios.id"]),
        sa.UniqueConstraint("usuario_id", "identificacion", name="uq_usuario_identidad_firma_identificacion"),
    )
    op.create_index("ix_usuario_identidades_firma_empresa_id", "usuario_identidades_firma", ["empresa_id"])
    op.create_index("ix_usuario_identidades_firma_usuario_id", "usuario_identidades_firma", ["usuario_id"])
    op.create_index("ix_usuario_identidades_firma_estado", "usuario_identidades_firma", ["estado"])

    op.create_table(
        "documento_firma_procesos",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("pdf_origen_id", sa.BigInteger(), nullable=False),
        sa.Column("pdf_final_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("solicitado_por_id", sa.BigInteger(), nullable=False),
        sa.Column("solicitado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vence_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_codigo", sa.String(length=80), nullable=True),
        sa.Column("error_mensaje", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.CheckConstraint("estado IN ('PENDIENTE', 'EN_FIRMA', 'COMPLETADO', 'RECHAZADO', 'CANCELADO', 'ERROR', 'VENCIDO')", name="ck_documento_firma_procesos_estado_valido"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["pdf_final_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["pdf_origen_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["solicitado_por_id"], ["usuarios.id"]),
        sa.UniqueConstraint("public_id", name="uq_documento_firma_procesos_public_id"),
    )
    op.create_index("ix_documento_firma_procesos_empresa_id", "documento_firma_procesos", ["empresa_id"])
    op.create_index("ix_documento_firma_procesos_documento_id", "documento_firma_procesos", ["documento_id"])
    op.create_index("ix_documento_firma_procesos_documento_version_id", "documento_firma_procesos", ["documento_version_id"])
    op.create_index("ix_documento_firma_procesos_pdf_origen_id", "documento_firma_procesos", ["pdf_origen_id"])
    op.create_index("ix_documento_firma_procesos_estado", "documento_firma_procesos", ["estado"])
    op.create_index(
        "uq_documento_firma_proceso_activo",
        "documento_firma_procesos",
        ["documento_version_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('PENDIENTE', 'EN_FIRMA')"),
        sqlite_where=sa.text("estado IN ('PENDIENTE', 'EN_FIRMA')"),
    )

    op.create_table(
        "documento_firma_pasos",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("proceso_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("rol_firmante", sa.String(length=30), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("identidad_firma_id", sa.BigInteger(), nullable=True),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("artifact_entrada_id", sa.BigInteger(), nullable=True),
        sa.Column("artifact_salida_id", sa.BigInteger(), nullable=True),
        sa.Column("habilitado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("firmado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vence_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_count_after", sa.Integer(), nullable=True),
        sa.Column("validation_state", sa.String(length=50), nullable=True),
        sa.Column("validation_summary", sa.Text(), nullable=True),
        sa.Column("error_codigo", sa.String(length=80), nullable=True),
        sa.Column("error_mensaje", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.CheckConstraint("rol_firmante IN ('ELABORADOR', 'REVISOR', 'APROBADOR')", name="ck_documento_firma_pasos_rol_valido"),
        sa.CheckConstraint("estado IN ('PENDIENTE', 'HABILITADO', 'FIRMADO', 'RECHAZADO', 'CANCELADO', 'ERROR', 'VENCIDO')", name="ck_documento_firma_pasos_estado_valido"),
        sa.CheckConstraint("orden > 0", name="ck_documento_firma_pasos_orden_positivo"),
        sa.CheckConstraint("signature_count_after IS NULL OR signature_count_after >= 0", name="ck_documento_firma_pasos_signature_count_valido"),
        sa.ForeignKeyConstraint(["artifact_entrada_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["artifact_salida_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["identidad_firma_id"], ["usuario_identidades_firma.id"]),
        sa.ForeignKeyConstraint(["proceso_id"], ["documento_firma_procesos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.UniqueConstraint("proceso_id", "orden", name="uq_documento_firma_pasos_proceso_orden"),
        sa.UniqueConstraint("public_id", name="uq_documento_firma_pasos_public_id"),
    )
    op.create_index("ix_documento_firma_pasos_empresa_id", "documento_firma_pasos", ["empresa_id"])
    op.create_index("ix_documento_firma_pasos_proceso_id", "documento_firma_pasos", ["proceso_id"])
    op.create_index("ix_documento_firma_pasos_usuario_id", "documento_firma_pasos", ["usuario_id"])
    op.create_index("ix_documento_firma_pasos_estado", "documento_firma_pasos", ["estado"])

    op.create_table(
        "documento_firma_eventos",
        sa.Column("proceso_id", sa.BigInteger(), nullable=False),
        sa.Column("paso_id", sa.BigInteger(), nullable=True),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("tipo_evento", sa.String(length=40), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.CheckConstraint("tipo_evento IN ('PROCESO_CREADO', 'PASO_HABILITADO', 'PDF_DESCARGADO', 'PDF_SUBIDO', 'VALIDACION_OK', 'VALIDACION_ERROR', 'PASO_FIRMADO', 'PROCESO_COMPLETADO', 'RECHAZADO', 'CANCELADO', 'VENCIDO', 'ERROR')", name="ck_documento_firma_eventos_tipo_valido"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["paso_id"], ["documento_firma_pasos.id"]),
        sa.ForeignKeyConstraint(["proceso_id"], ["documento_firma_procesos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
    )
    op.create_index("ix_documento_firma_eventos_empresa_id", "documento_firma_eventos", ["empresa_id"])
    op.create_index("ix_documento_firma_eventos_proceso_id", "documento_firma_eventos", ["proceso_id"])
    op.create_index("ix_documento_firma_eventos_paso_id", "documento_firma_eventos", ["paso_id"])
    op.create_index("ix_documento_firma_eventos_tipo_evento", "documento_firma_eventos", ["tipo_evento"])
    op.create_index("ix_documento_firma_eventos_creado_en", "documento_firma_eventos", ["creado_en"])

    with op.batch_alter_table("documento_artefactos") as batch:
        batch.create_foreign_key("fk_documento_artefactos_firma_proceso_id", "documento_firma_procesos", ["firma_proceso_id"], ["id"])
        batch.create_foreign_key("fk_documento_artefactos_firma_paso_id", "documento_firma_pasos", ["firma_paso_id"], ["id"])


def downgrade():
    with op.batch_alter_table("documento_artefactos") as batch:
        batch.drop_constraint("fk_documento_artefactos_firma_paso_id", type_="foreignkey")
        batch.drop_constraint("fk_documento_artefactos_firma_proceso_id", type_="foreignkey")

    op.drop_index("ix_documento_firma_eventos_creado_en", table_name="documento_firma_eventos")
    op.drop_index("ix_documento_firma_eventos_tipo_evento", table_name="documento_firma_eventos")
    op.drop_index("ix_documento_firma_eventos_paso_id", table_name="documento_firma_eventos")
    op.drop_index("ix_documento_firma_eventos_proceso_id", table_name="documento_firma_eventos")
    op.drop_index("ix_documento_firma_eventos_empresa_id", table_name="documento_firma_eventos")
    op.drop_table("documento_firma_eventos")

    op.drop_index("ix_documento_firma_pasos_estado", table_name="documento_firma_pasos")
    op.drop_index("ix_documento_firma_pasos_usuario_id", table_name="documento_firma_pasos")
    op.drop_index("ix_documento_firma_pasos_proceso_id", table_name="documento_firma_pasos")
    op.drop_index("ix_documento_firma_pasos_empresa_id", table_name="documento_firma_pasos")
    op.drop_table("documento_firma_pasos")

    op.drop_index("uq_documento_firma_proceso_activo", table_name="documento_firma_procesos")
    op.drop_index("ix_documento_firma_procesos_estado", table_name="documento_firma_procesos")
    op.drop_index("ix_documento_firma_procesos_pdf_origen_id", table_name="documento_firma_procesos")
    op.drop_index("ix_documento_firma_procesos_documento_version_id", table_name="documento_firma_procesos")
    op.drop_index("ix_documento_firma_procesos_documento_id", table_name="documento_firma_procesos")
    op.drop_index("ix_documento_firma_procesos_empresa_id", table_name="documento_firma_procesos")
    op.drop_table("documento_firma_procesos")

    op.drop_index("ix_usuario_identidades_firma_estado", table_name="usuario_identidades_firma")
    op.drop_index("ix_usuario_identidades_firma_usuario_id", table_name="usuario_identidades_firma")
    op.drop_index("ix_usuario_identidades_firma_empresa_id", table_name="usuario_identidades_firma")
    op.drop_table("usuario_identidades_firma")

    op.drop_index("ix_documento_artefactos_firma_paso_id", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_firma_proceso_id", table_name="documento_artefactos")
    op.drop_index("ix_documento_artefactos_source_artifact_id", table_name="documento_artefactos")
    with op.batch_alter_table("documento_artefactos") as batch:
        batch.drop_constraint("fk_documento_artefactos_signed_by_user_id", type_="foreignkey")
        batch.drop_constraint("fk_documento_artefactos_source_artifact_id", type_="foreignkey")
        batch.drop_constraint("ck_documento_artefactos_signed_revision_valido", type_="check")
        batch.drop_constraint("ck_documento_artefactos_signature_count_valido", type_="check")
        batch.drop_constraint("ck_documento_artefactos_source_artifact_sha256_valido", type_="check")
        batch.drop_constraint("ck_documento_artefactos_tipo_valido", type_="check")
        batch.drop_column("signed_at")
        batch.drop_column("signed_by_user_id")
        batch.drop_column("signed_revision")
        batch.drop_column("validation_state")
        batch.drop_column("signature_count")
        batch.drop_column("source_artifact_sha256")
        batch.drop_column("firma_paso_id")
        batch.drop_column("firma_proceso_id")
        batch.drop_column("source_artifact_id")
        batch.create_check_constraint("ck_documento_artefactos_tipo_valido", "tipo IN ('PDF_APROBADO')")
