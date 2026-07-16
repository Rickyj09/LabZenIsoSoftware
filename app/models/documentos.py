from app.extensions import db
from app.models.base import BaseModel, TenantMixin


ESTADO_EN_ELABORACION = "EN_ELABORACION"
ESTADO_EN_REVISION = "EN_REVISION"
ESTADO_APROBADO = "APROBADO"
ESTADO_RECHAZADO = "RECHAZADO"
ESTADO_OBSOLETO = "OBSOLETO"
ESTADO_SUSTITUIDO = "SUSTITUIDO"

ESTADOS_DOCUMENTO = (
    ESTADO_EN_ELABORACION,
    ESTADO_EN_REVISION,
    ESTADO_APROBADO,
    ESTADO_RECHAZADO,
    ESTADO_OBSOLETO,
)

ESTADOS_VERSION_DOCUMENTO = (
    ESTADO_EN_ELABORACION,
    ESTADO_EN_REVISION,
    ESTADO_APROBADO,
    ESTADO_RECHAZADO,
    ESTADO_OBSOLETO,
    ESTADO_SUSTITUIDO,
)

ACCIONES_EVENTO_DOCUMENTO = (
    "CREAR_VERSION",
    "ENVIAR_REVISION",
    "APROBAR",
    "RECHAZAR",
    "DEVOLVER_BORRADOR",
    "OBSOLETAR",
    "SUSTITUIR_VERSION",
)

ESTADO_EDICION_ACTIVA = "ACTIVA"
ESTADO_EDICION_LIBERADA = "LIBERADA"
ESTADO_EDICION_EXPIRADA = "EXPIRADA"
ESTADO_EDICION_ERROR = "ERROR"
ESTADO_EDICION_CANCELADA = "CANCELADA"

ESTADOS_EDICION_DOCUMENTO = (
    ESTADO_EDICION_ACTIVA,
    ESTADO_EDICION_LIBERADA,
    ESTADO_EDICION_EXPIRADA,
    ESTADO_EDICION_ERROR,
    ESTADO_EDICION_CANCELADA,
)

SNAPSHOT_ENVIO_REVISION = "ENVIO_REVISION"
SNAPSHOT_APROBADO = "APROBADO"
SNAPSHOT_RECHAZADO = "RECHAZADO"

TIPOS_DOCUMENTO_SNAPSHOT = (
    SNAPSHOT_ENVIO_REVISION,
    SNAPSHOT_APROBADO,
    SNAPSHOT_RECHAZADO,
)

SNAPSHOT_CREANDO = "CREANDO"
SNAPSHOT_DISPONIBLE = "DISPONIBLE"
SNAPSHOT_ERROR = "ERROR"
SNAPSHOT_INVALIDADO = "INVALIDADO"

ESTADOS_DOCUMENTO_SNAPSHOT = (
    SNAPSHOT_CREANDO,
    SNAPSHOT_DISPONIBLE,
    SNAPSHOT_ERROR,
    SNAPSHOT_INVALIDADO,
)

ARTEFACTO_PDF_APROBADO = "PDF_APROBADO"

TIPOS_DOCUMENTO_ARTEFACTO = (
    ARTEFACTO_PDF_APROBADO,
)

ARTEFACTO_PENDIENTE = "PENDIENTE"
ARTEFACTO_CONVIRTIENDO = "CONVIRTIENDO"
ARTEFACTO_DISPONIBLE = "DISPONIBLE"
ARTEFACTO_ERROR = "ERROR"
ARTEFACTO_CANCELADO = "CANCELADO"

ESTADOS_DOCUMENTO_ARTEFACTO = (
    ARTEFACTO_PENDIENTE,
    ARTEFACTO_CONVIRTIENDO,
    ARTEFACTO_DISPONIBLE,
    ARTEFACTO_ERROR,
    ARTEFACTO_CANCELADO,
)

CONVERSION_PENDIENTE = "PENDIENTE"
CONVERSION_SOLICITADA = "SOLICITADA"
CONVERSION_EN_PROCESO = "EN_PROCESO"
CONVERSION_COMPLETADA = "COMPLETADA"
CONVERSION_ERROR = "ERROR"
CONVERSION_CANCELADA = "CANCELADA"

ESTADOS_DOCUMENTO_CONVERSION = (
    CONVERSION_PENDIENTE,
    CONVERSION_SOLICITADA,
    CONVERSION_EN_PROCESO,
    CONVERSION_COMPLETADA,
    CONVERSION_ERROR,
    CONVERSION_CANCELADA,
)

