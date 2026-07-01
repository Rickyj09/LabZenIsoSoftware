"""workflow documental auditable

Revision ID: d6f4a2b98c10
Revises: c3d8a1f42e76
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "d6f4a2b98c10"
down_revision = "c3d8a1f42e76"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documento_versiones", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rechazado_por_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("obsoletado_por_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("comentario_revision", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("comentario_aprobacion", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("comentario_rechazo", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("motivo_obsolescencia", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_documento_versiones_rechazado_por_id",
            "usuarios",
            ["rechazado_por_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_documento_versiones_obsoletado_por_id",
            "usuarios",
            ["obsoletado_por_id"],
            ["id"],
        )

    with op.batch_alter_table("documento_aprobaciones", schema=None) as batch_op:
        batch_op.add_column(sa.Column("documento_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("estado_anterior", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("estado_nuevo", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("ip", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("user_agent", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_documento_eventos_documento_id",
            "documentos",
            ["documento_id"],
            ["id"],
        )

    op.execute(sa.text("""
        UPDATE documento_aprobaciones AS evento
        SET documento_id = version.documento_id,
            accion = CASE evento.accion
                WHEN 'APROBADO' THEN 'APROBAR'
                WHEN 'EN_REVISION' THEN 'ENVIAR_REVISION'
                WHEN 'OBSOLETO' THEN 'OBSOLETAR'
                ELSE evento.accion
            END,
            estado_nuevo = CASE evento.accion
                WHEN 'APROBADO' THEN 'APROBADO'
                WHEN 'EN_REVISION' THEN 'EN_REVISION'
                WHEN 'OBSOLETO' THEN 'OBSOLETO'
                ELSE version.estado
            END
        FROM documento_versiones AS version
        WHERE version.id = evento.documento_version_id
    """))

    with op.batch_alter_table("documento_aprobaciones", schema=None) as batch_op:
        batch_op.alter_column("documento_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.alter_column("estado_nuevo", existing_type=sa.String(length=30), nullable=False)
        batch_op.create_check_constraint(
            "ck_documento_eventos_accion_valida",
            "accion IN ('CREAR_VERSION', 'ENVIAR_REVISION', 'APROBAR', 'RECHAZAR', 'DEVOLVER_BORRADOR', 'OBSOLETAR', 'SUSTITUIR_VERSION')",
        )
        batch_op.create_index("ix_documento_eventos_documento_id", ["documento_id"], unique=False)
        batch_op.create_index("ix_documento_eventos_accion", ["accion"], unique=False)


def downgrade():
    with op.batch_alter_table("documento_aprobaciones", schema=None) as batch_op:
        batch_op.drop_index("ix_documento_eventos_accion")
        batch_op.drop_index("ix_documento_eventos_documento_id")
        batch_op.drop_constraint("ck_documento_eventos_accion_valida", type_="check")
        batch_op.drop_constraint("fk_documento_eventos_documento_id", type_="foreignkey")
        batch_op.drop_column("user_agent")
        batch_op.drop_column("ip")
        batch_op.drop_column("estado_nuevo")
        batch_op.drop_column("estado_anterior")
        batch_op.drop_column("documento_id")

    with op.batch_alter_table("documento_versiones", schema=None) as batch_op:
        batch_op.drop_constraint("fk_documento_versiones_obsoletado_por_id", type_="foreignkey")
        batch_op.drop_constraint("fk_documento_versiones_rechazado_por_id", type_="foreignkey")
        batch_op.drop_column("motivo_obsolescencia")
        batch_op.drop_column("comentario_rechazo")
        batch_op.drop_column("comentario_aprobacion")
        batch_op.drop_column("comentario_revision")
        batch_op.drop_column("obsoletado_por_id")
        batch_op.drop_column("rechazado_por_id")
