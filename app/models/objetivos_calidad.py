from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class ObjetivoCalidad(TenantMixin, BaseModel):
    __tablename__ = "objetivos_calidad"

    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    indicador = db.Column(db.String(200), nullable=False)
    meta = db.Column(db.String(100), nullable=False)
    unidad = db.Column(db.String(50))
    frecuencia = db.Column(db.String(30), nullable=False)  # mensual, trimestral, semestral, anual
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date)
    estado = db.Column(db.String(30), default="activo")  # activo, cumplido, vencido, suspendido
    resultado_actual = db.Column(db.String(100))
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    responsable = db.relationship("Usuario", foreign_keys=[responsable_id])
    seguimientos = db.relationship(
        "SeguimientoObjetivoCalidad",
        back_populates="objetivo",
        lazy=True,
        cascade="all, delete-orphan"
    )


class SeguimientoObjetivoCalidad(TenantMixin, BaseModel):
    __tablename__ = "seguimientos_objetivos_calidad"

    objetivo_id = db.Column(db.BigInteger, db.ForeignKey("objetivos_calidad.id"), nullable=False)
    fecha_seguimiento = db.Column(db.Date, nullable=False)
    valor_obtenido = db.Column(db.String(100), nullable=False)
    comentario = db.Column(db.Text)
    estado = db.Column(db.String(30), default="en_revision")  # en_revision, cumple, no_cumple

    empresa = db.relationship("Empresa")
    objetivo = db.relationship("ObjetivoCalidad", back_populates="seguimientos")