ESTADO_DOCUMENTO_LABELS = {
    ESTADO_EN_ELABORACION: "EN ELABORACIÓN",
    ESTADO_EN_REVISION: "EN REVISIÓN",
    ESTADO_APROBADO: "APROBADO",
    ESTADO_RECHAZADO: "RECHAZADO",
    ESTADO_OBSOLETO: "OBSOLETO",
    ESTADO_SUSTITUIDO: "SUSTITUIDO",
}

ESTADO_DOCUMENTO_BADGE_CLASSES = {
    ESTADO_EN_ELABORACION: "bg-secondary",
    ESTADO_EN_REVISION: "bg-warning text-dark",
    ESTADO_APROBADO: "bg-success",
    ESTADO_RECHAZADO: "bg-danger",
    ESTADO_OBSOLETO: "bg-danger",
    ESTADO_SUSTITUIDO: "bg-dark",
}


def etiqueta_estado_documental(estado):
    return ESTADO_DOCUMENTO_LABELS.get(estado, (estado or "").replace("_", " "))


def clase_badge_estado_documental(estado):
    return ESTADO_DOCUMENTO_BADGE_CLASSES.get(estado, "bg-light text-dark")


class Documento(TenantMixin, BaseModel):
    __tablename__ = "documentos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_documentos_empresa_codigo"),
        db.CheckConstraint(
            "estado IN ('EN_ELABORACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')",
            name="ck_documentos_estado_valido",
        ),
    )

    codigo = db.Column(db.String(50), nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    tipo_documento = db.Column(db.String(50), nullable=False)
    proceso = db.Column(db.String(100))
    estado = db.Column(db.String(30), default=ESTADO_EN_ELABORACION, nullable=False)
    version_actual = db.Column(db.String(20), nullable=False, default="1")
    version_vigente_id = db.Column(
        db.BigInteger,
        db.ForeignKey("documento_versiones.id", name="fk_documentos_version_vigente_id", use_alter=True),
        nullable=True,
    )

    elaborado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa", back_populates="documentos")
    elaborado_por = db.relationship("Usuario", foreign_keys=[elaborado_por_id])

    versiones = db.relationship(
        "DocumentoVersion",
        foreign_keys="DocumentoVersion.documento_id",
        back_populates="documento",
        lazy=True,
        cascade="all, delete-orphan"
    )
    version_vigente = db.relationship(
        "DocumentoVersion",
        foreign_keys=[version_vigente_id],
        post_update=True,
    )
    eventos = db.relationship(
        "DocumentoAprobacion",
        foreign_keys="DocumentoAprobacion.documento_id",
        back_populates="documento",
        lazy=True,
    )


class DocumentoVersion(TenantMixin, BaseModel):
    __tablename__ = "documento_versiones"
    __table_args__ = (
        db.UniqueConstraint("documento_id", "version", name="uq_documento_version_numero"),
        db.CheckConstraint(
            "estado IN ('EN_ELABORACION', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')",
            name="ck_documento_versiones_estado_valido",
        ),
        db.Index("ix_documento_versiones_documento_id", "documento_id"),
        db.Index("ix_documento_versiones_estado", "estado"),
        db.Index(
            "uq_documento_version_preparacion_activa",
            "documento_id",
            unique=True,
            postgresql_where=db.text("estado IN ('EN_ELABORACION', 'EN_REVISION')"),
            sqlite_where=db.text("estado IN ('EN_ELABORACION', 'EN_REVISION')"),
        ),
    )

    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)

    version = db.Column(db.String(20), nullable=False)
    archivo_url = db.Column(db.String(255))
    archivo_nombre_original = db.Column(db.String(255))
    archivo_nombre_guardado = db.Column(db.String(255))
    archivo_storage_path = db.Column(db.String(500))
    archivo_mime = db.Column(db.String(255))
    archivo_size = db.Column(db.BigInteger)
    archivo_sha256 = db.Column(db.String(64))
    contenido = db.Column(db.Text)
    fecha_version = db.Column(db.Date, nullable=False, default=db.func.current_date())
    cambios = db.Column(db.Text)

    elaborado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    revisado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    aprobado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    rechazado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    obsoletado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    fecha_aprobacion = db.Column(db.DateTime(timezone=True), nullable=True)
    fecha_envio_revision = db.Column(db.DateTime(timezone=True), nullable=True)
    fecha_rechazo = db.Column(db.DateTime(timezone=True), nullable=True)
    fecha_obsolescencia = db.Column(db.DateTime(timezone=True), nullable=True)
    comentario_revision = db.Column(db.Text)
    comentario_aprobacion = db.Column(db.Text)
    comentario_rechazo = db.Column(db.Text)
    motivo_obsolescencia = db.Column(db.Text)
    estado = db.Column(db.String(30), default=ESTADO_EN_ELABORACION, nullable=False)

    empresa = db.relationship("Empresa")
    documento = db.relationship(
        "Documento",
        foreign_keys=[documento_id],
        back_populates="versiones",
    )

    elaborado_por = db.relationship("Usuario", foreign_keys=[elaborado_por_id])
    revisado_por = db.relationship("Usuario", foreign_keys=[revisado_por_id])
    aprobado_por = db.relationship("Usuario", foreign_keys=[aprobado_por_id])
    rechazado_por = db.relationship("Usuario", foreign_keys=[rechazado_por_id])
    obsoletado_por = db.relationship("Usuario", foreign_keys=[obsoletado_por_id])

    aprobaciones = db.relationship(
        "DocumentoAprobacion",
        back_populates="documento_version",
        lazy=True,
        cascade="all, delete-orphan"
    )


