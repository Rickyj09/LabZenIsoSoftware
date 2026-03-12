from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Proceso(TenantMixin, BaseModel):
    __tablename__ = "procesos"

    nombre = db.Column(db.String(200), nullable=False)
    codigo = db.Column(db.String(50))
    tipo = db.Column(db.String(30), nullable=False)  # estrategico, misional, apoyo
    objetivo = db.Column(db.Text)
    alcance = db.Column(db.Text)
    entradas = db.Column(db.Text)
    salidas = db.Column(db.Text)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    estado = db.Column(db.String(30), default="activo")

    empresa = db.relationship("Empresa")
    responsable = db.relationship("Usuario", foreign_keys=[responsable_id])