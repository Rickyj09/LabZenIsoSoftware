"""Modulo 4A personal cargos perfiles

Revision ID: c8d9e0f1a2b3
Revises: b1c2d3e4f5a6
Create Date: 2026-08-29 00:00:00.000000

"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "c8d9e0f1a2b3"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


PERSONAL_PERMISSIONS = (
    ("personal.ver", "Consultar personal", "personal"),
    ("personal.gestionar", "Administrar personal", "personal"),
)


def upgrade():
    now = datetime.now(timezone.utc)
    connection = op.get_bind()
    default_empresa_id = connection.execute(sa.text("SELECT id FROM empresas ORDER BY id LIMIT 1")).scalar()

    op.add_column("cargos", sa.Column("empresa_id", sa.BigInteger(), nullable=True))
    op.add_column("cargos", sa.Column("codigo", sa.String(length=50), nullable=True))
    op.add_column("cargos", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cargos", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_cargos_empresa_id", "cargos", ["empresa_id"], unique=False)

    op.add_column("personal", sa.Column("empresa_id", sa.BigInteger(), nullable=True))
    op.add_column("personal", sa.Column("codigo", sa.String(length=50), nullable=True))
    op.add_column("personal", sa.Column("nombres", sa.String(length=120), nullable=True))
    op.add_column("personal", sa.Column("apellidos", sa.String(length=120), nullable=True))
    op.add_column("personal", sa.Column("identificacion", sa.String(length=50), nullable=True))
    op.add_column("personal", sa.Column("usuario_id", sa.BigInteger(), nullable=True))
    op.add_column("personal", sa.Column("fecha_ingreso", sa.Date(), nullable=True))
    op.add_column("personal", sa.Column("fecha_salida", sa.Date(), nullable=True))
    op.add_column("personal", sa.Column("estado", sa.String(length=20), nullable=True))
    op.add_column("personal", sa.Column("observaciones", sa.Text(), nullable=True))
    op.add_column("personal", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("personal", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_personal_empresa_id", "personal", ["empresa_id"], unique=False)

    if default_empresa_id is not None:
        connection.execute(sa.text("UPDATE cargos SET empresa_id = :empresa_id WHERE empresa_id IS NULL"), {"empresa_id": default_empresa_id})
        connection.execute(sa.text("UPDATE personal SET empresa_id = :empresa_id WHERE empresa_id IS NULL"), {"empresa_id": default_empresa_id})

    connection.execute(sa.text("UPDATE cargos SET codigo = 'CARGO-' || CAST(id AS VARCHAR) WHERE codigo IS NULL"))
    connection.execute(sa.text("UPDATE cargos SET activo = COALESCE(activo, TRUE), created_at = COALESCE(created_at, :now), updated_at = COALESCE(updated_at, :now)"), {"now": now})
    connection.execute(sa.text(
        "UPDATE personal SET codigo = 'PER-' || CAST(id AS VARCHAR), nombres = COALESCE(nombre, 'Sin nombre'), "
        "apellidos = '', estado = CASE WHEN COALESCE(activo, TRUE) THEN 'ACTIVO' ELSE 'INACTIVO' END, "
        "created_at = COALESCE(created_at, :now), updated_at = COALESCE(updated_at, :now) WHERE codigo IS NULL"
    ), {"now": now})

    with op.batch_alter_table("cargos") as batch:
        batch.alter_column("empresa_id", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("codigo", existing_type=sa.String(length=50), nullable=False)
        batch.alter_column("activo", existing_type=sa.Boolean(), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.create_foreign_key("fk_cargos_empresa_id_empresas", "empresas", ["empresa_id"], ["id"])
        batch.create_unique_constraint("uq_cargos_empresa_codigo", ["empresa_id", "codigo"])
        batch.create_unique_constraint("uq_cargos_empresa_nombre", ["empresa_id", "nombre"])

    with op.batch_alter_table("personal") as batch:
        batch.alter_column("empresa_id", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("codigo", existing_type=sa.String(length=50), nullable=False)
        batch.alter_column("nombres", existing_type=sa.String(length=120), nullable=False)
        batch.alter_column("apellidos", existing_type=sa.String(length=120), nullable=False)
        batch.alter_column("estado", existing_type=sa.String(length=20), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.drop_column("activo")
        batch.drop_column("nombre")
        batch.create_foreign_key("fk_personal_empresa_id_empresas", "empresas", ["empresa_id"], ["id"])
        batch.create_foreign_key("fk_personal_usuario_id_usuarios", "usuarios", ["usuario_id"], ["id"])
        batch.create_check_constraint("ck_personal_estado_valido", "estado IN ('ACTIVO', 'INACTIVO')")
        batch.create_check_constraint(
            "ck_personal_fechas_ordenadas",
            "fecha_salida IS NULL OR fecha_ingreso IS NULL OR fecha_salida >= fecha_ingreso",
        )
        batch.create_unique_constraint("uq_personal_empresa_codigo", ["empresa_id", "codigo"])
        batch.create_unique_constraint("uq_personal_empresa_identificacion", ["empresa_id", "identificacion"])
        batch.create_unique_constraint("uq_personal_empresa_usuario", ["empresa_id", "usuario_id"])

    op.create_index("ix_cargos_empresa_activo", "cargos", ["empresa_id", "activo"], unique=False)
    op.create_index("ix_personal_empresa_estado", "personal", ["empresa_id", "estado"], unique=False)
    op.create_index("ix_personal_empresa_cargo", "personal", ["empresa_id", "cargo_id"], unique=False)

    op.create_table(
        "perfiles_puesto",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("cargo_id", sa.Integer(), nullable=False),
        sa.Column("proposito", sa.Text(), nullable=True),
        sa.Column("funciones", sa.Text(), nullable=True),
        sa.Column("responsabilidades", sa.Text(), nullable=True),
        sa.Column("autoridad", sa.Text(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["cargo_id"], ["cargos.id"], name="fk_perfiles_puesto_cargo_id_cargos"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_perfiles_puesto_empresa_id_empresas"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "cargo_id", name="uq_perfiles_puesto_empresa_cargo"),
    )
    op.create_index("ix_perfiles_puesto_empresa_id", "perfiles_puesto", ["empresa_id"], unique=False)
    op.create_index("ix_perfiles_puesto_empresa_activo", "perfiles_puesto", ["empresa_id", "activo"], unique=False)

    _seed_permissions(connection)


def downgrade():
    connection = op.get_bind()
    _delete_permissions(connection)

    op.drop_index("ix_perfiles_puesto_empresa_activo", table_name="perfiles_puesto")
    op.drop_index("ix_perfiles_puesto_empresa_id", table_name="perfiles_puesto")
    op.drop_table("perfiles_puesto")

    op.drop_index("ix_personal_empresa_cargo", table_name="personal")
    op.drop_index("ix_personal_empresa_estado", table_name="personal")
    op.drop_index("ix_cargos_empresa_activo", table_name="cargos")

    op.add_column("personal", sa.Column("nombre", sa.String(length=150), nullable=True))
    op.add_column("personal", sa.Column("activo", sa.Boolean(), nullable=True))
    connection.execute(sa.text(
        "UPDATE personal SET nombre = TRIM(COALESCE(nombres, '') || ' ' || COALESCE(apellidos, '')), "
        "activo = CASE WHEN estado = 'ACTIVO' THEN TRUE ELSE FALSE END"
    ))

    op.drop_index("ix_personal_empresa_id", table_name="personal")

    with op.batch_alter_table("personal") as batch:
        batch.drop_constraint("uq_personal_empresa_usuario", type_="unique")
        batch.drop_constraint("uq_personal_empresa_identificacion", type_="unique")
        batch.drop_constraint("uq_personal_empresa_codigo", type_="unique")
        batch.drop_constraint("ck_personal_fechas_ordenadas", type_="check")
        batch.drop_constraint("ck_personal_estado_valido", type_="check")
        batch.drop_constraint("fk_personal_usuario_id_usuarios", type_="foreignkey")
        batch.drop_constraint("fk_personal_empresa_id_empresas", type_="foreignkey")
        batch.alter_column("nombre", existing_type=sa.String(length=150), nullable=False)
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("observaciones")
        batch.drop_column("estado")
        batch.drop_column("fecha_salida")
        batch.drop_column("fecha_ingreso")
        batch.drop_column("usuario_id")
        batch.drop_column("identificacion")
        batch.drop_column("apellidos")
        batch.drop_column("nombres")
        batch.drop_column("codigo")
        batch.drop_column("empresa_id")

    op.drop_index("ix_cargos_empresa_id", table_name="cargos")

    with op.batch_alter_table("cargos") as batch:
        batch.drop_constraint("uq_cargos_empresa_nombre", type_="unique")
        batch.drop_constraint("uq_cargos_empresa_codigo", type_="unique")
        batch.drop_constraint("fk_cargos_empresa_id_empresas", type_="foreignkey")
        batch.alter_column("activo", existing_type=sa.Boolean(), nullable=True)
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("codigo")
        batch.drop_column("empresa_id")


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
    roles = sa.table("roles", sa.column("id", sa.BigInteger), sa.column("nombre", sa.String))
    role_permissions = sa.table(
        "rol_permisos",
        sa.column("rol_id", sa.BigInteger),
        sa.column("permiso_id", sa.BigInteger),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    for code, name, module in PERSONAL_PERMISSIONS:
        exists = connection.execute(sa.select(permissions.c.id).where(permissions.c.codigo == code)).scalar()
        if not exists:
            now = datetime.now(timezone.utc)
            connection.execute(permissions.insert().values(
                codigo=code,
                nombre=name,
                descripcion=name,
                modulo=module,
                created_at=now,
                updated_at=now,
            ))

    permission_rows = connection.execute(
        sa.select(permissions.c.id, permissions.c.codigo).where(
            permissions.c.codigo.in_([code for code, _name, _module in PERSONAL_PERMISSIONS])
        )
    ).fetchall()
    permission_ids = {row.codigo: row.id for row in permission_rows}
    role_rows = connection.execute(
        sa.select(roles.c.id, roles.c.nombre).where(roles.c.nombre.in_(["ADMINISTRADOR", "CALIDAD", "TECNICO", "CONSULTA"]))
    ).fetchall()

    for role in role_rows:
        codes = ["personal.ver", "personal.gestionar"] if role.nombre in {"ADMINISTRADOR", "CALIDAD"} else ["personal.ver"]
        for code in codes:
            exists = connection.execute(
                sa.select(role_permissions.c.rol_id).where(
                    role_permissions.c.rol_id == role.id,
                    role_permissions.c.permiso_id == permission_ids[code],
                )
            ).scalar()
            if not exists:
                now = datetime.now(timezone.utc)
                connection.execute(role_permissions.insert().values(
                    rol_id=role.id,
                    permiso_id=permission_ids[code],
                    created_at=now,
                    updated_at=now,
                ))


def _delete_permissions(connection):
    permission_codes = [code for code, _name, _module in PERSONAL_PERMISSIONS]
    permission_ids = connection.execute(
        sa.text("SELECT id FROM permisos WHERE codigo IN :codes").bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": permission_codes},
    ).scalars().all()
    if permission_ids:
        connection.execute(
            sa.text("DELETE FROM rol_permisos WHERE permiso_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": permission_ids},
        )
        connection.execute(
            sa.text("DELETE FROM permisos WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": permission_ids},
        )