class DocumentoAprobacion(TenantMixin, BaseModel):
    __tablename__ = "documento_aprobaciones"
    __table_args__ = (
        db.CheckConstraint(
            "accion IN ('CREAR_VERSION', 'ENVIAR_REVISION', 'APROBAR', 'RECHAZAR', 'DEVOLVER_BORRADOR', 'OBSOLETAR', 'SUSTITUIR_VERSION')",
            name="ck_documento_eventos_accion_valida",
        ),
        db.Index("ix_documento_eventos_documento_id", "documento_id"),
        db.Index("ix_documento_eventos_accion", "accion"),
    )

    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)

    accion = db.Column(db.String(30), nullable=False)
    fecha_accion = db.Column(db.DateTime(timezone=True), nullable=False)
    estado_anterior = db.Column(db.String(30))
    estado_nuevo = db.Column(db.String(30), nullable=False)
    comentario = db.Column(db.Text)
    ip = db.Column(db.String(50))
    user_agent = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
    documento = db.relationship(
        "Documento",
        foreign_keys=[documento_id],
        back_populates="eventos",
    )
    documento_version = db.relationship("DocumentoVersion", back_populates="aprobaciones")


class DocumentoSnapshot(TenantMixin, BaseModel):
    __tablename__ = "documento_snapshots"
    __table_args__ = (
        db.CheckConstraint(
            "tipo IN ('ENVIO_REVISION', 'APROBADO', 'RECHAZADO')",
            name="ck_documento_snapshots_tipo_valido",
        ),
        db.CheckConstraint(
            "estado IN ('CREANDO', 'DISPONIBLE', 'ERROR', 'INVALIDADO')",
            name="ck_documento_snapshots_estado_valido",
        ),
        db.CheckConstraint("secuencia > 0", name="ck_documento_snapshots_secuencia_positiva"),
        db.CheckConstraint("ciclo_revision > 0", name="ck_documento_snapshots_ciclo_positivo"),
        db.CheckConstraint("archivo_size IS NULL OR archivo_size > 0", name="ck_documento_snapshots_size_positivo"),
        db.CheckConstraint(
            "archivo_sha256 IS NULL OR length(archivo_sha256) = 64",
            name="ck_documento_snapshots_sha256_valido",
        ),
        db.CheckConstraint(
            "hash_origen IS NULL OR length(hash_origen) = 64",
            name="ck_documento_snapshots_hash_origen_valido",
        ),
        db.CheckConstraint(
            "estado <> 'DISPONIBLE' OR inmutable = true",
            name="ck_documento_snapshots_disponible_inmutable",
        ),
        db.UniqueConstraint("public_id", name="uq_documento_snapshots_public_id"),
        db.UniqueConstraint("storage_path", name="uq_documento_snapshots_storage_path"),
        db.UniqueConstraint("documento_version_id", "secuencia", name="uq_documento_snapshots_version_secuencia"),
        db.UniqueConstraint(
            "documento_version_id",
            "tipo",
            "ciclo_revision",
            name="uq_documento_snapshots_version_tipo_ciclo",
        ),
        db.Index("ix_documento_snapshots_documento_id", "documento_id"),
        db.Index("ix_documento_snapshots_documento_version_id", "documento_version_id"),
        db.Index("ix_documento_snapshots_tipo", "tipo"),
        db.Index("ix_documento_snapshots_ciclo_revision", "ciclo_revision"),
        db.Index("ix_documento_snapshots_secuencia", "secuencia"),
        db.Index("ix_documento_snapshots_creado_en", "creado_en"),
        db.Index("ix_documento_snapshots_archivo_sha256", "archivo_sha256"),
        db.Index("ix_documento_snapshots_workflow_evento_id", "workflow_evento_id"),
        db.Index(
            "uq_documento_snapshots_aprobado_unico",
            "documento_version_id",
            unique=True,
            postgresql_where=db.text("tipo = 'APROBADO' AND estado = 'DISPONIBLE'"),
            sqlite_where=db.text("tipo = 'APROBADO' AND estado = 'DISPONIBLE'"),
        ),
    )

    public_id = db.Column(db.String(64), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    secuencia = db.Column(db.Integer, nullable=False)
    ciclo_revision = db.Column(db.Integer, nullable=False)
    tipo = db.Column(db.String(30), nullable=False)
    estado = db.Column(db.String(30), nullable=False, default=SNAPSHOT_CREANDO)
    storage_path = db.Column(db.String(500))
    archivo_nombre_interno = db.Column(db.String(255))
    archivo_nombre_original = db.Column(db.String(255))
    archivo_mime = db.Column(db.String(255))
    archivo_size = db.Column(db.BigInteger)
    archivo_sha256 = db.Column(db.String(64))
    hash_origen = db.Column(db.String(64))
    creado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False)
    workflow_evento_id = db.Column(db.BigInteger, db.ForeignKey("documento_aprobaciones.id"), nullable=True)
    snapshot_origen_id = db.Column(db.BigInteger, db.ForeignKey("documento_snapshots.id"), nullable=True)
    comentario = db.Column(db.Text)
    resumen_cambios = db.Column(db.Text)
    hojas_modificadas = db.Column(db.String(500))
    metadata_json = db.Column(db.JSON)
    inmutable = db.Column(db.Boolean, nullable=False, default=True)

    empresa = db.relationship("Empresa")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    creado_por = db.relationship("Usuario", foreign_keys=[creado_por_id])
    workflow_evento = db.relationship("DocumentoAprobacion", foreign_keys=[workflow_evento_id])
    snapshot_origen = db.relationship("DocumentoSnapshot", remote_side="DocumentoSnapshot.id")


