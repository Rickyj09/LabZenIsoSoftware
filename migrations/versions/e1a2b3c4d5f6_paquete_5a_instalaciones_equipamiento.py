"""Paquete 5A instalaciones areas e inventario de equipos

Revision ID: e1a2b3c4d5f6
Revises: d8e9f0a1b2c3
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa


revision = "e1a2b3c4d5f6"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


NEW_PERMISSIONS = (
    ("equipamiento.dashboard.ver", "Ver dashboard de instalaciones y equipamiento", "equipamiento"),
    ("instalaciones.ver", "Ver instalaciones", "equipamiento"),
    ("instalaciones.crear", "Crear instalaciones", "equipamiento"),
    ("instalaciones.editar", "Editar instalaciones", "equipamiento"),
    ("instalaciones.inactivar", "Inactivar instalaciones", "equipamiento"),
    ("areas.ver", "Ver areas y ambientes", "equipamiento"),
    ("areas.crear", "Crear areas y ambientes", "equipamiento"),
    ("areas.editar", "Editar areas y ambientes", "equipamiento"),
    ("areas.inactivar", "Inactivar areas y ambientes", "equipamiento"),
    ("equipos.ver", "Ver equipos", "equipamiento"),
    ("equipos.crear", "Crear equipos", "equipamiento"),
    ("equipos.editar", "Editar equipos", "equipamiento"),
    ("equipos.cambiar_estado", "Cambiar estado operativo de equipos", "equipamiento"),
    ("equipos.inactivar", "Inactivar equipos", "equipamiento"),
    ("equipos.historial.ver", "Ver historial de equipos", "equipamiento"),
    ("equipos.documentos.vincular", "Vincular documentos a equipos", "equipamiento"),
)


ROLE_PERMISSION_CODES = {
    "ADMINISTRADOR": {code for code, _name, _module in NEW_PERMISSIONS},
    "ADMIN": {code for code, _name, _module in NEW_PERMISSIONS},
    "SUPERADMIN": {code for code, _name, _module in NEW_PERMISSIONS},
    "CALIDAD": {code for code, _name, _module in NEW_PERMISSIONS},
    "TECNICO": {
        "equipamiento.dashboard.ver",
        "instalaciones.ver",
        "areas.ver",
        "equipos.ver",
        "equipos.crear",
        "equipos.editar",
        "equipos.cambiar_estado",
        "equipos.historial.ver",
        "equipos.documentos.vincular",
    },
    "CONSULTA": {
        "equipamiento.dashboard.ver",
        "instalaciones.ver",
        "areas.ver",
        "equipos.ver",
        "equipos.historial.ver",
    },
}


def upgrade():
    op.create_table(
        "instalaciones",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("direccion", sa.Text(), nullable=True),
        sa.Column("responsable", sa.String(length=150), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="activo"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_instalaciones_empresa_codigo"),
    )
    op.create_index("ix_instalaciones_empresa_id", "instalaciones", ["empresa_id"])
    op.create_index("ix_instalaciones_empresa_estado", "instalaciones", ["empresa_id", "estado"])
    op.create_index("ix_instalaciones_estado", "instalaciones", ["estado"])

    op.create_table(
        "areas_ambientes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("instalacion_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("tipo", sa.String(length=80), nullable=True),
        sa.Column("ubicacion_interna", sa.String(length=150), nullable=True),
        sa.Column("responsable", sa.String(length=150), nullable=True),
        sa.Column("requiere_control_ambiental", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="activo"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["instalacion_id"], ["instalaciones.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_areas_ambientes_empresa_codigo"),
    )
    op.create_index("ix_areas_ambientes_empresa_id", "areas_ambientes", ["empresa_id"])
    op.create_index("ix_areas_ambientes_empresa_estado", "areas_ambientes", ["empresa_id", "estado"])
    op.create_index("ix_areas_ambientes_instalacion_id", "areas_ambientes", ["instalacion_id"])
    op.create_index("ix_areas_ambientes_estado", "areas_ambientes", ["estado"])

    with op.batch_alter_table("equipos") as batch:
        batch.add_column(sa.Column("instalacion_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("area_ambiente_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("tipo", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("fabricante", sa.String(length=150), nullable=True))
        batch.add_column(sa.Column("ubicacion_especifica", sa.String(length=150), nullable=True))
        batch.add_column(sa.Column("estado_operativo", sa.String(length=30), nullable=False, server_default="OPERATIVO"))
        batch.add_column(sa.Column("requiere_mantenimiento", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("responsable", sa.String(length=150), nullable=True))
        batch.add_column(sa.Column("observaciones", sa.Text(), nullable=True))
    op.execute(
        "UPDATE equipos SET criticidad = UPPER(criticidad) "
        "WHERE criticidad IS NOT NULL AND UPPER(criticidad) IN ('BAJA', 'MEDIA', 'ALTA')"
    )
    op.execute("UPDATE equipos SET criticidad = NULL WHERE criticidad IS NOT NULL AND criticidad NOT IN ('BAJA', 'MEDIA', 'ALTA')")
    with op.batch_alter_table("equipos") as batch:
        batch.create_foreign_key("fk_equipos_instalacion_id", "instalaciones", ["instalacion_id"], ["id"])
        batch.create_foreign_key("fk_equipos_area_ambiente_id", "areas_ambientes", ["area_ambiente_id"], ["id"])
        batch.create_check_constraint(
            "ck_equipos_estado_operativo_valido",
            "estado_operativo IN ('OPERATIVO', 'FUERA_DE_SERVICIO', 'EN_MANTENIMIENTO', 'EN_CALIBRACION', 'RETIRADO')",
        )
        batch.create_check_constraint("ck_equipos_criticidad_valida", "criticidad IS NULL OR criticidad IN ('BAJA', 'MEDIA', 'ALTA')")
    op.create_index("ix_equipos_estado", "equipos", ["estado"])
    op.create_index("ix_equipos_estado_operativo", "equipos", ["estado_operativo"])
    op.create_index("ix_equipos_instalacion_id", "equipos", ["instalacion_id"])
    op.create_index("ix_equipos_area_ambiente_id", "equipos", ["area_ambiente_id"])

    with op.batch_alter_table("equipo_documentos") as batch:
        batch.add_column(sa.Column("documento_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("documento_version_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("vinculado_por_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("observaciones", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_equipo_documentos_documento_id", "documentos", ["documento_id"], ["id"])
        batch.create_foreign_key("fk_equipo_documentos_documento_version_id", "documento_versiones", ["documento_version_id"], ["id"])
        batch.create_foreign_key("fk_equipo_documentos_vinculado_por_id", "usuarios", ["vinculado_por_id"], ["id"])
        batch.create_unique_constraint("uq_equipo_documento_version", ["equipo_id", "documento_version_id"])
    op.create_index("ix_equipo_documentos_equipo_id", "equipo_documentos", ["equipo_id"])
    op.create_index("ix_equipo_documentos_documento_id", "equipo_documentos", ["documento_id"])
    op.create_index("ix_equipo_documentos_documento_version_id", "equipo_documentos", ["documento_version_id"])

    op.create_table(
        "equipo_historial",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("equipo_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_evento", sa.String(length=40), nullable=False),
        sa.Column("estado_anterior", sa.String(length=100), nullable=True),
        sa.Column("estado_nuevo", sa.String(length=100), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "tipo_evento IN ('CREACION', 'ACTUALIZACION', 'CAMBIO_UBICACION', 'CAMBIO_RESPONSABLE', 'CAMBIO_ESTADO_OPERATIVO', 'RETIRO', 'REACTIVACION', 'VINCULO_DOCUMENTO')",
            name="ck_equipo_historial_tipo_evento_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["equipo_id"], ["equipos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipo_historial_empresa_id", "equipo_historial", ["empresa_id"])
    op.create_index("ix_equipo_historial_equipo_id", "equipo_historial", ["equipo_id"])
    op.create_index("ix_equipo_historial_tipo_evento", "equipo_historial", ["tipo_evento"])

    _seed_permissions()


def downgrade():
    _delete_permissions()

    op.drop_index("ix_equipo_historial_tipo_evento", table_name="equipo_historial")
    op.drop_index("ix_equipo_historial_equipo_id", table_name="equipo_historial")
    op.drop_index("ix_equipo_historial_empresa_id", table_name="equipo_historial")
    op.drop_table("equipo_historial")

    op.drop_index("ix_equipo_documentos_documento_version_id", table_name="equipo_documentos")
    op.drop_index("ix_equipo_documentos_documento_id", table_name="equipo_documentos")
    op.drop_index("ix_equipo_documentos_equipo_id", table_name="equipo_documentos")
    with op.batch_alter_table("equipo_documentos") as batch:
        batch.drop_constraint("uq_equipo_documento_version", type_="unique")
        batch.drop_constraint("fk_equipo_documentos_vinculado_por_id", type_="foreignkey")
        batch.drop_constraint("fk_equipo_documentos_documento_version_id", type_="foreignkey")
        batch.drop_constraint("fk_equipo_documentos_documento_id", type_="foreignkey")
        batch.drop_column("observaciones")
        batch.drop_column("vinculado_por_id")
        batch.drop_column("documento_version_id")
        batch.drop_column("documento_id")

    op.drop_index("ix_equipos_area_ambiente_id", table_name="equipos")
    op.drop_index("ix_equipos_instalacion_id", table_name="equipos")
    op.drop_index("ix_equipos_estado_operativo", table_name="equipos")
    op.drop_index("ix_equipos_estado", table_name="equipos")
    with op.batch_alter_table("equipos") as batch:
        batch.drop_constraint("ck_equipos_criticidad_valida", type_="check")
        batch.drop_constraint("ck_equipos_estado_operativo_valido", type_="check")
        batch.drop_constraint("fk_equipos_area_ambiente_id", type_="foreignkey")
        batch.drop_constraint("fk_equipos_instalacion_id", type_="foreignkey")
        batch.drop_column("observaciones")
        batch.drop_column("responsable")
        batch.drop_column("requiere_mantenimiento")
        batch.drop_column("estado_operativo")
        batch.drop_column("ubicacion_especifica")
        batch.drop_column("fabricante")
        batch.drop_column("tipo")
        batch.drop_column("area_ambiente_id")
        batch.drop_column("instalacion_id")

    op.drop_index("ix_areas_ambientes_estado", table_name="areas_ambientes")
    op.drop_index("ix_areas_ambientes_instalacion_id", table_name="areas_ambientes")
    op.drop_index("ix_areas_ambientes_empresa_estado", table_name="areas_ambientes")
    op.drop_index("ix_areas_ambientes_empresa_id", table_name="areas_ambientes")
    op.drop_table("areas_ambientes")

    op.drop_index("ix_instalaciones_estado", table_name="instalaciones")
    op.drop_index("ix_instalaciones_empresa_estado", table_name="instalaciones")
    op.drop_index("ix_instalaciones_empresa_id", table_name="instalaciones")
    op.drop_table("instalaciones")


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
    for code, name, module in NEW_PERMISSIONS:
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
            permissions.c.codigo.in_([code for code, _name, _module in NEW_PERMISSIONS])
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
    codes = [code for code, _name, _module in NEW_PERMISSIONS]
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
