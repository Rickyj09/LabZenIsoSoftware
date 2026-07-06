"""permisos documentales y roles

Revision ID: e8a4c7d91f20
Revises: d6f4a2b98c10
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa


revision = "e8a4c7d91f20"
down_revision = "d6f4a2b98c10"
branch_labels = None
depends_on = None


PERMISSIONS = (
    ("documentos.ver", "Ver documentos"),
    ("documentos.crear", "Crear documentos"),
    ("documentos.editar", "Editar documentos"),
    ("documentos.enviar_revision", "Enviar documentos a revisión"),
    ("documentos.aprobar", "Aprobar documentos"),
    ("documentos.rechazar", "Rechazar documentos"),
    ("documentos.devolver_borrador", "Devolver documentos a borrador"),
    ("documentos.obsoletar", "Obsoletar documentos"),
    ("documentos.descargar", "Descargar documentos"),
    ("documentos.ver_historial", "Ver historial documental"),
    ("documentos.ver_pendientes", "Ver pendientes documentales"),
)

ROLE_PERMISSIONS = {
    "ADMINISTRADOR": {code for code, _ in PERMISSIONS},
    "CALIDAD": {code for code, _ in PERMISSIONS},
    "TECNICO": {
        "documentos.ver",
        "documentos.crear",
        "documentos.editar",
        "documentos.enviar_revision",
        "documentos.descargar",
        "documentos.ver_historial",
    },
    "CONSULTA": {"documentos.ver", "documentos.descargar"},
}


def upgrade():
    connection = op.get_bind()
    roles = sa.table(
        "roles",
        sa.column("id", sa.BigInteger),
        sa.column("nombre", sa.String),
        sa.column("descripcion", sa.Text),
        sa.column("es_sistema", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
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
    role_permissions = sa.table(
        "rol_permisos",
        sa.column("rol_id", sa.BigInteger),
        sa.column("permiso_id", sa.BigInteger),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    user_roles = sa.table(
        "usuario_roles",
        sa.column("usuario_id", sa.BigInteger),
        sa.column("rol_id", sa.BigInteger),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    users = sa.table(
        "usuarios",
        sa.column("id", sa.BigInteger),
        sa.column("username", sa.String),
    )

    for role_name in ROLE_PERMISSIONS:
        exists = connection.execute(
            sa.select(roles.c.id).where(sa.func.upper(roles.c.nombre) == role_name)
        ).scalar()
        if not exists:
            connection.execute(roles.insert().values(
                nombre=role_name,
                descripcion=f"Rol de sistema {role_name}",
                es_sistema=True,
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            ))

    for code, name in PERMISSIONS:
        exists = connection.execute(
            sa.select(permissions.c.id).where(permissions.c.codigo == code)
        ).scalar()
        if not exists:
            connection.execute(permissions.insert().values(
                codigo=code,
                nombre=name,
                descripcion=name,
                modulo="documentos",
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            ))

    role_rows = connection.execute(sa.select(roles.c.id, roles.c.nombre)).all()
    permission_rows = connection.execute(
        sa.select(permissions.c.id, permissions.c.codigo)
        .where(permissions.c.codigo.in_([code for code, _ in PERMISSIONS]))
    ).all()
    permission_ids = {row.codigo: row.id for row in permission_rows}

    for role in role_rows:
        normalized_name = role.nombre.strip().upper()
        codes = ROLE_PERMISSIONS.get(normalized_name)
        if normalized_name in {"ADMIN", "SUPERADMIN"}:
            codes = ROLE_PERMISSIONS["ADMINISTRADOR"]
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

    administrator_id = connection.execute(
        sa.select(roles.c.id).where(sa.func.upper(roles.c.nombre) == "ADMINISTRADOR")
    ).scalar_one()
    admin_users = connection.execute(
        sa.select(users.c.id).where(sa.func.lower(users.c.username) == "admin")
    ).all()
    for admin_user in admin_users:
        has_role = connection.execute(
            sa.select(user_roles.c.usuario_id).where(user_roles.c.usuario_id == admin_user.id)
        ).scalar()
        if not has_role:
            connection.execute(user_roles.insert().values(
                usuario_id=admin_user.id,
                rol_id=administrator_id,
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            ))


def downgrade():
    connection = op.get_bind()
    permission_ids = connection.execute(sa.text(
        "SELECT id FROM permisos WHERE codigo LIKE 'documentos.%'"
    )).scalars().all()
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
