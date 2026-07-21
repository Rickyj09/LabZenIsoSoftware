"""Carpetas documentales para explorador

Revision ID: f7b2c3d4e5f6
Revises: f6a1b2c3d4e5
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "f7b2c3d4e5f6"
down_revision = "f6a1b2c3d4e5"
branch_labels = None
depends_on = None


FOLDER_PERMISSIONS = (
    ("documentos.carpetas.crear", "Crear carpetas documentales"),
    ("documentos.carpetas.editar", "Editar carpetas documentales"),
    ("documentos.carpetas.eliminar", "Eliminar carpetas documentales"),
    ("documentos.carpetas.mover_documentos", "Mover documentos entre carpetas"),
)


ROLE_PERMISSION_CODES = {
    "ADMINISTRADOR": {code for code, _name in FOLDER_PERMISSIONS},
    "CALIDAD": {code for code, _name in FOLDER_PERMISSIONS},
    "TECNICO": {"documentos.carpetas.crear", "documentos.carpetas.editar", "documentos.carpetas.mover_documentos"},
}


def _seed_permissions(connection):
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
    roles = sa.table(
        "roles",
        sa.column("id", sa.BigInteger),
        sa.column("nombre", sa.String),
    )
    role_permissions = sa.table(
        "rol_permisos",
        sa.column("rol_id", sa.BigInteger),
        sa.column("permiso_id", sa.BigInteger),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for code, name in FOLDER_PERMISSIONS:
        exists = connection.execute(sa.select(permissions.c.id).where(permissions.c.codigo == code)).scalar()
        if not exists:
            connection.execute(permissions.insert().values(
                codigo=code,
                nombre=name,
                descripcion=name,
                modulo="documentos",
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            ))

    permission_rows = connection.execute(
        sa.select(permissions.c.id, permissions.c.codigo)
        .where(permissions.c.codigo.in_([code for code, _name in FOLDER_PERMISSIONS]))
    ).all()
    permission_ids = {row.codigo: row.id for row in permission_rows}
    role_rows = connection.execute(sa.select(roles.c.id, roles.c.nombre)).all()
    for role in role_rows:
        normalized_name = (role.nombre or "").strip().upper()
        codes = ROLE_PERMISSION_CODES.get(normalized_name)
        if normalized_name in {"ADMIN", "SUPERADMIN"}:
            codes = ROLE_PERMISSION_CODES["ADMINISTRADOR"]
        if not codes:
            continue
        for code in codes:
            permission_id = permission_ids[code]
            exists = connection.execute(
                sa.select(role_permissions.c.rol_id).where(
                    role_permissions.c.rol_id == role.id,
                    role_permissions.c.permiso_id == permission_id,
                )
            ).scalar()
            if not exists:
                connection.execute(role_permissions.insert().values(
                    rol_id=role.id,
                    permiso_id=permission_id,
                    created_at=sa.func.now(),
                    updated_at=sa.func.now(),
                ))


def upgrade():
    op.create_table(
        "carpetas_documentales",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("padre_id", sa.BigInteger(), nullable=True),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("creada_por_id", sa.BigInteger(), nullable=False),
        sa.Column("actualizada_por_id", sa.BigInteger(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("id <> padre_id", name="ck_carpetas_documentales_no_autopadre"),
        sa.ForeignKeyConstraint(["actualizada_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["creada_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["padre_id"], ["carpetas_documentales.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_carpetas_documentales_public_id"),
        sa.UniqueConstraint("empresa_id", "padre_id", "nombre", name="uq_carpetas_documentales_empresa_padre_nombre"),
    )
    op.create_index("ix_carpetas_documentales_activa", "carpetas_documentales", ["activa"], unique=False)
    op.create_index("ix_carpetas_documentales_empresa_id", "carpetas_documentales", ["empresa_id"], unique=False)
    op.create_index("ix_carpetas_documentales_empresa_padre", "carpetas_documentales", ["empresa_id", "padre_id"], unique=False)
    op.create_index("ix_carpetas_documentales_orden", "carpetas_documentales", ["orden"], unique=False)
    op.create_index("ix_carpetas_documentales_padre_id", "carpetas_documentales", ["padre_id"], unique=False)
    op.add_column("documentos", sa.Column("carpeta_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_documentos_carpeta_id", "documentos", "carpetas_documentales", ["carpeta_id"], ["id"])
    op.create_index("ix_documentos_carpeta_id", "documentos", ["carpeta_id"], unique=False)
    _seed_permissions(op.get_bind())


def downgrade():
    connection = op.get_bind()
    permission_codes = [code for code, _name in FOLDER_PERMISSIONS]
    permission_ids = connection.execute(
        sa.text("SELECT id FROM permisos WHERE codigo IN :codes")
        .bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": permission_codes},
    ).scalars().all()
    if permission_ids:
        connection.execute(
            sa.text("DELETE FROM rol_permisos WHERE permiso_id IN :ids")
            .bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": permission_ids},
        )
        connection.execute(
            sa.text("DELETE FROM permisos WHERE id IN :ids")
            .bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": permission_ids},
        )
    op.drop_index("ix_documentos_carpeta_id", table_name="documentos")
    op.drop_constraint("fk_documentos_carpeta_id", "documentos", type_="foreignkey")
    op.drop_column("documentos", "carpeta_id")
    op.drop_index("ix_carpetas_documentales_padre_id", table_name="carpetas_documentales")
    op.drop_index("ix_carpetas_documentales_orden", table_name="carpetas_documentales")
    op.drop_index("ix_carpetas_documentales_empresa_padre", table_name="carpetas_documentales")
    op.drop_index("ix_carpetas_documentales_empresa_id", table_name="carpetas_documentales")
    op.drop_index("ix_carpetas_documentales_activa", table_name="carpetas_documentales")
    op.drop_table("carpetas_documentales")
