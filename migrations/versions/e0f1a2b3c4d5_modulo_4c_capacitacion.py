"""Modulo 4C capacitacion

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa


revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_capacitaciones",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=True),
        sa.Column("nombre", sa.String(length=180), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("objetivo", sa.Text(), nullable=True),
        sa.Column("proveedor", sa.String(length=180), nullable=True),
        sa.Column("instructor", sa.String(length=180), nullable=True),
        sa.Column("modalidad", sa.String(length=20), nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("duracion_horas", sa.Numeric(8, 2), nullable=True),
        sa.Column("lugar", sa.String(length=180), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="PLANIFICADA"),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "tipo IN ('INTERNA', 'EXTERNA', 'INDUCCION', 'ACTUALIZACION', 'ENTRENAMIENTO', 'OTRO')",
            name="ck_personal_capacitaciones_tipo_valido",
        ),
        sa.CheckConstraint(
            "modalidad IN ('PRESENCIAL', 'VIRTUAL', 'HIBRIDA')",
            name="ck_personal_capacitaciones_modalidad_valida",
        ),
        sa.CheckConstraint(
            "estado IN ('PLANIFICADA', 'EN_CURSO', 'COMPLETADA', 'CANCELADA')",
            name="ck_personal_capacitaciones_estado_valido",
        ),
        sa.CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_capacitaciones_fechas_ordenadas",
        ),
        sa.CheckConstraint(
            "duracion_horas IS NULL OR duracion_horas >= 0",
            name="ck_personal_capacitaciones_duracion_no_negativa",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_capacitaciones_empresa_id_empresas"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_personal_capacitaciones_empresa_codigo"),
    )
    op.create_index("ix_personal_capacitaciones_empresa_id", "personal_capacitaciones", ["empresa_id"])
    op.create_index("ix_personal_capacitaciones_empresa_estado", "personal_capacitaciones", ["empresa_id", "estado"])
    op.create_index("ix_personal_capacitaciones_empresa_tipo", "personal_capacitaciones", ["empresa_id", "tipo"])
    op.create_index("ix_personal_capacitaciones_empresa_fechas", "personal_capacitaciones", ["empresa_id", "fecha_inicio", "fecha_fin"])

    op.create_table(
        "personal_capacitacion_participantes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("capacitacion_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_id", sa.BigInteger(), nullable=False),
        sa.Column("estado_participacion", sa.String(length=20), nullable=False, server_default="INSCRITO"),
        sa.Column("fecha_registro", sa.Date(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "estado_participacion IN ('INSCRITO', 'ASISTIO', 'COMPLETO', 'NO_ASISTIO', 'RETIRADO')",
            name="ck_personal_cap_participantes_estado_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_cap_participantes_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["capacitacion_id"], ["personal_capacitaciones.id"], name="fk_personal_cap_participantes_capacitacion_id"),
        sa.ForeignKeyConstraint(["personal_id"], ["personal.id"], name="fk_personal_cap_participantes_personal_id_personal"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "capacitacion_id", "personal_id", name="uq_personal_cap_participante_unico"),
    )
    op.create_index("ix_personal_cap_participantes_empresa_id", "personal_capacitacion_participantes", ["empresa_id"])
    op.create_index(
        "ix_personal_cap_participantes_empresa_capacitacion",
        "personal_capacitacion_participantes",
        ["empresa_id", "capacitacion_id"],
    )
    op.create_index(
        "ix_personal_cap_participantes_empresa_personal",
        "personal_capacitacion_participantes",
        ["empresa_id", "personal_id"],
    )
    op.create_index(
        "ix_personal_cap_participantes_empresa_estado",
        "personal_capacitacion_participantes",
        ["empresa_id", "estado_participacion"],
    )

    op.create_table(
        "personal_capacitacion_evidencias",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("capacitacion_id", sa.BigInteger(), nullable=False),
        sa.Column("participante_id", sa.BigInteger(), nullable=True),
        sa.Column("archivo_nombre_original", sa.String(length=255), nullable=False),
        sa.Column("archivo_nombre_guardado", sa.String(length=255), nullable=False),
        sa.Column("archivo_storage_path", sa.String(length=500), nullable=False),
        sa.Column("archivo_mime", sa.String(length=150), nullable=False),
        sa.Column("archivo_size", sa.BigInteger(), nullable=False),
        sa.Column("archivo_sha256", sa.String(length=64), nullable=False),
        sa.Column("tipo_evidencia", sa.String(length=30), nullable=False),
        sa.Column("cargado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "tipo_evidencia IN ('CERTIFICADO', 'LISTA_ASISTENCIA', 'DIPLOMA', 'CONSTANCIA', 'MATERIAL', 'OTRO')",
            name="ck_personal_cap_evidencias_tipo_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_cap_evidencias_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["capacitacion_id"], ["personal_capacitaciones.id"], name="fk_personal_cap_evidencias_capacitacion_id"),
        sa.ForeignKeyConstraint(["participante_id"], ["personal_capacitacion_participantes.id"], name="fk_personal_cap_evidencias_participante_id"),
        sa.ForeignKeyConstraint(["cargado_por_id"], ["usuarios.id"], name="fk_personal_cap_evidencias_cargado_por_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_cap_evidencias_empresa_id", "personal_capacitacion_evidencias", ["empresa_id"])
    op.create_index(
        "ix_personal_cap_evidencias_empresa_capacitacion",
        "personal_capacitacion_evidencias",
        ["empresa_id", "capacitacion_id"],
    )
    op.create_index(
        "ix_personal_cap_evidencias_empresa_participante",
        "personal_capacitacion_evidencias",
        ["empresa_id", "participante_id"],
    )
    op.create_index(
        "ix_personal_cap_evidencias_empresa_activo",
        "personal_capacitacion_evidencias",
        ["empresa_id", "activo"],
    )


def downgrade():
    op.drop_index("ix_personal_cap_evidencias_empresa_activo", table_name="personal_capacitacion_evidencias")
    op.drop_index("ix_personal_cap_evidencias_empresa_participante", table_name="personal_capacitacion_evidencias")
    op.drop_index("ix_personal_cap_evidencias_empresa_capacitacion", table_name="personal_capacitacion_evidencias")
    op.drop_index("ix_personal_cap_evidencias_empresa_id", table_name="personal_capacitacion_evidencias")
    op.drop_table("personal_capacitacion_evidencias")

    op.drop_index("ix_personal_cap_participantes_empresa_estado", table_name="personal_capacitacion_participantes")
    op.drop_index("ix_personal_cap_participantes_empresa_personal", table_name="personal_capacitacion_participantes")
    op.drop_index("ix_personal_cap_participantes_empresa_capacitacion", table_name="personal_capacitacion_participantes")
    op.drop_index("ix_personal_cap_participantes_empresa_id", table_name="personal_capacitacion_participantes")
    op.drop_table("personal_capacitacion_participantes")

    op.drop_index("ix_personal_capacitaciones_empresa_fechas", table_name="personal_capacitaciones")
    op.drop_index("ix_personal_capacitaciones_empresa_tipo", table_name="personal_capacitaciones")
    op.drop_index("ix_personal_capacitaciones_empresa_estado", table_name="personal_capacitaciones")
    op.drop_index("ix_personal_capacitaciones_empresa_id", table_name="personal_capacitaciones")
    op.drop_table("personal_capacitaciones")
