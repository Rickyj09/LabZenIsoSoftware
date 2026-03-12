from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Documento(TenantMixin, BaseModel):
    __tablename__ = "documentos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_documentos_empresa_codigo"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    tipo_documento = db.Column(db.String(50), nullable=False)
    proceso = db.Column(db.String(100))
    estado = db.Column(db.String(30), default="borrador")
    version_actual = db.Column(db.String(20))
    elaborado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa", back_populates="documentos")
    versiones = db.relationship(
        "DocumentoVersion",
        back_populates="documento",
        lazy=True,
        cascade="all, delete-orphan"
    )


class DocumentoVersion(TenantMixin, BaseModel):
    __tablename__ = "documento_versiones"

    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    version = db.Column(db.String(20), nullable=False)
    archivo_url = db.Column(db.String(255))
    contenido = db.Column(db.Text)
    fecha_version = db.Column(db.Date, nullable=False)
    cambios = db.Column(db.Text)
    elaborado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    revisado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    aprobado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    estado = db.Column(db.String(30), default="borrador")
    
    empresa = db.relationship("Empresa")
    documento = db.relationship("Documento", back_populates="versiones")
    aprobaciones = db.relationship(
        "DocumentoAprobacion",
        back_populates="documento_version",
        lazy=True,
        cascade="all, delete-orphan"
    )


class DocumentoAprobacion(TenantMixin, BaseModel):
    __tablename__ = "documento_aprobaciones"

    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)
    accion = db.Column(db.String(30), nullable=False)
    fecha_accion = db.Column(db.DateTime(timezone=True), nullable=False)
    comentario = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    documento_version = db.relationship("DocumentoVersion", back_populates="aprobaciones")