class DocumentoArtefacto(TenantMixin, BaseModel):
    __tablename__ = "documento_artefactos"
    __table_args__ = (
        db.CheckConstraint("tipo IN ('PDF_APROBADO')", name="ck_documento_artefactos_tipo_valido"),
        db.CheckConstraint(
            "estado IN ('PENDIENTE', 'CONVIRTIENDO', 'DISPONIBLE', 'ERROR', 'CANCELADO')",
            name="ck_documento_artefactos_estado_valido",
        ),
        db.CheckConstraint("archivo_size IS NULL OR archivo_size > 0", name="ck_documento_artefactos_size_positivo"),
        db.CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_documento_artefactos_page_count_positivo"),
        db.CheckConstraint(
            "archivo_sha256 IS NULL OR length(archivo_sha256) = 64",
            name="ck_documento_artefactos_sha256_valido",
        ),
        db.CheckConstraint(
            "source_snapshot_sha256 IS NULL OR length(source_snapshot_sha256) = 64",
            name="ck_documento_artefactos_source_sha256_valido",
        ),
        db.CheckConstraint(
            "estado <> 'DISPONIBLE' OR inmutable = true",
            name="ck_documento_artefactos_disponible_inmutable",
        ),
        db.CheckConstraint(
            "estado <> 'DISPONIBLE' OR page_count > 0",
            name="ck_documento_artefactos_disponible_page_count",
        ),
        db.CheckConstraint(
            "estado <> 'DISPONIBLE' OR archivo_size > 0",
            name="ck_documento_artefactos_disponible_size",
        ),
        db.UniqueConstraint("public_id", name="uq_documento_artefactos_public_id"),
        db.UniqueConstraint("storage_path", name="uq_documento_artefactos_storage_path"),
        db.Index("ix_documento_artefactos_documento_id", "documento_id"),
        db.Index("ix_documento_artefactos_documento_version_id", "documento_version_id"),
        db.Index("ix_documento_artefactos_source_snapshot_id", "source_snapshot_id"),
        db.Index("ix_documento_artefactos_tipo", "tipo"),
        db.Index("ix_documento_artefactos_estado", "estado"),
        db.Index("ix_documento_artefactos_creado_en", "creado_en"),
        db.Index("ix_documento_artefactos_archivo_sha256", "archivo_sha256"),
        db.Index("ix_documento_artefactos_provider", "provider"),
        db.Index(
            "uq_documento_artefactos_pdf_aprobado_disponible",
            "source_snapshot_id",
            "tipo",
            unique=True,
            postgresql_where=db.text("tipo = 'PDF_APROBADO' AND estado = 'DISPONIBLE'"),
            sqlite_where=db.text("tipo = 'PDF_APROBADO' AND estado = 'DISPONIBLE'"),
        ),
    )

    public_id = db.Column(db.String(64), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    source_snapshot_id = db.Column(db.BigInteger, db.ForeignKey("documento_snapshots.id"), nullable=False)
    tipo = db.Column(db.String(30), nullable=False, default=ARTEFACTO_PDF_APROBADO)
    estado = db.Column(db.String(30), nullable=False, default=ARTEFACTO_PENDIENTE)
    storage_path = db.Column(db.String(500))
    archivo_nombre_interno = db.Column(db.String(255))
    archivo_nombre_visible = db.Column(db.String(255))
    archivo_mime = db.Column(db.String(255))
    archivo_size = db.Column(db.BigInteger)
    archivo_sha256 = db.Column(db.String(64))
    source_snapshot_sha256 = db.Column(db.String(64), nullable=False)
    page_count = db.Column(db.Integer)
    provider = db.Column(db.String(50), nullable=False, default="onlyoffice")
    provider_version = db.Column(db.String(50))
    creado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False)
    disponible_en = db.Column(db.DateTime(timezone=True))
    inmutable = db.Column(db.Boolean, nullable=False, default=False)
    error_codigo = db.Column(db.String(80))
    error_mensaje = db.Column(db.Text)
    metadata_json = db.Column(db.JSON)

    empresa = db.relationship("Empresa")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    source_snapshot = db.relationship("DocumentoSnapshot", foreign_keys=[source_snapshot_id])
    creado_por = db.relationship("Usuario", foreign_keys=[creado_por_id])


