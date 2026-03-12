from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Equipo(TenantMixin, BaseModel):
    __tablename__ = "equipos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_equipos_empresa_codigo"),
    )

    sede_id = db.Column(db.BigInteger, db.ForeignKey("sedes.id"))
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    marca = db.Column(db.String(100))
    modelo = db.Column(db.String(100))
    serie = db.Column(db.String(100))
    ubicacion = db.Column(db.String(150))
    fecha_adquisicion = db.Column(db.Date)
    fecha_puesta_servicio = db.Column(db.Date)
    estado = db.Column(db.String(30), default="activo")
    criticidad = db.Column(db.String(30))
    requiere_calibracion = db.Column(db.Boolean, default=False, nullable=False)
    frecuencia_calibracion_meses = db.Column(db.Integer)
    frecuencia_mantenimiento_meses = db.Column(db.Integer)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa", back_populates="equipos")
    sede = db.relationship("Sede", back_populates="equipos")
    calibraciones = db.relationship(
        "EquipoCalibracion",
        back_populates="equipo",
        lazy=True,
        cascade="all, delete-orphan"
    )
    mantenimientos = db.relationship(
        "EquipoMantenimiento",
        back_populates="equipo",
        lazy=True,
        cascade="all, delete-orphan"
    )
    documentos = db.relationship(
        "EquipoDocumento",
        back_populates="equipo",
        lazy=True,
        cascade="all, delete-orphan"
    )


class EquipoCalibracion(TenantMixin, BaseModel):
    __tablename__ = "equipo_calibraciones"

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    fecha_calibracion = db.Column(db.Date, nullable=False)
    fecha_proxima = db.Column(db.Date)
    proveedor = db.Column(db.String(150))
    resultado = db.Column(db.String(50))
    certificado_numero = db.Column(db.String(100))
    archivo_url = db.Column(db.String(255))
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="calibraciones")


class EquipoMantenimiento(TenantMixin, BaseModel):
    __tablename__ = "equipo_mantenimientos"

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    tipo_mantenimiento = db.Column(db.String(50), nullable=False)
    fecha_mantenimiento = db.Column(db.Date, nullable=False)
    fecha_proxima = db.Column(db.Date)
    proveedor = db.Column(db.String(150))
    resultado = db.Column(db.String(50))
    observaciones = db.Column(db.Text)
    archivo_url = db.Column(db.String(255))

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="mantenimientos")


class EquipoDocumento(TenantMixin, BaseModel):
    __tablename__ = "equipo_documentos"

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    tipo_documento = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    archivo_url = db.Column(db.String(255))
    version = db.Column(db.String(20))
    fecha_documento = db.Column(db.Date)

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="documentos")