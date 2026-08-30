"""Modulo 4D evaluacion de competencia

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_evaluaciones_competencia",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_id", sa.BigInteger(), nullable=False),
        sa.Column("evaluador_personal_id", sa.BigInteger(), nullable=True),
        sa.Column("evaluador_usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("capacitacion_id", sa.BigInteger(), nullable=True),
        sa.Column("capacitacion_participante_id", sa.BigInteger(), nullable=True),
        sa.Column("codigo", sa.String(length=50), nullable=True),
        sa.Column("actividad", sa.String(length=180), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("tipo_competencia", sa.String(length=30), nullable=False, server_default="TECNICA"),
        sa.Column("metodo_evaluacion", sa.String(length=40), nullable=False),
        sa.Column("criterio_evaluacion", sa.Text(), nullable=False),
        sa.Column("criterios", sa.Text(), nullable=True),
        sa.Column("descripcion_metodo", sa.Text(), nullable=True),
        sa.Column("fecha_evaluacion", sa.Date(), nullable=False),
        sa.Column("resultado", sa.String(length=40), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("evaluador_externo_nombre", sa.String(length=180), nullable=True),
        sa.Column("evaluador_externo_entidad", sa.String(length=180), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "tipo_competencia IN ('TECNICA', 'EQUIPO', 'METODO', 'MUESTREO', 'RESULTADOS', 'SISTEMA_GESTION', 'OTRA')",
            name="ck_personal_eval_comp_tipo_valido",
        ),
        sa.CheckConstraint(
            "metodo_evaluacion IN ('OBSERVACION_DIRECTA', 'DEMOSTRACION_PRACTICA', 'EXAMEN_TEORICO', 'EXAMEN_PRACTICO', 'REVISION_DE_RESULTADOS', 'MUESTRA_DESCONOCIDA', 'COMPARACION_INTERLABORATORIO', 'SUPERVISION', 'OTRO')",
            name="ck_personal_eval_comp_metodo_valido",
        ),
        sa.CheckConstraint(
            "resultado IN ('COMPETENTE', 'COMPETENTE_CON_OBSERVACIONES', 'REQUIERE_ENTRENAMIENTO', 'NO_COMPETENTE')",
            name="ck_personal_eval_comp_resultado_valido",
        ),
        sa.CheckConstraint(
            "evaluador_personal_id IS NOT NULL OR evaluador_externo_nombre IS NOT NULL",
            name="ck_personal_eval_comp_evaluador_requerido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_eval_comp_empresa_id_empresas"),
        sa.ForeignKeyConstraint(["personal_id"], ["personal.id"], name="fk_personal_eval_comp_personal_id"),
        sa.ForeignKeyConstraint(["evaluador_personal_id"], ["personal.id"], name="fk_personal_eval_comp_evaluador_personal_id"),
        sa.ForeignKeyConstraint(["evaluador_usuario_id"], ["usuarios.id"], name="fk_personal_eval_comp_evaluador_usuario_id"),
        sa.ForeignKeyConstraint(["capacitacion_id"], ["personal_capacitaciones.id"], name="fk_personal_eval_comp_capacitacion_id"),
        sa.ForeignKeyConstraint(
            ["capacitacion_participante_id"],
            ["personal_capacitacion_participantes.id"],
            name="fk_personal_eval_comp_capacitacion_participante_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_personal_eval_comp_empresa_codigo"),
    )
    op.create_index("ix_personal_eval_comp_empresa_id", "personal_evaluaciones_competencia", ["empresa_id"])
    op.create_index(
        "ix_personal_eval_comp_empresa_personal",
        "personal_evaluaciones_competencia",
        ["empresa_id", "personal_id"],
    )
    op.create_index(
        "ix_personal_eval_comp_empresa_evaluador",
        "personal_evaluaciones_competencia",
        ["empresa_id", "evaluador_personal_id"],
    )
    op.create_index(
        "ix_personal_eval_comp_empresa_resultado",
        "personal_evaluaciones_competencia",
        ["empresa_id", "resultado"],
    )
    op.create_index(
        "ix_personal_eval_comp_empresa_tipo",
        "personal_evaluaciones_competencia",
        ["empresa_id", "tipo_competencia"],
    )
    op.create_index(
        "ix_personal_eval_comp_empresa_fecha",
        "personal_evaluaciones_competencia",
        ["empresa_id", "fecha_evaluacion"],
    )
    op.create_index(
        "ix_personal_eval_comp_empresa_activo",
        "personal_evaluaciones_competencia",
        ["empresa_id", "activo"],
    )

    op.create_table(
        "personal_evaluacion_competencia_evidencias",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("evaluacion_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_evidencia", sa.String(length=30), nullable=False),
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
            "tipo_evidencia IN ('CHECKLIST', 'FORMATO_EVALUACION', 'FOTOGRAFIA', 'ACTA', 'INFORME', 'RESULTADO_PRACTICO', 'PDF_FIRMADO', 'HOJA_CALCULO', 'OTRO')",
            name="ck_personal_eval_comp_evidencias_tipo_valido",
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], name="fk_personal_eval_comp_evid_empresa_id_empresas"),
        sa.ForeignKeyConstraint(
            ["evaluacion_id"],
            ["personal_evaluaciones_competencia.id"],
            name="fk_personal_eval_comp_evid_evaluacion_id",
        ),
        sa.ForeignKeyConstraint(["cargado_por_id"], ["usuarios.id"], name="fk_personal_eval_comp_evid_cargado_por_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_eval_comp_evid_empresa_id",
        "personal_evaluacion_competencia_evidencias",
        ["empresa_id"],
    )
    op.create_index(
        "ix_personal_eval_comp_evid_empresa_eval",
        "personal_evaluacion_competencia_evidencias",
        ["empresa_id", "evaluacion_id"],
    )
    op.create_index(
        "ix_personal_eval_comp_evid_empresa_activo",
        "personal_evaluacion_competencia_evidencias",
        ["empresa_id", "activo"],
    )


def downgrade():
    op.drop_index("ix_personal_eval_comp_evid_empresa_activo", table_name="personal_evaluacion_competencia_evidencias")
    op.drop_index("ix_personal_eval_comp_evid_empresa_eval", table_name="personal_evaluacion_competencia_evidencias")
    op.drop_index("ix_personal_eval_comp_evid_empresa_id", table_name="personal_evaluacion_competencia_evidencias")
    op.drop_table("personal_evaluacion_competencia_evidencias")

    op.drop_index("ix_personal_eval_comp_empresa_activo", table_name="personal_evaluaciones_competencia")
    op.drop_index("ix_personal_eval_comp_empresa_fecha", table_name="personal_evaluaciones_competencia")
    op.drop_index("ix_personal_eval_comp_empresa_tipo", table_name="personal_evaluaciones_competencia")
    op.drop_index("ix_personal_eval_comp_empresa_resultado", table_name="personal_evaluaciones_competencia")
    op.drop_index("ix_personal_eval_comp_empresa_evaluador", table_name="personal_evaluaciones_competencia")
    op.drop_index("ix_personal_eval_comp_empresa_personal", table_name="personal_evaluaciones_competencia")
    op.drop_index("ix_personal_eval_comp_empresa_id", table_name="personal_evaluaciones_competencia")
    op.drop_table("personal_evaluaciones_competencia")
