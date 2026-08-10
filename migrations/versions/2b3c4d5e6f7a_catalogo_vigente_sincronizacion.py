"""sincronizacion automatica catalogo vigente

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "2b3c4d5e6f7a"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


OLD_EVENT_ACTIONS = (
    "'CREAR_VERSION', 'ENVIAR_REVISION', 'DAR_CONFORMIDAD', 'APROBAR', 'RECHAZAR', "
    "'SOLICITAR_CORRECCIONES', 'RECHAZAR_APROBACION', 'DEVOLVER_BORRADOR', "
    "'OBSOLETAR', 'SUSTITUIR_VERSION', 'PUBLICAR_VIGENTE', 'VERSION_ANTERIOR_OBSOLETA', "
    "'PUBLICACION_PREPARADA', 'QR_GENERADO', 'PDF_QR_GENERADO', 'DISTRIBUCION_ENCOLADA', "
    "'PUBLICACION_CONSULTADA', 'PDF_VIGENTE_DESCARGADO', 'PUBLICACION_REVOCADA', "
    "'CLASIFICAR_CONTROL'"
)

NEW_EVENT_ACTIONS = (
    "'CREAR_VERSION', 'ENVIAR_REVISION', 'DAR_CONFORMIDAD', 'APROBAR', 'RECHAZAR', "
    "'SOLICITAR_CORRECCIONES', 'RECHAZAR_APROBACION', 'DEVOLVER_BORRADOR', "
    "'OBSOLETAR', 'SUSTITUIR_VERSION', 'PUBLICAR_VIGENTE', 'VERSION_ANTERIOR_OBSOLETA', "
    "'PUBLICACION_PREPARADA', 'QR_GENERADO', 'PDF_QR_GENERADO', 'DISTRIBUCION_ENCOLADA', "
    "'PUBLICACION_CONSULTADA', 'PDF_VIGENTE_DESCARGADO', 'PUBLICACION_REVOCADA', "
    "'CLASIFICAR_CONTROL', 'CATALOGO_VIGENTE_ALTA', 'CATALOGO_VIGENTE_ACTUALIZADO', "
    "'CATALOGO_VIGENTE_SIN_CAMBIOS', 'CATALOGO_VIGENTE_ERROR'"
)


def _drop_event_constraint():
    with op.batch_alter_table("documento_aprobaciones") as batch:
        batch.drop_constraint("ck_documento_eventos_accion_valida", type_="check")


def _create_event_constraint(actions):
    with op.batch_alter_table("documento_aprobaciones") as batch:
        batch.create_check_constraint(
            "ck_documento_eventos_accion_valida",
            f"accion IN ({actions})",
        )


def upgrade():
    with op.batch_alter_table("documento_vigor_catalogo") as batch:
        batch.add_column(sa.Column("documento_publicacion_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("sincronizado_por_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("sincronizado_en", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_documento_vigor_documento_publicacion_id",
            "documento_publicaciones",
            ["documento_publicacion_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_documento_vigor_sincronizado_por_id",
            "usuarios",
            ["sincronizado_por_id"],
            ["id"],
        )
        batch.create_index("ix_documento_vigor_documento_publicacion_id", ["documento_publicacion_id"])

    _drop_event_constraint()
    _create_event_constraint(NEW_EVENT_ACTIONS)


def downgrade():
    _drop_event_constraint()
    _create_event_constraint(OLD_EVENT_ACTIONS)

    with op.batch_alter_table("documento_vigor_catalogo") as batch:
        batch.drop_index("ix_documento_vigor_documento_publicacion_id")
        batch.drop_constraint("fk_documento_vigor_sincronizado_por_id", type_="foreignkey")
        batch.drop_constraint("fk_documento_vigor_documento_publicacion_id", type_="foreignkey")
        batch.drop_column("sincronizado_en")
        batch.drop_column("sincronizado_por_id")
        batch.drop_column("documento_publicacion_id")
