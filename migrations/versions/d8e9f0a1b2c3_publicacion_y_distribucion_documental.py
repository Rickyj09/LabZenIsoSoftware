"""publicacion y distribucion documental

Revision ID: d8e9f0a1b2c3
Revises: c5d7e9f1a2b3
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa


revision = "d8e9f0a1b2c3"
down_revision = "c5d7e9f1a2b3"
branch_labels = None
depends_on = None


NEW_PERMISSIONS = (
    ("documentos.publicar_vigente", "Publicar documentos como vigentes"),
    ("documentos.distribucion.gestionar", "Gestionar distribucion documental"),
    ("documentos.distribucion.ver", "Ver distribucion documental"),
    ("documentos.distribucion.reintentar", "Reintentar distribucion documental"),
    ("documentos.publicaciones.revocar", "Revocar publicaciones documentales"),
)


def upgrade():
    with op.batch_alter_table("documentos") as batch:
        batch.drop_constraint("ck_documentos_estado_valido", type_="check")
        batch.create_check_constraint(
            "ck_documentos_estado_valido",
            "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION', 'APROBADO', 'VIGENTE', 'RECHAZADO', 'OBSOLETO')",
        )

    with op.batch_alter_table("documento_versiones") as batch:
        batch.drop_constraint("ck_documento_versiones_estado_valido", type_="check")
        batch.add_column(sa.Column("vigente_desde", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("publicado_por_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key("fk_documento_versiones_publicado_por_id", "usuarios", ["publicado_por_id"], ["id"])
        batch.create_check_constraint(
            "ck_documento_versiones_estado_valido",
            "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION', 'APROBADO', 'VIGENTE', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')",
        )

    with op.batch_alter_table("documento_aprobaciones") as batch:
        batch.drop_constraint("ck_documento_eventos_accion_valida", type_="check")
        batch.alter_column("accion", existing_type=sa.String(length=30), type_=sa.String(length=60), existing_nullable=False)
        batch.create_check_constraint(
            "ck_documento_eventos_accion_valida",
            "accion IN ('CREAR_VERSION', 'ENVIAR_REVISION', 'DAR_CONFORMIDAD', 'APROBAR', 'RECHAZAR', 'SOLICITAR_CORRECCIONES', 'RECHAZAR_APROBACION', 'DEVOLVER_BORRADOR', 'OBSOLETAR', 'SUSTITUIR_VERSION', 'PUBLICAR_VIGENTE', 'VERSION_ANTERIOR_OBSOLETA', 'PUBLICACION_PREPARADA', 'QR_GENERADO', 'PDF_QR_GENERADO', 'DISTRIBUCION_ENCOLADA', 'PUBLICACION_CONSULTADA', 'PDF_VIGENTE_DESCARGADO', 'PUBLICACION_REVOCADA')",
        )

    with op.batch_alter_table("documento_artefactos") as batch:
        batch.drop_constraint("ck_documento_artefactos_tipo_valido", type_="check")
        batch.create_check_constraint(
            "ck_documento_artefactos_tipo_valido",
            "tipo IN ('PDF_APROBADO', 'PDF_APROBADO_CON_QR', 'PDF_FIRMADO_PARCIAL', 'PDF_FIRMADO_FINAL')",
        )

    op.create_table(
        "documento_publicaciones",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_version_id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("modo_acceso", sa.String(length=30), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("qr_payload", sa.String(length=1000), nullable=True),
        sa.Column("qr_storage_key", sa.String(length=500), nullable=True),
        sa.Column("qr_sha256", sa.String(length=64), nullable=True),
        sa.Column("pdf_fuente_storage_key", sa.String(length=500), nullable=True),
        sa.Column("pdf_fuente_sha256", sa.String(length=64), nullable=True),
        sa.Column("pdf_publicado_id", sa.BigInteger(), nullable=True),
        sa.Column("pdf_aprobado_original_id", sa.BigInteger(), nullable=True),
        sa.Column("pdf_qr_artifact_id", sa.BigInteger(), nullable=True),
        sa.Column("qr_embebido", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vigente_desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publicado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("revocado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("motivo_revocacion", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.CheckConstraint("estado IN ('PREPARADA', 'ACTIVA', 'OBSOLETA', 'REVOCADA')", name="ck_documento_publicaciones_estado_valido"),
        sa.CheckConstraint("modo_acceso IN ('AUTENTICADO', 'TOKEN_PUBLICO')", name="ck_documento_publicaciones_modo_acceso_valido"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["documento_version_id"], ["documento_versiones.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["pdf_aprobado_original_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["pdf_publicado_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["pdf_qr_artifact_id"], ["documento_artefactos.id"]),
        sa.ForeignKeyConstraint(["publicado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["revocado_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_documento_publicaciones_public_id"),
        sa.UniqueConstraint("token", name="uq_documento_publicaciones_token"),
    )
    op.create_index("ix_documento_publicaciones_documento_id", "documento_publicaciones", ["documento_id"])
    op.create_index("ix_documento_publicaciones_documento_version_id", "documento_publicaciones", ["documento_version_id"])
    op.create_index("ix_documento_publicaciones_empresa_id", "documento_publicaciones", ["empresa_id"])
    op.create_index("ix_documento_publicaciones_estado", "documento_publicaciones", ["estado"])
    op.create_index("uq_documento_publicacion_version_activa", "documento_publicaciones", ["documento_version_id"], unique=True, postgresql_where=sa.text("activa = true"), sqlite_where=sa.text("activa = 1"))
    op.create_index("uq_documento_publicacion_vigente_activa", "documento_publicaciones", ["empresa_id", "documento_id"], unique=True, postgresql_where=sa.text("estado = 'ACTIVA' AND activa = true"), sqlite_where=sa.text("estado = 'ACTIVA' AND activa = 1"))

    op.create_table(
        "documento_distribucion_destinatarios",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("grupo", sa.String(length=120), nullable=True),
        sa.Column("creado_por_id", sa.BigInteger(), nullable=False),
        sa.Column("actualizado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("desactivado_por_id", sa.BigInteger(), nullable=True),
        sa.Column("desactivado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_desactivacion", sa.Text(), nullable=True),
        sa.CheckConstraint("tipo IN ('INTERNO', 'EXTERNO')", name="ck_documento_distribucion_destinatarios_tipo_valido"),
        sa.ForeignKeyConstraint(["actualizado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["desactivado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documento_destinatarios_activo", "documento_distribucion_destinatarios", ["activo"])
    op.create_index("ix_documento_destinatarios_documento_id", "documento_distribucion_destinatarios", ["documento_id"])
    op.create_index("ix_documento_destinatarios_email", "documento_distribucion_destinatarios", ["email"])
    op.create_index("ix_documento_distribucion_destinatarios_empresa_id", "documento_distribucion_destinatarios", ["empresa_id"])
    op.create_index("ix_documento_destinatarios_usuario_id", "documento_distribucion_destinatarios", ["usuario_id"])
    op.create_index("uq_documento_destinatario_email_activo", "documento_distribucion_destinatarios", ["empresa_id", "documento_id", "email"], unique=True, postgresql_where=sa.text("activo = true"), sqlite_where=sa.text("activo = 1"))

    op.create_table(
        "documento_distribucion_entregas",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("empresa_id", sa.BigInteger(), nullable=False),
        sa.Column("publicacion_id", sa.BigInteger(), nullable=False),
        sa.Column("destinatario_original_id", sa.BigInteger(), nullable=True),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("nombre_snapshot", sa.String(length=200), nullable=False),
        sa.Column("email_snapshot", sa.String(length=255), nullable=False),
        sa.Column("tipo_snapshot", sa.String(length=30), nullable=False),
        sa.Column("estado_envio", sa.String(length=30), nullable=False),
        sa.Column("intentos", sa.Integer(), nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("ultimo_intento_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.CheckConstraint("estado_envio IN ('PENDIENTE', 'PROCESANDO', 'ENVIADO', 'FALLIDO', 'OMITIDO')", name="ck_documento_distribucion_entregas_estado_valido"),
        sa.CheckConstraint("intentos >= 0", name="ck_documento_distribucion_entregas_intentos_valido"),
        sa.ForeignKeyConstraint(["destinatario_original_id"], ["documento_distribucion_destinatarios.id"]),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["publicacion_id"], ["documento_publicaciones.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publicacion_id", "email_snapshot", name="uq_documento_entrega_publicacion_email"),
    )
    op.create_index("ix_documento_entregas_email_snapshot", "documento_distribucion_entregas", ["email_snapshot"])
    op.create_index("ix_documento_distribucion_entregas_empresa_id", "documento_distribucion_entregas", ["empresa_id"])
    op.create_index("ix_documento_entregas_estado_envio", "documento_distribucion_entregas", ["estado_envio"])
    op.create_index("ix_documento_entregas_publicacion_id", "documento_distribucion_entregas", ["publicacion_id"])

    _seed_permissions()


def downgrade():
    _delete_permissions()
    op.drop_index("ix_documento_entregas_publicacion_id", table_name="documento_distribucion_entregas")
    op.drop_index("ix_documento_entregas_estado_envio", table_name="documento_distribucion_entregas")
    op.execute("DROP INDEX IF EXISTS ix_documento_distribucion_entregas_empresa_id")
    op.drop_index("ix_documento_entregas_email_snapshot", table_name="documento_distribucion_entregas")
    op.drop_table("documento_distribucion_entregas")
    op.drop_index("ix_documento_destinatarios_usuario_id", table_name="documento_distribucion_destinatarios")
    op.drop_index("uq_documento_destinatario_email_activo", table_name="documento_distribucion_destinatarios")
    op.drop_index("ix_documento_destinatarios_email", table_name="documento_distribucion_destinatarios")
    op.execute("DROP INDEX IF EXISTS ix_documento_distribucion_destinatarios_empresa_id")
    op.drop_index("ix_documento_destinatarios_documento_id", table_name="documento_distribucion_destinatarios")
    op.drop_index("ix_documento_destinatarios_activo", table_name="documento_distribucion_destinatarios")
    op.drop_table("documento_distribucion_destinatarios")
    op.drop_index("uq_documento_publicacion_vigente_activa", table_name="documento_publicaciones")
    op.drop_index("uq_documento_publicacion_version_activa", table_name="documento_publicaciones")
    op.drop_index("ix_documento_publicaciones_estado", table_name="documento_publicaciones")
    op.execute("DROP INDEX IF EXISTS ix_documento_publicaciones_empresa_id")
    op.drop_index("ix_documento_publicaciones_documento_version_id", table_name="documento_publicaciones")
    op.drop_index("ix_documento_publicaciones_documento_id", table_name="documento_publicaciones")
    op.drop_table("documento_publicaciones")

    with op.batch_alter_table("documento_artefactos") as batch:
        batch.drop_constraint("ck_documento_artefactos_tipo_valido", type_="check")
        batch.create_check_constraint("ck_documento_artefactos_tipo_valido", "tipo IN ('PDF_APROBADO', 'PDF_FIRMADO_PARCIAL', 'PDF_FIRMADO_FINAL')")
    with op.batch_alter_table("documento_aprobaciones") as batch:
        batch.drop_constraint("ck_documento_eventos_accion_valida", type_="check")
        batch.alter_column("accion", existing_type=sa.String(length=60), type_=sa.String(length=30), existing_nullable=False)
        batch.create_check_constraint("ck_documento_eventos_accion_valida", "accion IN ('CREAR_VERSION', 'ENVIAR_REVISION', 'DAR_CONFORMIDAD', 'APROBAR', 'RECHAZAR', 'SOLICITAR_CORRECCIONES', 'RECHAZAR_APROBACION', 'DEVOLVER_BORRADOR', 'OBSOLETAR', 'SUSTITUIR_VERSION')")
    with op.batch_alter_table("documento_versiones") as batch:
        batch.drop_constraint("ck_documento_versiones_estado_valido", type_="check")
        batch.drop_constraint("fk_documento_versiones_publicado_por_id", type_="foreignkey")
        batch.drop_column("publicado_por_id")
        batch.drop_column("vigente_desde")
        batch.create_check_constraint("ck_documento_versiones_estado_valido", "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')")
    with op.batch_alter_table("documentos") as batch:
        batch.drop_constraint("ck_documentos_estado_valido", type_="check")
        batch.create_check_constraint("ck_documentos_estado_valido", "estado IN ('EN_ELABORACION', 'EN_ACTUALIZACION', 'EN_REVISION', 'EN_APROBACION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')")


def _seed_permissions():
    connection = op.get_bind()
    permissions = sa.table("permisos", sa.column("id", sa.BigInteger), sa.column("codigo", sa.String), sa.column("nombre", sa.String), sa.column("descripcion", sa.Text), sa.column("modulo", sa.String), sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)))
    roles = sa.table("roles", sa.column("id", sa.BigInteger), sa.column("nombre", sa.String))
    role_permissions = sa.table("rol_permisos", sa.column("rol_id", sa.BigInteger), sa.column("permiso_id", sa.BigInteger), sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)))
    for code, name in NEW_PERMISSIONS:
        permission_id = connection.execute(sa.select(permissions.c.id).where(permissions.c.codigo == code)).scalar()
        if not permission_id:
            connection.execute(permissions.insert().values(codigo=code, nombre=name, descripcion=name, modulo="documentos", created_at=sa.func.now(), updated_at=sa.func.now()))
    permission_rows = connection.execute(sa.select(permissions.c.id, permissions.c.codigo).where(permissions.c.codigo.in_([code for code, _ in NEW_PERMISSIONS]))).all()
    permission_ids = {row.codigo: row.id for row in permission_rows}
    role_rows = connection.execute(sa.select(roles.c.id, roles.c.nombre)).all()
    for role in role_rows:
        if role.nombre.strip().upper() not in {"SUPERADMIN", "ADMIN", "ADMINISTRADOR", "CALIDAD"}:
            continue
        for code in permission_ids:
            exists = connection.execute(sa.select(role_permissions.c.rol_id).where(role_permissions.c.rol_id == role.id, role_permissions.c.permiso_id == permission_ids[code])).scalar()
            if not exists:
                connection.execute(role_permissions.insert().values(rol_id=role.id, permiso_id=permission_ids[code], created_at=sa.func.now(), updated_at=sa.func.now()))


def _delete_permissions():
    connection = op.get_bind()
    codes = [code for code, _ in NEW_PERMISSIONS]
    ids = connection.execute(sa.text("SELECT id FROM permisos WHERE codigo IN :codes").bindparams(sa.bindparam("codes", expanding=True)), {"codes": codes}).scalars().all()
    if ids:
        connection.execute(sa.text("DELETE FROM rol_permisos WHERE permiso_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": ids})
        connection.execute(sa.text("DELETE FROM permisos WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": ids})
