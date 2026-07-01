"""versionamiento documental correcto

Revision ID: b7a2e4c91d30
Revises: 8f3c2d1a9b70
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "b7a2e4c91d30"
down_revision = "8f3c2d1a9b70"
branch_labels = None
depends_on = None


def upgrade():
    # Corrección reversible de las dos referencias legacy no migrables aprobadas.
    op.execute(sa.text("""
        UPDATE documento_versiones
        SET archivo_url = NULL, updated_at = NOW()
        WHERE archivo_storage_path IS NULL
          AND (
              (id = 2 AND empresa_id = 1 AND documento_id = 2 AND archivo_url = 'Descargas')
              OR
              (id = 3 AND empresa_id = 1 AND documento_id = 3
               AND archivo_url = 'C:\\Ricardo\\Proyectos\\LabZenIsoSoftware')
          )
    """))

    op.execute(sa.text("""
        UPDATE documentos
        SET estado = CASE
            WHEN LOWER(estado) = 'vigente' THEN 'APROBADO'
            ELSE UPPER(estado)
        END
    """))
    op.execute(sa.text("""
        UPDATE documento_versiones
        SET estado = CASE
            WHEN LOWER(estado) = 'vigente' THEN 'APROBADO'
            ELSE UPPER(estado)
        END,
        fecha_aprobacion = CASE
            WHEN LOWER(estado) = 'vigente' THEN COALESCE(fecha_aprobacion, updated_at)
            ELSE fecha_aprobacion
        END
    """))

    with op.batch_alter_table("documento_versiones", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fecha_envio_revision", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("fecha_rechazo", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("fecha_obsolescencia", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint("uq_documento_version_numero", ["documento_id", "version"])
        batch_op.create_index("ix_documento_versiones_documento_id", ["documento_id"], unique=False)
        batch_op.create_index("ix_documento_versiones_estado", ["estado"], unique=False)
        batch_op.create_check_constraint(
            "ck_documento_versiones_estado_valido",
            "estado IN ('BORRADOR', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')",
        )

    with op.batch_alter_table("documentos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version_vigente_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "fk_documentos_version_vigente_id",
            "documento_versiones",
            ["version_vigente_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_documentos_estado_valido",
            "estado IN ('BORRADOR', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')",
        )

    op.execute(sa.text("""
        UPDATE documentos AS d
        SET version_vigente_id = (
                SELECT dv.id
                FROM documento_versiones AS dv
                WHERE dv.documento_id = d.id
                  AND dv.empresa_id = d.empresa_id
                  AND dv.estado = 'APROBADO'
                ORDER BY
                    CASE WHEN dv.version = d.version_actual THEN 0 ELSE 1 END,
                    dv.fecha_aprobacion DESC NULLS LAST,
                    dv.id DESC
                LIMIT 1
            ),
            version_actual = (
                SELECT dv.version
                FROM documento_versiones AS dv
                WHERE dv.documento_id = d.id
                  AND dv.empresa_id = d.empresa_id
                  AND dv.estado = 'APROBADO'
                ORDER BY
                    CASE WHEN dv.version = d.version_actual THEN 0 ELSE 1 END,
                    dv.fecha_aprobacion DESC NULLS LAST,
                    dv.id DESC
                LIMIT 1
            ),
            estado = 'APROBADO'
        WHERE EXISTS (
            SELECT 1 FROM documento_versiones AS dv
            WHERE dv.documento_id = d.id
              AND dv.empresa_id = d.empresa_id
              AND dv.estado = 'APROBADO'
        )
    """))


def downgrade():
    with op.batch_alter_table("documentos", schema=None) as batch_op:
        batch_op.drop_constraint("ck_documentos_estado_valido", type_="check")
        batch_op.drop_constraint("fk_documentos_version_vigente_id", type_="foreignkey")
        batch_op.drop_column("version_vigente_id")

    with op.batch_alter_table("documento_versiones", schema=None) as batch_op:
        batch_op.drop_constraint("ck_documento_versiones_estado_valido", type_="check")
        batch_op.drop_index("ix_documento_versiones_estado")
        batch_op.drop_index("ix_documento_versiones_documento_id")
        batch_op.drop_constraint("uq_documento_version_numero", type_="unique")
        batch_op.drop_column("fecha_obsolescencia")
        batch_op.drop_column("fecha_rechazo")
        batch_op.drop_column("fecha_envio_revision")

    op.execute(sa.text("""
        UPDATE documento_versiones SET archivo_url = 'Descargas'
        WHERE id = 2 AND empresa_id = 1 AND documento_id = 2
          AND archivo_url IS NULL AND archivo_storage_path IS NULL
    """))
    op.execute(sa.text("""
        UPDATE documento_versiones SET archivo_url = 'C:\\Ricardo\\Proyectos\\LabZenIsoSoftware'
        WHERE id = 3 AND empresa_id = 1 AND documento_id = 3
          AND archivo_url IS NULL AND archivo_storage_path IS NULL
    """))
