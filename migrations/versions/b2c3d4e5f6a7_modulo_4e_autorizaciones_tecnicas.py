"""Modulo 4E autorizaciones tecnicas

Revision ID: b2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_autorizaciones_tecnicas",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=True),
        sa.Column("tipo_autorizacion", sa.String(length=40), nullable=False),
        sa.Column("actividad", sa.String(length=180), nullable=False),
        sa.Column("alcance", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("equipo_id", sa.BigInteger(), nullable=True),
        sa.Column("metodo_referencia", sa.String(length=120), nullable=True),
        sa.Column("metodo_descripcion", sa.Text(), nullable=True),
        sa.Column("evaluacion_competencia_id", sa.BigInteger(), nullable=True),
        sa.Column("autorizador_personal_id", sa.BigInteger(), nullable=True),
        sa.Column("autorizador_usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("autorizador_externo_nombre", sa.String(length=180), nullable=True),
        sa.Column("autorizador_externo_entidad", sa.String(length=180), nullable=True),
        sa.Column("fecha_autorizacion", sa.Date(), nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="VIGENTE"),
        sa.Column("fundamento", sa.Text(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("motivo_estado", sa.Text(), nullable=True),
        sa.Column("fecha_estado", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "tipo_autorizacion IN ('ACTIVIDAD_TECNICA', 'EQUIPO', 'METODO', 'MUESTREO', 'REVISION_RESULTADOS', 'AUTORIZACION_RESULTADOS', 'OPINION_INTERPRETACION', 'DESARROLLO_METODO', 'VALIDACION_METODO', 'OTRA')",
            name="ck_personal_aut_tec_tipo_valido",
        ),
        sa.CheckConstraint(
            "estado IN ('VIGENTE', 'SUSPENDIDA', 'REVOCADA')",
            name="ck_personal_aut_tec_estado_valido",
        ),
        sa.CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_aut_tec_fechas_ordenadas",
        ),
        sa.CheckConstraint(
            "tipo_autorizacion <> 'EQUIPO' OR equipo_id IS NOT NULL",
            name="ck_personal_aut_tec_equipo_requerido",
        ),
        sa.CheckConstraint(
            "tipo_autorizacion <> 'METODO' OR metodo_referencia IS NOT NULL",
            name="ck_personal_aut_tec_metodo_requerido",
        ),
        sa.CheckConstraint(
            "autorizador_personal_id IS NOT NULL OR autorizador_usuario_id IS NOT NULL OR autorizador_externo_nombre IS NOT NULL",
            name="ck_personal_aut_tec_autorizador_requerido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_aut_tec_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["personal_id"], ["personal.id"], name="fk_personal_aut_tec_personal_id"),
        sa.ForeignKeyConstraint(["equipo_id"], ["equipos.id"], name="fk_personal_aut_tec_equipo_id"),
        sa.ForeignKeyConstraint(
            ["evaluacion_competencia_id"],
            ["personal_evaluaciones_competencia.id"],
            name="fk_personal_aut_tec_evaluacion_competencia_id",
        ),
        sa.ForeignKeyConstraint(["autorizador_personal_id"], ["personal.id"], name="fk_personal_aut_tec_autorizador_personal_id"),
        sa.ForeignKeyConstraint(["autorizador_usuario_id"], ["usuarios.id"], name="fk_personal_aut_tec_autorizador_usuario_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_personal_aut_tec_empresa_codigo"),
    )
    op.create_index("ix_personal_aut_tec_empresa_id", "personal_autorizaciones_tecnicas", ["empresa_id"])
    op.create_index("ix_personal_aut_tec_empresa_personal", "personal_autorizaciones_tecnicas", ["empresa_id", "personal_id"])
    op.create_index("ix_personal_aut_tec_empresa_equipo", "personal_autorizaciones_tecnicas", ["empresa_id", "equipo_id"])
    op.create_index(
        "ix_personal_aut_tec_empresa_evaluacion",
        "personal_autorizaciones_tecnicas",
        ["empresa_id", "evaluacion_competencia_id"],
    )
    op.create_index("ix_personal_aut_tec_empresa_tipo", "personal_autorizaciones_tecnicas", ["empresa_id", "tipo_autorizacion"])
    op.create_index("ix_personal_aut_tec_empresa_estado", "personal_autorizaciones_tecnicas", ["empresa_id", "estado"])
    op.create_index(
        "ix_personal_aut_tec_empresa_vigencia",
        "personal_autorizaciones_tecnicas",
        ["empresa_id", "fecha_inicio", "fecha_fin"],
    )

    op.create_table(
        "personal_autorizacion_tecnica_evidencias",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("autorizacion_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_evidencia", sa.String(length=40), nullable=False),
        sa.Column("archivo_nombre_original", sa.String(length=255), nullable=False),
        sa.Column("archivo_nombre_guardado", sa.String(length=255), nullable=False),
        sa.Column("archivo_storage_path", sa.String(length=500), nullable=False),
        sa.Column("archivo_mime", sa.String(length=150), nullable=False),
        sa.Column("archivo_size", sa.BigInteger(), nullable=False),
        sa.Column("archivo_sha256", sa.String(length=64), nullable=False),
        sa.Column("cargado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "tipo_evidencia IN ('ACTA_AUTORIZACION', 'MATRIZ_FIRMADA', 'FORMATO_AUTORIZACION', 'CERTIFICADO', 'RESOLUCION_INTERNA', 'OTRO')",
            name="ck_personal_aut_tec_evidencias_tipo_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_aut_tec_evid_empresa_id_empresas"),
        sa.ForeignKeyConstraint(
            ["autorizacion_id"],
            ["personal_autorizaciones_tecnicas.id"],
            name="fk_personal_aut_tec_evid_autorizacion_id",
        ),
        sa.ForeignKeyConstraint(["cargado_por_id"], ["usuarios.id"], name="fk_personal_aut_tec_evid_cargado_por_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_aut_tec_evid_empresa_id", "personal_autorizacion_tecnica_evidencias", ["empresa_id"])
    op.create_index(
        "ix_personal_aut_tec_evid_empresa_aut",
        "personal_autorizacion_tecnica_evidencias",
        ["empresa_id", "autorizacion_id"],
    )
    op.create_index(
        "ix_personal_aut_tec_evid_empresa_activo",
        "personal_autorizacion_tecnica_evidencias",
        ["empresa_id", "activo"],
    )


def downgrade():
    op.drop_index("ix_personal_aut_tec_evid_empresa_activo", table_name="personal_autorizacion_tecnica_evidencias")
    op.drop_index("ix_personal_aut_tec_evid_empresa_aut", table_name="personal_autorizacion_tecnica_evidencias")
    op.drop_index("ix_personal_aut_tec_evid_empresa_id", table_name="personal_autorizacion_tecnica_evidencias")
    op.drop_table("personal_autorizacion_tecnica_evidencias")

    op.drop_index("ix_personal_aut_tec_empresa_vigencia", table_name="personal_autorizaciones_tecnicas")
    op.drop_index("ix_personal_aut_tec_empresa_estado", table_name="personal_autorizaciones_tecnicas")
    op.drop_index("ix_personal_aut_tec_empresa_tipo", table_name="personal_autorizaciones_tecnicas")
    op.drop_index("ix_personal_aut_tec_empresa_evaluacion", table_name="personal_autorizaciones_tecnicas")
    op.drop_index("ix_personal_aut_tec_empresa_equipo", table_name="personal_autorizaciones_tecnicas")
    op.drop_index("ix_personal_aut_tec_empresa_personal", table_name="personal_autorizaciones_tecnicas")
    op.drop_index("ix_personal_aut_tec_empresa_id", table_name="personal_autorizaciones_tecnicas")
    op.drop_table("personal_autorizaciones_tecnicas")
