from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Contrato(TenantMixin, BaseModel):
    __tablename__ = "contratos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_contratos_empresa_codigo"),
    )

    oferta_id = db.Column(
        db.BigInteger,
        db.ForeignKey("ofertas.id"),
        nullable=False,
        index=True
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
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date)

    objeto = db.Column(db.String(255))
    condiciones = db.Column(db.Text)
    estado = db.Column(db.String(30), nullable=False, default="borrador")
    observaciones = db.Column(db.Text)

    creado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa", back_populates="contratos")
    oferta = db.relationship("Oferta", back_populates="contratos")
    solicitud = db.relationship("Solicitud", back_populates="contratos")
    cliente = db.relationship("Cliente", back_populates="contratos")

    creado_por = db.relationship(
        "Usuario",
        foreign_keys=[creado_por_id],
        back_populates="contratos_creados"
    )

    muestras = db.relationship(
    "Muestra",
    back_populates="contrato",
    lazy=True,
    cascade="all, delete-orphan"
    )