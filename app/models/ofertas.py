from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Oferta(TenantMixin, BaseModel):
    __tablename__ = "ofertas"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_ofertas_empresa_codigo"),
    )

    solicitud_id = db.Column(
        db.BigInteger,
        db.ForeignKey("solicitudes.id"),
        nullable=False,
        index=True
    )

    cliente_id = db.Column(
        db.BigInteger,
        db.ForeignKey("clientes.id"),
        nullable=False,
        index=True
    )

    codigo = db.Column(db.String(50), nullable=False)
    fecha_emision = db.Column(db.Date, nullable=False)
    fecha_vencimiento = db.Column(db.Date)

    objeto = db.Column(db.String(255))
    alcance = db.Column(db.Text)
    condiciones = db.Column(db.Text)

    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    impuestos = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    estado = db.Column(db.String(30), nullable=False, default="borrador")
    observaciones = db.Column(db.Text)

    creado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa", back_populates="ofertas")
    solicitud = db.relationship("Solicitud", back_populates="ofertas")
    cliente = db.relationship("Cliente", back_populates="ofertas")

    creado_por = db.relationship(
        "Usuario",
        foreign_keys=[creado_por_id],
        back_populates="ofertas_creadas"
    )

    contratos = db.relationship(
    "Contrato",
    back_populates="oferta",
    lazy=True,
    cascade="all, delete-orphan"
    )