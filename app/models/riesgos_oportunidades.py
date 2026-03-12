from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class RiesgoOportunidad(TenantMixin, BaseModel):
    __tablename__ = "riesgos_oportunidades"

    proceso_id = db.Column(db.BigInteger, db.ForeignKey("procesos.id"), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # riesgo, oportunidad
    descripcion = db.Column(db.Text, nullable=False)
    causa = db.Column(db.Text)
    efecto = db.Column(db.Text)  # consecuencia o beneficio esperado
    probabilidad = db.Column(db.Integer, nullable=False, default=1)
    impacto = db.Column(db.Integer, nullable=False, default=1)
    nivel = db.Column(db.Integer, nullable=False, default=1)
    accion = db.Column(db.Text)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_compromiso = db.Column(db.Date)
    estado = db.Column(db.String(30), default="abierto")  # abierto, en_tratamiento, cerrado

    empresa = db.relationship("Empresa")
    proceso = db.relationship("Proceso", backref="riesgos_oportunidades")
    responsable = db.relationship("Usuario", foreign_keys=[responsable_id])