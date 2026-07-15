"""onlyoffice edicion controlada

Revision ID: a7c9e4d2f6b1
Revises: f4b8d2c9a1e7
Create Date: 2026-07-14 23:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a7c9e4d2f6b1"
down_revision = "f4b8d2c9a1e7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documento_ediciones",
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("editor_key", sa.String(length=128), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultima_actividad", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fecha_expiracion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fecha_liberacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("liberado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("motivo_liberacion", sa.Text(), nullable=True),
        sa.Column("hash_inicial", sa.String(length=64), nullable=False),
        sa.Column("hash_ultimo_guardado", sa.String(length=64), nullable=True),
        sa.Column("ultimo_guardado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_callback_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_callback_status", sa.Integer(), nullable=True),
        sa.Column("ultimo_callback_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("error_ultimo_guardado", sa.Text(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "estado IN ('ACTIVA', 'LIBERADA', 'EXPIRADA', 'ERROR', 'CANCELADA')",
            name="ck_documento_ediciones_estado_valido",
        ),
        sa.CheckConstraint(
            "fecha_expiracion > fecha_inicio",
            name="ck_documento_ediciones_expiracion_posterior_inicio",
        ),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["liberado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("editor_key", name="uq_documento_ediciones_editor_key"),
        sa.UniqueConstraint("public_id", name="uq_documento_ediciones_public_id"),
    )
    op.create_index("ix_documento_ediciones_documento_id", "documento_ediciones", ["documento_id"])
    op.create_index("ix_documento_ediciones_documento_version_id", "documento_ediciones", ["documento_version_id"])
    op.create_index("ix_documento_ediciones_empresa_id", "documento_ediciones", ["empresa_id"])
    op.create_index("ix_documento_ediciones_estado", "documento_ediciones", ["estado"])
    op.create_index("ix_documento_ediciones_fecha_expiracion", "documento_ediciones", ["fecha_expiracion"])
    op.create_index("ix_documento_ediciones_usuario_id", "documento_ediciones", ["usuario_id"])
    op.create_index(
        "uq_documento_ediciones_version_activa",
        "documento_ediciones",
        ["documento_version_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'ACTIVA'"),
        sqlite_where=sa.text("estado = 'ACTIVA'"),
    )

    op.create_table(
        "documento_edicion_eventos",
        sa.Column("edicion_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("tipo", sa.String(length=50), nullable=False),
        sa.Column("fecha_evento", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_callback", sa.Integer(), nullable=True),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["edicion_id"], ["documento_ediciones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_documento_edicion_eventos_fingerprint"),
    )
    op.create_index("ix_documento_edicion_eventos_edicion_id", "documento_edicion_eventos", ["edicion_id"])
    op.create_index("ix_documento_edicion_eventos_empresa_id", "documento_edicion_eventos", ["empresa_id"])
    op.create_index("ix_documento_edicion_eventos_fecha_evento", "documento_edicion_eventos", ["fecha_evento"])
    op.create_index("ix_documento_edicion_eventos_tipo", "documento_edicion_eventos", ["tipo"])


def downgrade():
    op.drop_index("ix_documento_edicion_eventos_tipo", table_name="documento_edicion_eventos")
    op.drop_index("ix_documento_edicion_eventos_fecha_evento", table_name="documento_edicion_eventos")
    op.drop_index("ix_documento_edicion_eventos_empresa_id", table_name="documento_edicion_eventos")
    op.drop_index("ix_documento_edicion_eventos_edicion_id", table_name="documento_edicion_eventos")
    op.drop_table("documento_edicion_eventos")

    op.drop_index("uq_documento_ediciones_version_activa", table_name="documento_ediciones")
    op.drop_index("ix_documento_ediciones_usuario_id", table_name="documento_ediciones")
    op.drop_index("ix_documento_ediciones_fecha_expiracion", table_name="documento_ediciones")
    op.drop_index("ix_documento_ediciones_estado", table_name="documento_ediciones")
    op.drop_index("ix_documento_ediciones_empresa_id", table_name="documento_ediciones")
    op.drop_index("ix_documento_ediciones_documento_version_id", table_name="documento_ediciones")
    op.drop_index("ix_documento_ediciones_documento_id", table_name="documento_ediciones")
    op.drop_table("documento_ediciones")
