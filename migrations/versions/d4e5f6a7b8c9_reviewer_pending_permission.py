"""Asignar pendientes documentales al rol revisor

Revision ID: d4e5f6a7b8c9
Revises: c9f1e2d3a4b5
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c9f1e2d3a4b5"
branch_labels = None
depends_on = None


ROLE_NAME = "REVISOR_DOCUMENTAL"
PERMISSION_CODE = "documentos.ver_pendientes"


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
                "nombre": "Ver pendientes documentales",
                "descripcion": "Ver pendientes documentales",
                "modulo": "documentos",
            },
        )
        permission_id = connection.execute(
            sa.text("SELECT id FROM permisos WHERE codigo = :codigo"),
            {"codigo": PERMISSION_CODE},
        ).scalar_one()

    role_id = connection.execute(
        sa.text("SELECT id FROM roles WHERE UPPER(nombre) = :nombre"),
        {"nombre": ROLE_NAME},
    ).scalar()
    if not role_id:
        return

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
    role_id = connection.execute(
        sa.text("SELECT id FROM roles WHERE UPPER(nombre) = :nombre"),
        {"nombre": ROLE_NAME},
    ).scalar()
    if not permission_id or not role_id:
        return

    connection.execute(
        sa.text(
            """
            DELETE FROM rol_permisos
            WHERE rol_id = :role_id AND permiso_id = :permission_id
            """
        ),
        {"role_id": role_id, "permission_id": permission_id},
    )
