"""Asignar revision documental al rol administrador

Revision ID: c9f1e2d3a4b5
Revises: 2b3c4d5e6f7a
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "c9f1e2d3a4b5"
down_revision = "2b3c4d5e6f7a"
branch_labels = None
depends_on = None


ADMIN_ROLE_NAMES = ("ADMINISTRADOR", "ADMIN", "SUPERADMIN")
PERMISSION_CODE = "documentos.revisar"


def upgrade():
    connection = op.get_bind()
    permission_id = connection.execute(
        sa.text("SELECT id FROM permisos WHERE codigo = :codigo"),
        {"codigo": PERMISSION_CODE},
    ).scalar()
    if not permission_id:
        connection.execute(
            sa.text(
                """
                INSERT INTO permisos (codigo, nombre, descripcion, modulo, created_at, updated_at)
                VALUES (:codigo, :nombre, :descripcion, :modulo, now(), now())
                """
            ),
            {
                "codigo": PERMISSION_CODE,
                "nombre": "Revisar documentos",
                "descripcion": "Revisar documentos",
                "modulo": "documentos",
            },
        )
        permission_id = connection.execute(
            sa.text("SELECT id FROM permisos WHERE codigo = :codigo"),
            {"codigo": PERMISSION_CODE},
        ).scalar_one()

    role_ids = connection.execute(
        sa.text("SELECT id FROM roles WHERE UPPER(nombre) IN :names").bindparams(
            sa.bindparam("names", expanding=True)
        ),
        {"names": ADMIN_ROLE_NAMES},
    ).scalars().all()

    for role_id in role_ids:
        exists = connection.execute(
            sa.text(
                """
                SELECT 1
                FROM rol_permisos
                WHERE rol_id = :role_id AND permiso_id = :permission_id
                """
            ),
            {"role_id": role_id, "permission_id": permission_id},
        ).scalar()
        if not exists:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO rol_permisos (rol_id, permiso_id, created_at, updated_at)
                    VALUES (:role_id, :permission_id, now(), now())
                    """
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )


def downgrade():
    connection = op.get_bind()
    permission_id = connection.execute(
        sa.text("SELECT id FROM permisos WHERE codigo = :codigo"),
        {"codigo": PERMISSION_CODE},
    ).scalar()
    if not permission_id:
        return
    connection.execute(
        sa.text(
            """
            DELETE FROM rol_permisos
            WHERE permiso_id = :permission_id
              AND rol_id IN (
                  SELECT id FROM roles WHERE UPPER(nombre) IN :names
              )
            """
        ).bindparams(sa.bindparam("names", expanding=True)),
        {"permission_id": permission_id, "names": ADMIN_ROLE_NAMES},
    )
