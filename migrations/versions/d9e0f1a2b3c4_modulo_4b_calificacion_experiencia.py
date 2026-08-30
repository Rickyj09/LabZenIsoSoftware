"""Modulo 4B calificacion experiencia

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa


revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_calificaciones",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("institucion", sa.String(length=180), nullable=False),
        sa.Column("titulo", sa.String(length=180), nullable=False),
        sa.Column("area_especialidad", sa.String(length=150), nullable=True),
        sa.Column("fecha_inicio", sa.Date(), nullable=True),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("numero_registro", sa.String(length=100), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "tipo IN ('EDUCACION_FORMAL', 'CERTIFICACION', 'LICENCIA', 'OTRO')",
            name="ck_personal_calificaciones_tipo_valido",
        ),
        sa.CheckConstraint(
            "fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_calificaciones_fechas_ordenadas",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_calificaciones_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["personal_id"], ["personal.id"], name="fk_personal_calificaciones_personal_id_personal"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_calificaciones_empresa_id", "personal_calificaciones", ["empresa_id"])
    op.create_index(
        "ix_personal_calificaciones_empresa_personal",
        "personal_calificaciones",
        ["empresa_id", "personal_id"],
    )
    op.create_index("ix_personal_calificaciones_empresa_tipo", "personal_calificaciones", ["empresa_id", "tipo"])
    op.create_index("ix_personal_calificaciones_empresa_activo", "personal_calificaciones", ["empresa_id", "activo"])

    op.create_table(
        "personal_experiencias",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_id", sa.BigInteger(), nullable=False),
        sa.Column("organizacion", sa.String(length=180), nullable=False),
        sa.Column("cargo_funcion", sa.String(length=180), nullable=False),
        sa.Column("area_especialidad", sa.String(length=150), nullable=True),
        sa.Column("descripcion_actividades", sa.Text(), nullable=True),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("experiencia_actual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_experiencias_fechas_ordenadas",
        ),
        sa.CheckConstraint(
            "experiencia_actual = FALSE OR fecha_fin IS NULL",
            name="ck_personal_experiencias_actual_sin_fecha_fin",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_experiencias_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["personal_id"], ["personal.id"], name="fk_personal_experiencias_personal_id_personal"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_experiencias_empresa_id", "personal_experiencias", ["empresa_id"])
    op.create_index("ix_personal_experiencias_empresa_personal", "personal_experiencias", ["empresa_id", "personal_id"])
    op.create_index("ix_personal_experiencias_empresa_activo", "personal_experiencias", ["empresa_id", "activo"])

    op.create_table(
        "personal_calificacion_evidencias",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_id", sa.BigInteger(), nullable=False),
        sa.Column("calificacion_id", sa.BigInteger(), nullable=False),
        sa.Column("archivo_nombre_original", sa.String(length=255), nullable=False),
        sa.Column("archivo_nombre_guardado", sa.String(length=255), nullable=False),
        sa.Column("archivo_storage_path", sa.String(length=500), nullable=False),
        sa.Column("archivo_mime", sa.String(length=150), nullable=False),
        sa.Column("archivo_size", sa.BigInteger(), nullable=False),
        sa.Column("archivo_sha256", sa.String(length=64), nullable=False),
        sa.Column("cargado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_calificacion_evidencias_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["personal_id"], ["personal.id"], name="fk_personal_calificacion_evidencias_personal_id_personal"),
        sa.ForeignKeyConstraint(["calificacion_id"], ["personal_calificaciones.id"], name="fk_personal_calificacion_evidencias_calificacion_id"),
        sa.ForeignKeyConstraint(["cargado_por_id"], ["usuarios.id"], name="fk_personal_calificacion_evidencias_cargado_por_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_calificacion_evidencias_empresa_id", "personal_calificacion_evidencias", ["empresa_id"])
    op.create_index(
        "ix_personal_calificacion_evidencias_empresa_calificacion",
        "personal_calificacion_evidencias",
        ["empresa_id", "calificacion_id"],
    )
    op.create_index(
        "ix_personal_calificacion_evidencias_empresa_personal",
        "personal_calificacion_evidencias",
        ["empresa_id", "personal_id"],
    )
    op.create_index(
        "ix_personal_calificacion_evidencias_empresa_activo",
        "personal_calificacion_evidencias",
        ["empresa_id", "activo"],
    )


def downgrade():
    op.drop_index("ix_personal_calificacion_evidencias_empresa_activo", table_name="personal_calificacion_evidencias")
    op.drop_index("ix_personal_calificacion_evidencias_empresa_personal", table_name="personal_calificacion_evidencias")
    op.drop_index("ix_personal_calificacion_evidencias_empresa_calificacion", table_name="personal_calificacion_evidencias")
    op.drop_index("ix_personal_calificacion_evidencias_empresa_id", table_name="personal_calificacion_evidencias")
    op.drop_table("personal_calificacion_evidencias")

    op.drop_index("ix_personal_experiencias_empresa_activo", table_name="personal_experiencias")
    op.drop_index("ix_personal_experiencias_empresa_personal", table_name="personal_experiencias")
    op.drop_index("ix_personal_experiencias_empresa_id", table_name="personal_experiencias")
    op.drop_table("personal_experiencias")

    op.drop_index("ix_personal_calificaciones_empresa_activo", table_name="personal_calificaciones")
    op.drop_index("ix_personal_calificaciones_empresa_tipo", table_name="personal_calificaciones")
    op.drop_index("ix_personal_calificaciones_empresa_personal", table_name="personal_calificaciones")
    op.drop_index("ix_personal_calificaciones_empresa_id", table_name="personal_calificaciones")
    op.drop_table("personal_calificaciones")
