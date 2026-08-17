"""Paquete 5D.1 condiciones ambientales

Revision ID: a7b8c9d0e1f2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "a7b8c9d0e1f2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "area_condiciones_ambientales",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("area_ambiente_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("unidad", sa.String(length=30), nullable=False),
        sa.Column("limite_minimo", sa.Numeric(14, 4), nullable=True),
        sa.Column("limite_maximo", sa.Numeric(14, 4), nullable=True),
        sa.Column("valor_referencia", sa.Numeric(14, 4), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "limite_minimo IS NOT NULL OR limite_maximo IS NOT NULL",
            name="ck_area_condicion_ambiental_limite_requerido",
        ),
        sa.CheckConstraint(
            "limite_minimo IS NULL OR limite_maximo IS NULL OR limite_minimo <= limite_maximo",
            name="ck_area_condicion_ambiental_limites_ordenados",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["area_ambiente_id"], ["areas_ambientes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "area_ambiente_id", "codigo", name="uq_area_condicion_ambiental_codigo"),
    )
    op.create_index("ix_area_condiciones_ambientales_empresa_id", "area_condiciones_ambientales", ["empresa_id"])
    op.create_index(
        "ix_area_condiciones_ambientales_empresa_area",
        "area_condiciones_ambientales",
        ["empresa_id", "area_ambiente_id"],
    )
    op.create_index(
        "ix_area_condiciones_ambientales_empresa_activa",
        "area_condiciones_ambientales",
        ["empresa_id", "activa"],
    )

    op.create_table(
        "area_mediciones_ambientales",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("area_ambiente_id", sa.BigInteger(), nullable=False),
        sa.Column("condicion_ambiental_id", sa.BigInteger(), nullable=False),
        sa.Column("fecha_hora_medicion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valor", sa.Numeric(14, 4), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("limite_minimo_aplicado", sa.Numeric(14, 4), nullable=True),
        sa.Column("limite_maximo_aplicado", sa.Numeric(14, 4), nullable=True),
        sa.Column("unidad_aplicada", sa.String(length=30), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("registrado_por_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("estado IN ('CONFORME', 'FUERA_DE_LIMITE')", name="ck_area_medicion_ambiental_estado_valido"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["area_ambiente_id"], ["areas_ambientes.id"]),
        sa.ForeignKeyConstraint(["condicion_ambiental_id"], ["area_condiciones_ambientales.id"]),
        sa.ForeignKeyConstraint(["registrado_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_area_mediciones_ambientales_empresa_id", "area_mediciones_ambientales", ["empresa_id"])
    op.create_index(
        "ix_area_mediciones_ambientales_empresa_area",
        "area_mediciones_ambientales",
        ["empresa_id", "area_ambiente_id"],
    )
    op.create_index("ix_area_mediciones_ambientales_condicion", "area_mediciones_ambientales", ["condicion_ambiental_id"])
    op.create_index("ix_area_mediciones_ambientales_fecha", "area_mediciones_ambientales", ["fecha_hora_medicion"])
    op.create_index(
        "ix_area_mediciones_ambientales_empresa_estado",
        "area_mediciones_ambientales",
        ["empresa_id", "estado"],
    )

    op.create_table(
        "area_historial_ambiental",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("area_ambiente_id", sa.BigInteger(), nullable=False),
        sa.Column("condicion_ambiental_id", sa.BigInteger(), nullable=True),
        sa.Column("medicion_ambiental_id", sa.BigInteger(), nullable=True),
        sa.Column("tipo_evento", sa.String(length=50), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("datos_antes", sa.JSON(), nullable=True),
        sa.Column("datos_despues", sa.JSON(), nullable=True),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "tipo_evento IN ('CONDICION_AMBIENTAL_CREADA', 'CONDICION_AMBIENTAL_ACTUALIZADA', 'CONDICION_AMBIENTAL_INACTIVADA', 'MEDICION_AMBIENTAL_REGISTRADA', 'MEDICION_AMBIENTAL_FUERA_DE_LIMITE')",
            name="ck_area_historial_ambiental_tipo_evento_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["area_ambiente_id"], ["areas_ambientes.id"]),
        sa.ForeignKeyConstraint(["condicion_ambiental_id"], ["area_condiciones_ambientales.id"]),
        sa.ForeignKeyConstraint(["medicion_ambiental_id"], ["area_mediciones_ambientales.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_area_historial_ambiental_empresa_id", "area_historial_ambiental", ["empresa_id"])
    op.create_index(
        "ix_area_historial_ambiental_empresa_area",
        "area_historial_ambiental",
        ["empresa_id", "area_ambiente_id"],
    )
    op.create_index("ix_area_historial_ambiental_tipo_evento", "area_historial_ambiental", ["tipo_evento"])


def downgrade():
    op.drop_index("ix_area_historial_ambiental_tipo_evento", table_name="area_historial_ambiental")
    op.drop_index("ix_area_historial_ambiental_empresa_area", table_name="area_historial_ambiental")
    op.drop_index("ix_area_historial_ambiental_empresa_id", table_name="area_historial_ambiental")
    op.drop_table("area_historial_ambiental")

    op.drop_index("ix_area_mediciones_ambientales_empresa_estado", table_name="area_mediciones_ambientales")
    op.drop_index("ix_area_mediciones_ambientales_fecha", table_name="area_mediciones_ambientales")
    op.drop_index("ix_area_mediciones_ambientales_condicion", table_name="area_mediciones_ambientales")
    op.drop_index("ix_area_mediciones_ambientales_empresa_area", table_name="area_mediciones_ambientales")
    op.drop_index("ix_area_mediciones_ambientales_empresa_id", table_name="area_mediciones_ambientales")
    op.drop_table("area_mediciones_ambientales")

    op.drop_index("ix_area_condiciones_ambientales_empresa_activa", table_name="area_condiciones_ambientales")
    op.drop_index("ix_area_condiciones_ambientales_empresa_area", table_name="area_condiciones_ambientales")
    op.drop_index("ix_area_condiciones_ambientales_empresa_id", table_name="area_condiciones_ambientales")
    op.drop_table("area_condiciones_ambientales")
