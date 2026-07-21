"""permiso gestionar identidades de firma

Revision ID: b4e6f8a1c9d0
Revises: a9d3e7f4b8c2
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa


revision = "b4e6f8a1c9d0"
down_revision = "a9d3e7f4b8c2"
branch_labels = None
depends_on = None


PERMISSION_CODE = "documentos.firmas.identidades.gestionar"
PERMISSION_NAME = "Gestionar identidades de firma documentales"
ROLE_NAMES = ("ADMINISTRADOR", "ADMIN", "SUPERADMIN", "CALIDAD")


def upgrade():
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

    permission_id = connection.execute(
        sa.select(permissions.c.id).where(permissions.c.codigo == PERMISSION_CODE)
    ).scalar()
    if not permission_id:
        connection.execute(permissions.insert().values(
            codigo=PERMISSION_CODE,
            nombre=PERMISSION_NAME,
            descripcion=PERMISSION_NAME,
            modulo="documentos",
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        ))
        permission_id = connection.execute(
            sa.select(permissions.c.id).where(permissions.c.codigo == PERMISSION_CODE)
        ).scalar_one()

    role_rows = connection.execute(sa.select(roles.c.id, roles.c.nombre)).all()
    for role in role_rows:
        if (role.nombre or "").strip().upper() not in ROLE_NAMES:
            continue
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


def downgrade():
    connection = op.get_bind()
    permission_id = connection.execute(
        sa.text("SELECT id FROM permisos WHERE codigo = :codigo"),
        {"codigo": PERMISSION_CODE},
    ).scalar()
    if permission_id:
        connection.execute(sa.text("DELETE FROM rol_permisos WHERE permiso_id = :id"), {"id": permission_id})
        connection.execute(sa.text("DELETE FROM permisos WHERE id = :id"), {"id": permission_id})