class DocumentoConversion(TenantMixin, BaseModel):
    __tablename__ = "documento_conversiones"
    __table_args__ = (
        db.CheckConstraint(
            "estado IN ('PENDIENTE', 'SOLICITADA', 'EN_PROCESO', 'COMPLETADA', 'ERROR', 'CANCELADA')",
            name="ck_documento_conversiones_estado_valido",
        ),
        db.CheckConstraint("attempt_number > 0", name="ck_documento_conversiones_attempt_positivo"),
        db.CheckConstraint("percent IS NULL OR (percent >= 0 AND percent <= 100)", name="ck_documento_conversiones_percent_valido"),
        db.UniqueConstraint("public_id", name="uq_documento_conversiones_public_id"),
        db.UniqueConstraint("conversion_key", name="uq_documento_conversiones_conversion_key"),
        db.Index("ix_documento_conversiones_documento_id", "documento_id"),
        db.Index("ix_documento_conversiones_documento_version_id", "documento_version_id"),
        db.Index("ix_documento_conversiones_source_snapshot_id", "source_snapshot_id"),
        db.Index("ix_documento_conversiones_artefacto_id", "artefacto_id"),
        db.Index("ix_documento_conversiones_provider", "provider"),
        db.Index("ix_documento_conversiones_estado", "estado"),
        db.Index("ix_documento_conversiones_attempt_number", "attempt_number"),
        db.Index("ix_documento_conversiones_solicitado_en", "solicitado_en"),
    )

    public_id = db.Column(db.String(64), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    source_snapshot_id = db.Column(db.BigInteger, db.ForeignKey("documento_snapshots.id"), nullable=False)
    artefacto_id = db.Column(db.BigInteger, db.ForeignKey("documento_artefactos.id"), nullable=True)
    provider = db.Column(db.String(50), nullable=False, default="onlyoffice")
    conversion_key = db.Column(db.String(128), nullable=False)
    estado = db.Column(db.String(30), nullable=False, default=CONVERSION_PENDIENTE)
    attempt_number = db.Column(db.Integer, nullable=False, default=1)
    percent = db.Column(db.Integer)
    solicitado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)
    solicitado_en = db.Column(db.DateTime(timezone=True), nullable=False)
    iniciado_en = db.Column(db.DateTime(timezone=True))
    ultima_consulta_en = db.Column(db.DateTime(timezone=True))
    completado_en = db.Column(db.DateTime(timezone=True))
    error_code = db.Column(db.String(80))
    error_message = db.Column(db.Text)
    request_fingerprint = db.Column(db.String(128))
    response_fingerprint = db.Column(db.String(128))
    source_url_expires_at = db.Column(db.DateTime(timezone=True))
    metadata_json = db.Column(db.JSON)

    empresa = db.relationship("Empresa")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    source_snapshot = db.relationship("DocumentoSnapshot", foreign_keys=[source_snapshot_id])
    artefacto = db.relationship("DocumentoArtefacto", foreign_keys=[artefacto_id])
    solicitado_por = db.relationship("Usuario", foreign_keys=[solicitado_por_id])


