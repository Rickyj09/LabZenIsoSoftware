"""separar revision tecnica y aprobacion documental

Revision ID: a2b3c4d5e6f7
Revises: f1c2d3e4a5b6
Create Date: 2026-07-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a2b3c4d5e6f7"
down_revision = "f1c2d3e4a5b6"
branch_labels = None
depends_on = None


DOCUMENTOS_ESTADOS = "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')"
VERSIONES_ESTADOS = (
    "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')"
)
DOCUMENTOS_ESTADOS_ANTERIOR = "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')"
VERSIONES_ESTADOS_ANTERIOR = (
    "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')"
)
ACCIONES = (
    "accion IN ('CREAR_VERSION', 'ENVIAR_REVISION', 'DAR_CONFORMIDAD', 'APROBAR', 'RECHAZAR', "
    "'SOLICITAR_CORRECCIONES', 'RECHAZAR_APROBACION', 'DEVOLVER_BORRADOR', 'OBSOLETAR', 'SUSTITUIR_VERSION')"
)
ACCIONES_ANTERIOR = (
    "accion IN ('CREAR_VERSION', 'ENVIAR_REVISION', 'APROBAR', 'RECHAZAR', "
    "'DEVOLVER_BORRADOR', 'OBSOLETAR', 'SUSTITUIR_VERSION')"
)


def _ensure_permission(connection, code, name):
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
    permission_id = connection.execute(sa.select(permissions.c.id).where(permissions.c.codigo == code)).scalar()
    if permission_id:
        return permission_id
    connection.execute(permissions.insert().values(
        codigo=code,
        nombre=name,
        descripcion=name,
        modulo="documentos",
        created_at=sa.func.now(),
        updated_at=sa.func.now(),
    ))
    return connection.execute(sa.select(permissions.c.id).where(permissions.c.codigo == code)).scalar_one()


def _ensure_role(connection, name):
    roles = sa.table(
        "roles",
        sa.column("id", sa.BigInteger),
        sa.column("nombre", sa.String),
        sa.column("descripcion", sa.Text),
        sa.column("es_sistema", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    role_id = connection.execute(sa.select(roles.c.id).where(sa.func.upper(roles.c.nombre) == name)).scalar()
    if role_id:
        return role_id
    connection.execute(roles.insert().values(
        nombre=name,
        descripcion=f"Rol de sistema {name}",
        es_sistema=True,
        created_at=sa.func.now(),
        updated_at=sa.func.now(),
    ))
    return connection.execute(sa.select(roles.c.id).where(sa.func.upper(roles.c.nombre) == name)).scalar_one()


def _link_role_permission(connection, role_id, permission_id):
    role_permissions = sa.table(
        "rol_permisos",
        sa.column("rol_id", sa.BigInteger),
        sa.column("permiso_id", sa.BigInteger),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    exists = connection.execute(
        sa.select(role_permissions.c.rol_id).where(
            role_permissions.c.rol_id == role_id,
            role_permissions.c.permiso_id == permission_id,
        )
    ).scalar()
    if not exists:
        connection.execute(role_permissions.insert().values(
            rol_id=role_id,
            permiso_id=permission_id,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        ))


def upgrade():
    connection = op.get_bind()
    op.drop_index("uq_documento_version_preparacion_activa", table_name="documento_versiones")
    with op.batch_alter_table("documento_versiones") as batch:
        batch.drop_constraint("ck_documento_versiones_estado_valido", type_="check")
        batch.add_column(sa.Column("fecha_revision", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_documento_versiones_estado_valido", VERSIONES_ESTADOS)
    with op.batch_alter_table("documentos") as batch:
        batch.drop_constraint("ck_documentos_estado_valido", type_="check")
        batch.create_check_constraint("ck_documentos_estado_valido", DOCUMENTOS_ESTADOS)
    with op.batch_alter_table("documento_aprobaciones") as batch:
        batch.drop_constraint("ck_documento_eventos_accion_valida", type_="check")
        batch.create_check_constraint("ck_documento_eventos_accion_valida", ACCIONES)
    op.create_index(
        "uq_documento_version_preparacion_activa",
        "documento_versiones",
        ["documento_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION')"),
        sqlite_where=sa.text("estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION')"),
    )

    permission_ids = {
        code: _ensure_permission(connection, code, name)
        for code, name in (
            ("documentos.ver", "Ver documentos"),
            ("documentos.descargar", "Descargar documentos"),
            ("documentos.ver_historial", "Ver historial documental"),
            ("documentos.revisar", "Revisar documentos"),
        )
    }
    reviewer_role_id = _ensure_role(connection, "REVISOR_DOCUMENTAL")
    for permission_id in permission_ids.values():
        _link_role_permission(connection, reviewer_role_id, permission_id)


def downgrade():
    connection = op.get_bind()
    op.drop_index("uq_documento_version_preparacion_activa", table_name="documento_versiones")
    op.execute("UPDATE documento_versiones SET estado = 'EN_REVISION' WHERE estado = 'EN_APROBACION'")
    op.execute("UPDATE documentos SET estado = 'EN_REVISION' WHERE estado = 'EN_APROBACION'")
    op.execute("UPDATE documento_aprobaciones SET estado_anterior = 'EN_REVISION' WHERE estado_anterior = 'EN_APROBACION'")
    op.execute("UPDATE documento_aprobaciones SET estado_nuevo = 'EN_REVISION' WHERE estado_nuevo = 'EN_APROBACION'")
    op.execute("UPDATE documento_aprobaciones SET accion = 'RECHAZAR' WHERE accion = 'RECHAZAR_APROBACION'")
    op.execute("UPDATE documento_aprobaciones SET accion = 'RECHAZAR' WHERE accion = 'SOLICITAR_CORRECCIONES'")
    op.execute("UPDATE documento_aprobaciones SET accion = 'ENVIAR_REVISION' WHERE accion = 'DAR_CONFORMIDAD'")
    with op.batch_alter_table("documento_aprobaciones") as batch:
        batch.drop_constraint("ck_documento_eventos_accion_valida", type_="check")
        batch.create_check_constraint("ck_documento_eventos_accion_valida", ACCIONES_ANTERIOR)
    with op.batch_alter_table("documento_versiones") as batch:
        batch.drop_constraint("ck_documento_versiones_estado_valido", type_="check")
        batch.drop_column("fecha_revision")
        batch.create_check_constraint("ck_documento_versiones_estado_valido", VERSIONES_ESTADOS_ANTERIOR)
    with op.batch_alter_table("documentos") as batch:
        batch.drop_constraint("ck_documentos_estado_valido", type_="check")
        batch.create_check_constraint("ck_documentos_estado_valido", DOCUMENTOS_ESTADOS_ANTERIOR)
    op.create_index(
        "uq_documento_version_preparacion_activa",
        "documento_versiones",
        ["documento_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION')"),
        sqlite_where=sa.text("estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION')"),
    )

    permission_id = connection.execute(sa.text("SELECT id FROM permisos WHERE codigo = 'documentos.revisar'")).scalar()
    role_id = connection.execute(sa.text("SELECT id FROM roles WHERE UPPER(nombre) = 'REVISOR_DOCUMENTAL'")).scalar()
    if permission_id and role_id:
        connection.execute(sa.text("DELETE FROM rol_permisos WHERE rol_id = :role_id AND permiso_id = :permission_id"), {
            "role_id": role_id,
            "permission_id": permission_id,
        })
