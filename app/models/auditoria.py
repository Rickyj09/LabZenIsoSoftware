from app.extensions import db
from app.models.base import BaseModel, TenantMixin



class Auditoria(TenantMixin, BaseModel):
    __tablename__ = "auditorias"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_auditoria_empresa_codigo"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    tipo_auditoria = db.Column(db.String(50), nullable=False)
    alcance = db.Column(db.Text)
    fecha_inicio = db.Column(db.Date)
    fecha_fin = db.Column(db.Date)
    auditor_lider_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    estado = db.Column(db.String(30), default="planificada")
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa", back_populates="auditorias")
    hallazgos = db.relationship(
        "AuditoriaHallazgo",
        back_populates="auditoria",
        lazy=True,
        cascade="all, delete-orphan"
    )


class AuditoriaHallazgo(TenantMixin, BaseModel):
    __tablename__ = "auditoria_hallazgos"

    auditoria_id = db.Column(db.BigInteger, db.ForeignKey("auditorias.id"), nullable=False)
    tipo_hallazgo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    requisito_incumplido = db.Column(db.String(200))
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    estado = db.Column(db.String(30), default="abierto")

    empresa = db.relationship("Empresa")
    auditoria = db.relationship("Auditoria", back_populates="hallazgos")
    acciones_correctivas = db.relationship(
        "AccionCorrectiva",
        back_populates="hallazgo",
        lazy=True
    )


class AuditoriaLog(TenantMixin, BaseModel):
    __tablename__ = "auditoria_logs"

    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    tabla = db.Column(db.String(100), nullable=False)
    registro_id = db.Column(db.BigInteger, nullable=False)
    accion = db.Column(db.String(30), nullable=False)
    datos_antes = db.Column(db.JSON)
    datos_despues = db.Column(db.JSON)
    ip = db.Column(db.String(50))
    user_agent = db.Column(db.Text)

    empresa = db.relationship("Empresa", back_populates="auditoria_logs")
    usuario = db.relationship("Usuario", back_populates="logs")

   
