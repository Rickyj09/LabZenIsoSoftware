"""Modulo 4F seguimiento de personal

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_seguimientos",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("titulo", sa.String(length=180), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("fecha_deteccion", sa.Date(), nullable=False),
        sa.Column("fecha_objetivo", sa.Date(), nullable=True),
        sa.Column("fecha_cierre", sa.Date(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="PENDIENTE"),
        sa.Column("prioridad", sa.String(length=20), nullable=False, server_default="MEDIA"),
        sa.Column("responsable_personal_id", sa.BigInteger(), nullable=True),
        sa.Column("responsable_usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("evaluacion_competencia_id", sa.BigInteger(), nullable=True),
        sa.Column("autorizacion_tecnica_id", sa.BigInteger(), nullable=True),
        sa.Column("capacitacion_id", sa.BigInteger(), nullable=True),
        sa.Column("accion_requerida", sa.Text(), nullable=False),
        sa.Column("resultado_cierre", sa.Text(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "tipo IN ('REEVALUACION_COMPETENCIA', 'CAPACITACION_REQUERIDA', 'REVISION_AUTORIZACION', 'SEGUIMIENTO_DESEMPENO', 'OBSERVACION', 'OTRO')",
            name="ck_personal_seguimientos_tipo_valido",
        ),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE', 'EN_PROCESO', 'COMPLETADO', 'CANCELADO')",
            name="ck_personal_seguimientos_estado_valido",
        ),
        sa.CheckConstraint(
            "prioridad IN ('BAJA', 'MEDIA', 'ALTA')",
            name="ck_personal_seguimientos_prioridad_valida",
        ),
        sa.CheckConstraint(
            "fecha_objetivo IS NULL OR fecha_objetivo >= fecha_deteccion",
            name="ck_personal_seguimientos_fecha_objetivo_coherente",
        ),
        sa.CheckConstraint(
            "fecha_cierre IS NULL OR fecha_cierre >= fecha_deteccion",
            name="ck_personal_seguimientos_fecha_cierre_coherente",
        ),
        sa.CheckConstraint(
            "estado <> 'COMPLETADO' OR (fecha_cierre IS NOT NULL AND resultado_cierre IS NOT NULL)",
            name="ck_personal_seguimientos_cierre_completo",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_seguimientos_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["personal_id"], ["personal.id"], name="fk_personal_seguimientos_personal_id"),
        sa.ForeignKeyConstraint(
            ["responsable_personal_id"],
            ["personal.id"],
            name="fk_personal_seguimientos_responsable_personal_id",
        ),
        sa.ForeignKeyConstraint(["responsable_usuario_id"], ["usuarios.id"], name="fk_personal_seguimientos_responsable_usuario_id"),
        sa.ForeignKeyConstraint(
            ["evaluacion_competencia_id"],
            ["personal_evaluaciones_competencia.id"],
            name="fk_personal_seguimientos_evaluacion_competencia_id",
        ),
        sa.ForeignKeyConstraint(
            ["autorizacion_tecnica_id"],
            ["personal_autorizaciones_tecnicas.id"],
            name="fk_personal_seguimientos_autorizacion_tecnica_id",
        ),
        sa.ForeignKeyConstraint(["capacitacion_id"], ["personal_capacitaciones.id"], name="fk_personal_seguimientos_capacitacion_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_seguimientos_empresa_id", "personal_seguimientos", ["empresa_id"])
    op.create_index("ix_personal_seguimientos_empresa_personal", "personal_seguimientos", ["empresa_id", "personal_id"])
    op.create_index("ix_personal_seguimientos_empresa_estado", "personal_seguimientos", ["empresa_id", "estado"])
    op.create_index("ix_personal_seguimientos_empresa_tipo", "personal_seguimientos", ["empresa_id", "tipo"])
    op.create_index("ix_personal_seguimientos_empresa_prioridad", "personal_seguimientos", ["empresa_id", "prioridad"])
    op.create_index("ix_personal_seguimientos_empresa_objetivo", "personal_seguimientos", ["empresa_id", "fecha_objetivo"])
    op.create_index(
        "ix_personal_seguimientos_empresa_responsable_personal",
        "personal_seguimientos",
        ["empresa_id", "responsable_personal_id"],
    )


def downgrade():
    op.drop_index("ix_personal_seguimientos_empresa_responsable_personal", table_name="personal_seguimientos")
    op.drop_index("ix_personal_seguimientos_empresa_objetivo", table_name="personal_seguimientos")
    op.drop_index("ix_personal_seguimientos_empresa_prioridad", table_name="personal_seguimientos")
    op.drop_index("ix_personal_seguimientos_empresa_tipo", table_name="personal_seguimientos")
    op.drop_index("ix_personal_seguimientos_empresa_estado", table_name="personal_seguimientos")
    op.drop_index("ix_personal_seguimientos_empresa_personal", table_name="personal_seguimientos")
    op.drop_index("ix_personal_seguimientos_empresa_id", table_name="personal_seguimientos")
    op.drop_table("personal_seguimientos")
