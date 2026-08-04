"""Paquete 5B.1 mantenimiento modelos permisos

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa


revision = "f2b3c4d5e6a7"
down_revision = "e1a2b3c4d5f6"
branch_labels = None
depends_on = None


MAINTENANCE_PERMISSIONS = (
    ("equipos.mantenimientos.ver", "Ver mantenimientos de equipos", "equipamiento"),
    ("equipos.mantenimientos.planes.crear", "Crear planes de mantenimiento de equipos", "equipamiento"),
    ("equipos.mantenimientos.planes.editar", "Editar planes de mantenimiento de equipos", "equipamiento"),
    ("equipos.mantenimientos.programar", "Programar mantenimientos de equipos", "equipamiento"),
    ("equipos.mantenimientos.correctivos.crear", "Crear mantenimientos correctivos de equipos", "equipamiento"),
    ("equipos.mantenimientos.iniciar", "Iniciar mantenimientos de equipos", "equipamiento"),
    ("equipos.mantenimientos.completar", "Completar mantenimientos de equipos", "equipamiento"),
    ("equipos.mantenimientos.cancelar", "Cancelar mantenimientos de equipos", "equipamiento"),
    ("equipos.mantenimientos.evidencias.vincular", "Vincular evidencias de mantenimiento", "equipamiento"),
    ("equipos.mantenimientos.evidencias.desvincular", "Desvincular evidencias de mantenimiento", "equipamiento"),
)

ALL_MAINTENANCE_CODES = {code for code, _name, _module in MAINTENANCE_PERMISSIONS}
TECHNICIAN_MAINTENANCE_CODES = {
    "equipos.mantenimientos.ver",
    "equipos.mantenimientos.programar",
    "equipos.mantenimientos.correctivos.crear",
    "equipos.mantenimientos.iniciar",
    "equipos.mantenimientos.completar",
    "equipos.mantenimientos.cancelar",
    "equipos.mantenimientos.evidencias.vincular",
}

ROLE_PERMISSION_CODES = {
    "ADMINISTRADOR": ALL_MAINTENANCE_CODES,
    "ADMIN": ALL_MAINTENANCE_CODES,
    "SUPERADMIN": ALL_MAINTENANCE_CODES,
    "CALIDAD": ALL_MAINTENANCE_CODES,
    "TECNICO": TECHNICIAN_MAINTENANCE_CODES,
    "CONSULTA": {"equipos.mantenimientos.ver"},
}

OLD_EQUIPMENT_EVENT_TYPES = (
    "CREACION",
    "ACTUALIZACION",
    "CAMBIO_UBICACION",
    "CAMBIO_RESPONSABLE",
    "CAMBIO_ESTADO_OPERATIVO",
    "RETIRO",
    "REACTIVACION",
    "VINCULO_DOCUMENTO",
)

NEW_EQUIPMENT_EVENT_TYPES = (
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


def _in_values(values):
    return ", ".join(f"'{value}'" for value in values)


def upgrade():
    op.create_table(
        "equipo_planes_mantenimiento",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("equipo_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("periodicidad_meses", sa.Integer(), nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("proxima_fecha", sa.Date(), nullable=True),
        sa.Column("responsable_id", sa.BigInteger(), nullable=True),
        sa.Column("proveedor", sa.String(length=150), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="ACTIVO"),
        sa.CheckConstraint("periodicidad_meses > 0", name="ck_equipo_plan_mantenimiento_periodicidad_positiva"),
        sa.CheckConstraint("estado IN ('ACTIVO', 'INACTIVO')", name="ck_equipo_plan_mantenimiento_estado_valido"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["equipo_id"], ["equipos.id"]),
        sa.ForeignKeyConstraint(["responsable_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_equipo_plan_mantenimiento_empresa_codigo"),
    )
    op.create_index("ix_equipo_planes_mantenimiento_empresa_id", "equipo_planes_mantenimiento", ["empresa_id"])
    op.create_index(
        "ix_equipo_plan_mantenimiento_empresa_equipo",
        "equipo_planes_mantenimiento",
        ["empresa_id", "equipo_id"],
    )
    op.create_index(
        "ix_equipo_plan_mantenimiento_empresa_estado",
        "equipo_planes_mantenimiento",
        ["empresa_id", "estado"],
    )
    op.create_index(
        "ix_equipo_plan_mantenimiento_empresa_proxima",
        "equipo_planes_mantenimiento",
        ["empresa_id", "proxima_fecha"],
    )

    with op.batch_alter_table("equipo_mantenimientos") as batch:
        batch.add_column(sa.Column("plan_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("codigo", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("estado", sa.String(length=30), nullable=True, server_default="PROGRAMADO"))
        batch.add_column(sa.Column("fecha_planificada", sa.Date(), nullable=True))
        batch.add_column(sa.Column("fecha_inicio", sa.Date(), nullable=True))
        batch.add_column(sa.Column("fecha_finalizacion", sa.Date(), nullable=True))
        batch.add_column(sa.Column("descripcion_trabajo", sa.Text(), nullable=True))
        batch.add_column(sa.Column("responsable_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("costo", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("moneda", sa.String(length=3), nullable=True))
        batch.add_column(sa.Column("cancelado_por_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("motivo_cancelacion", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE equipo_mantenimientos
        SET descripcion_trabajo =
            CASE
                WHEN tipo_mantenimiento IS NOT NULL
                 AND UPPER(tipo_mantenimiento) NOT IN ('PREVENTIVO', 'CORRECTIVO')
                 AND UPPER(tipo_mantenimiento) NOT LIKE '%PREVENT%'
                 AND UPPER(tipo_mantenimiento) NOT LIKE '%CORRECT%'
                 AND descripcion_trabajo IS NULL
                THEN 'Tipo legado: ' || tipo_mantenimiento
                ELSE descripcion_trabajo
            END
        """
    )
    op.execute(
        """
        UPDATE equipo_mantenimientos
        SET tipo_mantenimiento =
            CASE
                WHEN UPPER(tipo_mantenimiento) = 'PREVENTIVO' THEN 'PREVENTIVO'
                WHEN UPPER(tipo_mantenimiento) = 'CORRECTIVO' THEN 'CORRECTIVO'
                WHEN UPPER(tipo_mantenimiento) LIKE '%PREVENT%' THEN 'PREVENTIVO'
                WHEN UPPER(tipo_mantenimiento) LIKE '%CORRECT%' THEN 'CORRECTIVO'
                ELSE 'CORRECTIVO'
            END
        """
    )
    op.execute(
        """
        UPDATE equipo_mantenimientos
        SET codigo = 'MANT-' || CAST(empresa_id AS VARCHAR) || '-' || CAST(id AS VARCHAR)
        WHERE codigo IS NULL
        """
    )
    op.execute("UPDATE equipo_mantenimientos SET fecha_planificada = fecha_mantenimiento WHERE fecha_planificada IS NULL")
    op.execute(
        """
        UPDATE equipo_mantenimientos
        SET estado = CASE
            WHEN resultado IS NOT NULL AND TRIM(resultado) <> '' THEN 'COMPLETADO'
            ELSE 'PROGRAMADO'
        END
        WHERE estado IS NULL OR estado = 'PROGRAMADO'
        """
    )
    op.execute("UPDATE equipo_mantenimientos SET fecha_finalizacion = fecha_mantenimiento WHERE estado = 'COMPLETADO' AND fecha_finalizacion IS NULL")

    with op.batch_alter_table("equipo_mantenimientos") as batch:
        batch.alter_column("codigo", existing_type=sa.String(length=50), nullable=False)
        batch.alter_column("estado", existing_type=sa.String(length=30), nullable=False, server_default=None)
        batch.alter_column("fecha_planificada", existing_type=sa.Date(), nullable=False)
        batch.alter_column("fecha_mantenimiento", existing_type=sa.Date(), nullable=True)
        batch.create_foreign_key("fk_equipo_mantenimientos_plan_id", "equipo_planes_mantenimiento", ["plan_id"], ["id"])
        batch.create_foreign_key("fk_equipo_mantenimientos_responsable_id", "usuarios", ["responsable_id"], ["id"])
        batch.create_foreign_key("fk_equipo_mantenimientos_cancelado_por_id", "usuarios", ["cancelado_por_id"], ["id"])
        batch.create_unique_constraint("uq_equipo_mantenimiento_empresa_codigo", ["empresa_id", "codigo"])
        batch.create_check_constraint("ck_equipo_mantenimiento_tipo_valido", "tipo_mantenimiento IN ('PREVENTIVO', 'CORRECTIVO')")
        batch.create_check_constraint("ck_equipo_mantenimiento_estado_valido", "estado IN ('PROGRAMADO', 'EN_PROCESO', 'COMPLETADO', 'CANCELADO')")
        batch.create_check_constraint("ck_equipo_mantenimiento_costo_no_negativo", "costo IS NULL OR costo >= 0")
    op.create_index("ix_equipo_mantenimiento_empresa_estado", "equipo_mantenimientos", ["empresa_id", "estado"])
    op.create_index("ix_equipo_mantenimiento_empresa_fecha_planificada", "equipo_mantenimientos", ["empresa_id", "fecha_planificada"])
    op.create_index("ix_equipo_mantenimiento_empresa_equipo_estado", "equipo_mantenimientos", ["empresa_id", "equipo_id", "estado"])
    op.create_index("ix_equipo_mantenimiento_plan_id", "equipo_mantenimientos", ["plan_id"])

    op.create_table(
        "equipo_mantenimiento_documentos",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("mantenimiento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_evidencia", sa.String(length=50), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("vinculado_por_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["mantenimiento_id"], ["equipo_mantenimientos.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["vinculado_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mantenimiento_id", "documento_version_id", name="uq_equipo_mantenimiento_documento_version"),
    )
    op.create_index("ix_equipo_mantenimiento_documentos_empresa_id", "equipo_mantenimiento_documentos", ["empresa_id"])
    op.create_index(
        "ix_equipo_mantenimiento_documentos_empresa_mantenimiento",
        "equipo_mantenimiento_documentos",
        ["empresa_id", "mantenimiento_id"],
    )
    op.create_index(
        "ix_equipo_mantenimiento_documentos_documento_version_id",
        "equipo_mantenimiento_documentos",
        ["documento_version_id"],
    )

    with op.batch_alter_table("equipo_historial") as batch:
        batch.drop_constraint("ck_equipo_historial_tipo_evento_valido", type_="check")
        batch.create_check_constraint(
            "ck_equipo_historial_tipo_evento_valido",
            f"tipo_evento IN ({_in_values(OLD_EQUIPMENT_EVENT_TYPES + NEW_EQUIPMENT_EVENT_TYPES)})",
        )

    _seed_permissions()


def downgrade():
    _delete_permissions()

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

    op.drop_index("ix_equipo_mantenimiento_documentos_documento_version_id", table_name="equipo_mantenimiento_documentos")
    op.drop_index("ix_equipo_mantenimiento_documentos_empresa_mantenimiento", table_name="equipo_mantenimiento_documentos")
    op.drop_index("ix_equipo_mantenimiento_documentos_empresa_id", table_name="equipo_mantenimiento_documentos")
    op.drop_table("equipo_mantenimiento_documentos")

    op.drop_index("ix_equipo_mantenimiento_plan_id", table_name="equipo_mantenimientos")
    op.drop_index("ix_equipo_mantenimiento_empresa_equipo_estado", table_name="equipo_mantenimientos")
    op.drop_index("ix_equipo_mantenimiento_empresa_fecha_planificada", table_name="equipo_mantenimientos")
    op.drop_index("ix_equipo_mantenimiento_empresa_estado", table_name="equipo_mantenimientos")
    op.execute("UPDATE equipo_mantenimientos SET fecha_mantenimiento = fecha_planificada WHERE fecha_mantenimiento IS NULL")
    with op.batch_alter_table("equipo_mantenimientos") as batch:
        batch.drop_constraint("ck_equipo_mantenimiento_costo_no_negativo", type_="check")
        batch.drop_constraint("ck_equipo_mantenimiento_estado_valido", type_="check")
        batch.drop_constraint("ck_equipo_mantenimiento_tipo_valido", type_="check")
        batch.drop_constraint("uq_equipo_mantenimiento_empresa_codigo", type_="unique")
        batch.drop_constraint("fk_equipo_mantenimientos_cancelado_por_id", type_="foreignkey")
        batch.drop_constraint("fk_equipo_mantenimientos_responsable_id", type_="foreignkey")
        batch.drop_constraint("fk_equipo_mantenimientos_plan_id", type_="foreignkey")
        batch.alter_column("fecha_mantenimiento", existing_type=sa.Date(), nullable=False)
        batch.drop_column("motivo_cancelacion")
        batch.drop_column("cancelado_por_id")
        batch.drop_column("moneda")
        batch.drop_column("costo")
        batch.drop_column("responsable_id")
        batch.drop_column("descripcion_trabajo")
        batch.drop_column("fecha_finalizacion")
        batch.drop_column("fecha_inicio")
        batch.drop_column("fecha_planificada")
        batch.drop_column("estado")
        batch.drop_column("codigo")
        batch.drop_column("plan_id")

    op.drop_index("ix_equipo_plan_mantenimiento_empresa_proxima", table_name="equipo_planes_mantenimiento")
    op.drop_index("ix_equipo_plan_mantenimiento_empresa_estado", table_name="equipo_planes_mantenimiento")
    op.drop_index("ix_equipo_plan_mantenimiento_empresa_equipo", table_name="equipo_planes_mantenimiento")
    op.drop_index("ix_equipo_planes_mantenimiento_empresa_id", table_name="equipo_planes_mantenimiento")
    op.drop_table("equipo_planes_mantenimiento")


def _seed_permissions():
    connection = op.get_bind()
    permissions = sa.table(
        "permisos",
        sa.column("id", sa.BigInteger),
        sa.column("codigo", sa.String),
        sa.column("nombre", sa.String),
        sa.column("descripcion", sa.Text),
        sa.column("modulo", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table("roles", sa.column("id", sa.BigInteger), sa.column("nombre", sa.String))
    role_permissions = sa.table(
        "rol_permisos",
        sa.column("rol_id", sa.BigInteger),
        sa.column("permiso_id", sa.BigInteger),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for code, name, module in MAINTENANCE_PERMISSIONS:
        permission_id = connection.execute(sa.select(permissions.c.id).where(permissions.c.codigo == code)).scalar()
        if not permission_id:
            connection.execute(permissions.insert().values(
                codigo=code,
                nombre=name,
                descripcion=name,
                modulo=module,
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            ))
    permission_rows = connection.execute(
        sa.select(permissions.c.id, permissions.c.codigo).where(
            permissions.c.codigo.in_([code for code, _name, _module in MAINTENANCE_PERMISSIONS])
        )
    ).all()
    permission_ids = {row.codigo: row.id for row in permission_rows}
    for role in connection.execute(sa.select(roles.c.id, roles.c.nombre)).all():
        normalized = (role.nombre or "").strip().upper()
        codes = ROLE_PERMISSION_CODES.get(normalized)
        if not codes:
            continue
        for code in codes:
            exists = connection.execute(
                sa.select(role_permissions.c.rol_id).where(
                    role_permissions.c.rol_id == role.id,
                    role_permissions.c.permiso_id == permission_ids[code],
                )
            ).scalar()
            if not exists:
                connection.execute(role_permissions.insert().values(
                    rol_id=role.id,
                    permiso_id=permission_ids[code],
                    created_at=sa.func.now(),
                    updated_at=sa.func.now(),
                ))


def _delete_permissions():
    connection = op.get_bind()
    codes = [code for code, _name, _module in MAINTENANCE_PERMISSIONS]
    ids = connection.execute(
        sa.text("SELECT id FROM permisos WHERE codigo IN :codes").bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": codes},
    ).scalars().all()
    if ids:
        connection.execute(
            sa.text("DELETE FROM rol_permisos WHERE permiso_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": ids},
        )
        connection.execute(
            sa.text("DELETE FROM permisos WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": ids},
        )
