from app.extensions import db
from app.models.base import BaseModel, TenantMixin


ESTADOS_DOCUMENTO = (
    "BORRADOR",
    "EN_REVISION",
    "APROBADO",
    "RECHAZADO",
    "OBSOLETO",
)

ESTADOS_VERSION_DOCUMENTO = (
    "BORRADOR",
    "EN_REVISION",
    "APROBADO",
    "RECHAZADO",
    "OBSOLETO",
    "SUSTITUIDO",
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


class Documento(TenantMixin, BaseModel):
    __tablename__ = "documentos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_documentos_empresa_codigo"),
        db.CheckConstraint(
            "estado IN ('BORRADOR', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO')",
            name="ck_documentos_estado_valido",
        ),
    )

    codigo = db.Column(db.String(50), nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    tipo_documento = db.Column(db.String(50), nullable=False)
    proceso = db.Column(db.String(100))
    estado = db.Column(db.String(30), default="BORRADOR", nullable=False)
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
            "estado IN ('BORRADOR', 'EN_REVISION', 'APROBADO', 'RECHAZADO', 'OBSOLETO', 'SUSTITUIDO')",
            name="ck_documento_versiones_estado_valido",
        ),
        db.Index("ix_documento_versiones_documento_id", "documento_id"),
        db.Index("ix_documento_versiones_estado", "estado"),
        db.Index(
            "uq_documento_version_preparacion_activa",
            "documento_id",
            unique=True,
            postgresql_where=db.text("estado IN ('BORRADOR', 'EN_REVISION')"),
            sqlite_where=db.text("estado IN ('BORRADOR', 'EN_REVISION')"),
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
    estado = db.Column(db.String(30), default="BORRADOR", nullable=False)

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
