"""Paquete 5C.1 calibraciones metrologicas

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


OLD_EQUIPMENT_EVENT_TYPES = (
    "CREACION",
    "ACTUALIZACION",
    "CAMBIO_UBICACION",
    "CAMBIO_RESPONSABLE",
    "CAMBIO_ESTADO_OPERATIVO",
    "RETIRO",
    "REACTIVACION",
    "VINCULO_DOCUMENTO",
    "PLAN_MANTENIMIENTO_CREADO",
    "PLAN_MANTENIMIENTO_ACTUALIZADO",
    "PLAN_MANTENIMIENTO_INACTIVADO",
    "MANTENIMIENTO_PROGRAMADO",
    "MANTENIMIENTO_CORRECTIVO_CREADO",
    "MANTENIMIENTO_INICIADO",
    "MANTENIMIENTO_COMPLETADO",
    "MANTENIMIENTO_CANCELADO",
    "EVIDENCIA_MANTENIMIENTO_VINCULADA",
    "EVIDENCIA_MANTENIMIENTO_DESVINCULADA",
)

NEW_EQUIPMENT_EVENT_TYPES = (
    "CALIBRACION_PROGRAMADA",
    "VERIFICACION_PROGRAMADA",
    "CALIBRACION_INICIADA",
    "VERIFICACION_INICIADA",
    "CALIBRACION_COMPLETADA",
    "VERIFICACION_COMPLETADA",
    "CALIBRACION_CANCELADA",
    "VERIFICACION_CANCELADA",
    "EVIDENCIA_CALIBRACION_VINCULADA",
    "EVIDENCIA_CALIBRACION_DESVINCULADA",
)


def _in_values(values):
    return ", ".join(f"'{value}'" for value in values)


def upgrade():
    with op.batch_alter_table("equipo_calibraciones") as batch:
        batch.add_column(sa.Column("codigo", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("tipo_control", sa.String(length=30), nullable=True, server_default="CALIBRACION"))
        batch.add_column(sa.Column("estado", sa.String(length=30), nullable=True, server_default="COMPLETADO"))
        batch.add_column(sa.Column("fecha_planificada", sa.Date(), nullable=True))
        batch.add_column(sa.Column("fecha_inicio", sa.Date(), nullable=True))
        batch.add_column(sa.Column("fecha_finalizacion", sa.Date(), nullable=True))
        batch.add_column(sa.Column("periodicidad_meses", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("responsable_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("costo", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("moneda", sa.String(length=3), nullable=True))
        batch.add_column(sa.Column("cancelado_por_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("motivo_cancelacion", sa.Text(), nullable=True))

    op.execute("UPDATE equipo_calibraciones SET codigo = 'CAL-' || CAST(empresa_id AS VARCHAR) || '-' || CAST(id AS VARCHAR) WHERE codigo IS NULL")
    op.execute("UPDATE equipo_calibraciones SET tipo_control = 'CALIBRACION' WHERE tipo_control IS NULL")
    op.execute("UPDATE equipo_calibraciones SET estado = CASE WHEN resultado IS NOT NULL AND TRIM(resultado) <> '' THEN 'COMPLETADO' ELSE 'PROGRAMADO' END WHERE estado IS NULL OR estado = 'COMPLETADO'")
    op.execute("UPDATE equipo_calibraciones SET fecha_planificada = fecha_calibracion WHERE fecha_planificada IS NULL")
    op.execute("UPDATE equipo_calibraciones SET fecha_finalizacion = fecha_calibracion WHERE estado = 'COMPLETADO' AND fecha_finalizacion IS NULL")

    with op.batch_alter_table("equipo_calibraciones") as batch:
        batch.alter_column("codigo", existing_type=sa.String(length=50), nullable=False)
        batch.alter_column("tipo_control", existing_type=sa.String(length=30), nullable=False, server_default=None)
        batch.alter_column("estado", existing_type=sa.String(length=30), nullable=False, server_default=None)
        batch.alter_column("fecha_planificada", existing_type=sa.Date(), nullable=False)
        batch.alter_column("fecha_calibracion", existing_type=sa.Date(), nullable=True)
        batch.create_foreign_key("fk_equipo_calibraciones_responsable_id", "usuarios", ["responsable_id"], ["id"])
        batch.create_foreign_key("fk_equipo_calibraciones_cancelado_por_id", "usuarios", ["cancelado_por_id"], ["id"])
        batch.create_unique_constraint("uq_equipo_calibracion_empresa_codigo", ["empresa_id", "codigo"])
        batch.create_check_constraint("ck_equipo_calibracion_tipo_valido", "tipo_control IN ('CALIBRACION', 'VERIFICACION')")
        batch.create_check_constraint("ck_equipo_calibracion_estado_valido", "estado IN ('PROGRAMADO', 'EN_PROCESO', 'COMPLETADO', 'CANCELADO')")
        batch.create_check_constraint("ck_equipo_calibracion_costo_no_negativo", "costo IS NULL OR costo >= 0")

    op.create_index("ix_equipo_calibracion_empresa_estado", "equipo_calibraciones", ["empresa_id", "estado"])
    op.create_index("ix_equipo_calibracion_empresa_fecha_planificada", "equipo_calibraciones", ["empresa_id", "fecha_planificada"])
    op.create_index("ix_equipo_calibracion_empresa_equipo_estado", "equipo_calibraciones", ["empresa_id", "equipo_id", "estado"])

    op.create_table(
        "equipo_calibracion_documentos",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("calibracion_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_evidencia", sa.String(length=50), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("vinculado_por_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["calibracion_id"], ["equipo_calibraciones.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["vinculado_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("calibracion_id", "documento_version_id", name="uq_equipo_calibracion_documento_version"),
    )
    op.create_index("ix_equipo_calibracion_documentos_empresa_id", "equipo_calibracion_documentos", ["empresa_id"])
    op.create_index(
        "ix_equipo_calibracion_documentos_empresa_calibracion",
        "equipo_calibracion_documentos",
        ["empresa_id", "calibracion_id"],
    )
    op.create_index(
        "ix_equipo_calibracion_documentos_documento_version_id",
        "equipo_calibracion_documentos",
        ["documento_version_id"],
    )

    with op.batch_alter_table("equipo_historial") as batch:
        batch.drop_constraint("ck_equipo_historial_tipo_evento_valido", type_="check")
        batch.create_check_constraint(
            "ck_equipo_historial_tipo_evento_valido",
            f"tipo_evento IN ({_in_values(OLD_EQUIPMENT_EVENT_TYPES + NEW_EQUIPMENT_EVENT_TYPES)})",
        )


def downgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE equipo_historial SET tipo_evento = 'ACTUALIZACION' WHERE tipo_evento IN :event_types").bindparams(
            sa.bindparam("event_types", expanding=True)
        ),
        {"event_types": NEW_EQUIPMENT_EVENT_TYPES},
    )
    with op.batch_alter_table("equipo_historial") as batch:
        batch.drop_constraint("ck_equipo_historial_tipo_evento_valido", type_="check")
        batch.create_check_constraint(
            "ck_equipo_historial_tipo_evento_valido",
            f"tipo_evento IN ({_in_values(OLD_EQUIPMENT_EVENT_TYPES)})",
        )

    op.drop_index("ix_equipo_calibracion_documentos_documento_version_id", table_name="equipo_calibracion_documentos")
    op.drop_index("ix_equipo_calibracion_documentos_empresa_calibracion", table_name="equipo_calibracion_documentos")
    op.drop_index("ix_equipo_calibracion_documentos_empresa_id", table_name="equipo_calibracion_documentos")
    op.drop_table("equipo_calibracion_documentos")

    op.drop_index("ix_equipo_calibracion_empresa_equipo_estado", table_name="equipo_calibraciones")
    op.drop_index("ix_equipo_calibracion_empresa_fecha_planificada", table_name="equipo_calibraciones")
    op.drop_index("ix_equipo_calibracion_empresa_estado", table_name="equipo_calibraciones")
    with op.batch_alter_table("equipo_calibraciones") as batch:
        batch.drop_constraint("ck_equipo_calibracion_costo_no_negativo", type_="check")
        batch.drop_constraint("ck_equipo_calibracion_estado_valido", type_="check")
        batch.drop_constraint("ck_equipo_calibracion_tipo_valido", type_="check")
        batch.drop_constraint("uq_equipo_calibracion_empresa_codigo", type_="unique")
        batch.drop_constraint("fk_equipo_calibraciones_cancelado_por_id", type_="foreignkey")
        batch.drop_constraint("fk_equipo_calibraciones_responsable_id", type_="foreignkey")
        batch.alter_column("fecha_calibracion", existing_type=sa.Date(), nullable=False)
        batch.drop_column("motivo_cancelacion")
        batch.drop_column("cancelado_por_id")
        batch.drop_column("moneda")
        batch.drop_column("costo")
        batch.drop_column("responsable_id")
        batch.drop_column("periodicidad_meses")
        batch.drop_column("fecha_finalizacion")
        batch.drop_column("fecha_inicio")
        batch.drop_column("fecha_planificada")
        batch.drop_column("estado")
        batch.drop_column("tipo_control")
        batch.drop_column("codigo")