class DocumentoEdicion(TenantMixin, BaseModel):
    __tablename__ = "documento_ediciones"
    __table_args__ = (
        db.CheckConstraint(
            "estado IN ('ACTIVA', 'LIBERADA', 'EXPIRADA', 'ERROR', 'CANCELADA')",
            name="ck_documento_ediciones_estado_valido",
        ),
        db.CheckConstraint(
            "fecha_expiracion > fecha_inicio",
            name="ck_documento_ediciones_expiracion_posterior_inicio",
        ),
        db.UniqueConstraint("public_id", name="uq_documento_ediciones_public_id"),
        db.UniqueConstraint("editor_key", name="uq_documento_ediciones_editor_key"),
        db.Index("ix_documento_ediciones_documento_id", "documento_id"),
        db.Index("ix_documento_ediciones_documento_version_id", "documento_version_id"),
        db.Index("ix_documento_ediciones_usuario_id", "usuario_id"),
        db.Index("ix_documento_ediciones_estado", "estado"),
        db.Index("ix_documento_ediciones_fecha_expiracion", "fecha_expiracion"),
        db.Index(
            "uq_documento_ediciones_version_activa",
            "documento_version_id",
            unique=True,
            postgresql_where=db.text("estado = 'ACTIVA'"),
            sqlite_where=db.text("estado = 'ACTIVA'"),
        ),
    )

    public_id = db.Column(db.String(64), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)
    editor_key = db.Column(db.String(128), nullable=False)
    estado = db.Column(db.String(30), default=ESTADO_EDICION_ACTIVA, nullable=False)
    fecha_inicio = db.Column(db.DateTime(timezone=True), nullable=False)
    ultima_actividad = db.Column(db.DateTime(timezone=True), nullable=False)
    fecha_expiracion = db.Column(db.DateTime(timezone=True), nullable=False)
    fecha_liberacion = db.Column(db.DateTime(timezone=True))
    liberado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    motivo_liberacion = db.Column(db.Text)
    hash_inicial = db.Column(db.String(64), nullable=False)
    hash_ultimo_guardado = db.Column(db.String(64))
    ultimo_guardado_en = db.Column(db.DateTime(timezone=True))
    ultimo_callback_en = db.Column(db.DateTime(timezone=True))
    ultimo_callback_status = db.Column(db.Integer)
    ultimo_callback_fingerprint = db.Column(db.String(128))
    error_ultimo_guardado = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
    liberado_por = db.relationship("Usuario", foreign_keys=[liberado_por_id])
    eventos = db.relationship(
        "DocumentoEdicionEvento",
        back_populates="edicion",
        lazy=True,
        cascade="all, delete-orphan",
    )


class DocumentoEdicionEvento(TenantMixin, BaseModel):
    __tablename__ = "documento_edicion_eventos"
    __table_args__ = (
        db.UniqueConstraint("fingerprint", name="uq_documento_edicion_eventos_fingerprint"),
        db.Index("ix_documento_edicion_eventos_edicion_id", "edicion_id"),
        db.Index("ix_documento_edicion_eventos_tipo", "tipo"),
        db.Index("ix_documento_edicion_eventos_fecha_evento", "fecha_evento"),
    )

    edicion_id = db.Column(db.BigInteger, db.ForeignKey("documento_ediciones.id"), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    tipo = db.Column(db.String(50), nullable=False)
    fecha_evento = db.Column(db.DateTime(timezone=True), nullable=False)
    status_callback = db.Column(db.Integer)
    fingerprint = db.Column(db.String(128))
    detalle = db.Column(db.Text)
    ip = db.Column(db.String(50))
    user_agent = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    edicion = db.relationship("DocumentoEdicion", back_populates="eventos")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
