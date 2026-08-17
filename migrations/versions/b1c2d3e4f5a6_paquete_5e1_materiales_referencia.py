"""Paquete 5E.1 materiales y patrones de referencia

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "b1c2d3e4f5a6"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "materiales_referencia",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("fabricante", sa.String(length=150), nullable=True),
        sa.Column("proveedor", sa.String(length=150), nullable=True),
        sa.Column("lote", sa.String(length=100), nullable=True),
        sa.Column("certificado_numero", sa.String(length=100), nullable=True),
        sa.Column("referencia_fabricante", sa.String(length=100), nullable=True),
        sa.Column("fecha_recepcion", sa.Date(), nullable=False),
        sa.Column("fecha_apertura", sa.Date(), nullable=True),
        sa.Column("fecha_puesta_en_uso", sa.Date(), nullable=True),
        sa.Column("fecha_caducidad", sa.Date(), nullable=True),
        sa.Column("estado", sa.String(length=30), nullable=False, server_default="DISPONIBLE"),
        sa.Column("ubicacion", sa.String(length=150), nullable=True),
        sa.Column("condiciones_almacenamiento", sa.Text(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("responsable_id", sa.BigInteger(), nullable=True),
        sa.Column("cantidad_inicial", sa.Numeric(14, 4), nullable=True),
        sa.Column("cantidad_disponible", sa.Numeric(14, 4), nullable=True),
        sa.Column("unidad", sa.String(length=30), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "tipo IN ('MATERIAL_REFERENCIA', 'PATRON_REFERENCIA')",
            name="ck_materiales_referencia_tipo_valido",
        ),
        sa.CheckConstraint(
            "estado IN ('DISPONIBLE', 'EN_USO', 'AGOTADO', 'VENCIDO', 'RETIRADO')",
            name="ck_materiales_referencia_estado_valido",
        ),
        sa.CheckConstraint(
            "fecha_caducidad IS NULL OR fecha_caducidad >= fecha_recepcion",
            name="ck_materiales_referencia_caducidad_recepcion",
        ),
        sa.CheckConstraint(
            "cantidad_inicial IS NULL OR cantidad_inicial >= 0",
            name="ck_materiales_referencia_cantidad_inicial_no_negativa",
        ),
        sa.CheckConstraint(
            "cantidad_disponible IS NULL OR cantidad_disponible >= 0",
            name="ck_materiales_referencia_cantidad_disponible_no_negativa",
        ),
        sa.CheckConstraint(
            "cantidad_inicial IS NULL OR cantidad_disponible IS NULL OR cantidad_disponible <= cantidad_inicial",
            name="ck_materiales_referencia_cantidad_disponible_maxima",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["responsable_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_materiales_referencia_empresa_codigo"),
    )
    op.create_index("ix_materiales_referencia_empresa_id", "materiales_referencia", ["empresa_id"])
    op.create_index("ix_materiales_referencia_empresa_tipo", "materiales_referencia", ["empresa_id", "tipo"])
    op.create_index("ix_materiales_referencia_empresa_estado", "materiales_referencia", ["empresa_id", "estado"])
    op.create_index("ix_materiales_referencia_empresa_caducidad", "materiales_referencia", ["empresa_id", "fecha_caducidad"])
    op.create_index("ix_materiales_referencia_responsable_id", "materiales_referencia", ["responsable_id"])

    op.create_table(
        "material_referencia_documentos",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("material_referencia_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_evidencia", sa.String(length=50), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("vinculado_por_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "tipo_evidencia IN ('CERTIFICADO', 'FICHA_TECNICA', 'HOJA_SEGURIDAD', 'OTRO')",
            name="ck_material_referencia_documentos_tipo_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["material_referencia_id"], ["materiales_referencia.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["vinculado_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material_referencia_id", "documento_version_id", name="uq_material_referencia_documento_version"),
    )
    op.create_index("ix_material_referencia_documentos_empresa_id", "material_referencia_documentos", ["empresa_id"])
    op.create_index(
        "ix_material_referencia_documentos_empresa_material",
        "material_referencia_documentos",
        ["empresa_id", "material_referencia_id"],
    )
    op.create_index(
        "ix_material_referencia_documentos_documento_version_id",
        "material_referencia_documentos",
        ["documento_version_id"],
    )

    op.create_table(
        "material_referencia_historial",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("material_referencia_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_evento", sa.String(length=60), nullable=False),
        sa.Column("estado_anterior", sa.String(length=30), nullable=True),
        sa.Column("estado_nuevo", sa.String(length=30), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("datos_antes", sa.JSON(), nullable=True),
        sa.Column("datos_despues", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "tipo_evento IN ('MATERIAL_REFERENCIA_CREADO', 'MATERIAL_REFERENCIA_PUESTO_EN_USO', 'MATERIAL_REFERENCIA_AGOTADO', 'MATERIAL_REFERENCIA_VENCIDO', 'MATERIAL_REFERENCIA_RETIRADO', 'EVIDENCIA_MATERIAL_REFERENCIA_VINCULADA', 'EVIDENCIA_MATERIAL_REFERENCIA_DESVINCULADA')",
            name="ck_material_referencia_historial_tipo_evento_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["material_referencia_id"], ["materiales_referencia.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_material_referencia_historial_empresa_id", "material_referencia_historial", ["empresa_id"])
    op.create_index(
        "ix_material_referencia_historial_empresa_material",
        "material_referencia_historial",
        ["empresa_id", "material_referencia_id"],
    )
    op.create_index("ix_material_referencia_historial_tipo_evento", "material_referencia_historial", ["tipo_evento"])


def downgrade():
    op.drop_index("ix_material_referencia_historial_tipo_evento", table_name="material_referencia_historial")
    op.drop_index("ix_material_referencia_historial_empresa_material", table_name="material_referencia_historial")
    op.drop_index("ix_material_referencia_historial_empresa_id", table_name="material_referencia_historial")
    op.drop_table("material_referencia_historial")

    op.drop_index("ix_material_referencia_documentos_documento_version_id", table_name="material_referencia_documentos")
    op.drop_index("ix_material_referencia_documentos_empresa_material", table_name="material_referencia_documentos")
    op.drop_index("ix_material_referencia_documentos_empresa_id", table_name="material_referencia_documentos")
    op.drop_table("material_referencia_documentos")

    op.drop_index("ix_materiales_referencia_responsable_id", table_name="materiales_referencia")
    op.drop_index("ix_materiales_referencia_empresa_caducidad", table_name="materiales_referencia")
    op.drop_index("ix_materiales_referencia_empresa_estado", table_name="materiales_referencia")
    op.drop_index("ix_materiales_referencia_empresa_tipo", table_name="materiales_referencia")
    op.drop_index("ix_materiales_referencia_empresa_id", table_name="materiales_referencia")
    op.drop_table("materiales_referencia")
