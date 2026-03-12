from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Cliente(TenantMixin, BaseModel):
    __tablename__ = "clientes"

    tipo_cliente = db.Column(db.String(30))
    identificacion = db.Column(db.String(30))
    nombre_razon_social = db.Column(db.String(200), nullable=False)
    contacto_nombre = db.Column(db.String(150))
    contacto_email = db.Column(db.String(150))
    contacto_telefono = db.Column(db.String(50))
    direccion = db.Column(db.Text)
    ciudad = db.Column(db.String(100))
    estado = db.Column(db.String(30), default="activo")

    empresa = db.relationship("Empresa", back_populates="clientes")
    solicitudes = db.relationship(
        "Solicitud",
        back_populates="cliente",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Solicitud(TenantMixin, BaseModel):
    __tablename__ = "solicitudes"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_solicitudes_empresa_codigo"),
    )

    cliente_id = db.Column(db.BigInteger, db.ForeignKey("clientes.id"), nullable=False)
    codigo = db.Column(db.String(50), nullable=False)
    fecha_solicitud = db.Column(db.Date, nullable=False)
    fecha_recepcion = db.Column(db.Date)
    tipo_servicio = db.Column(db.String(100))
    descripcion = db.Column(db.Text)
    estado = db.Column(db.String(30), default="recibida")
    observaciones = db.Column(db.Text)
    creado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa", back_populates="solicitudes")
    cliente = db.relationship("Cliente", back_populates="solicitudes")
    creado_por = db.relationship(
        "Usuario",
        foreign_keys=[creado_por_id],
        back_populates="solicitudes_creadas"
    )
    muestras = db.relationship(
        "Muestra",
        back_populates="solicitud",
        lazy=True,
        cascade="all, delete-orphan"
    )