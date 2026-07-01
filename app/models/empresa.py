from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Empresa(BaseModel):
    __tablename__ = "empresas"

    nombre = db.Column(db.String(150), nullable=False)
    ruc = db.Column(db.String(30))
    email = db.Column(db.String(150))
    telefono = db.Column(db.String(50))
    direccion = db.Column(db.Text)
    ciudad = db.Column(db.String(100))
    pais = db.Column(db.String(100), default="Ecuador")
    plan = db.Column(db.String(50), default="trial")
    estado = db.Column(db.String(30), default="activo")
    fecha_inicio_plan = db.Column(db.Date)
    fecha_fin_plan = db.Column(db.Date)

    sedes = db.relationship("Sede", back_populates="empresa", lazy=True)
    usuarios = db.relationship("Usuario", back_populates="empresa", lazy=True)
    clientes = db.relationship("Cliente", back_populates="empresa", lazy=True)
    solicitudes = db.relationship("Solicitud", back_populates="empresa", lazy=True)
    muestras = db.relationship("Muestra", back_populates="empresa", lazy=True)
    ensayos_catalogo = db.relationship("EnsayoCatalogo", back_populates="empresa", lazy=True)
    metodos = db.relationship("Metodo", back_populates="empresa", lazy=True)
    equipos = db.relationship("Equipo", back_populates="empresa", lazy=True)
    documentos = db.relationship("Documento", back_populates="empresa", lazy=True)
    no_conformidades = db.relationship("NoConformidad", back_populates="empresa", lazy=True)
    auditorias = db.relationship("Auditoria", back_populates="empresa", lazy=True)
    auditoria_logs = db.relationship("AuditoriaLog", back_populates="empresa", lazy=True)
    ofertas = db.relationship("Oferta", back_populates="empresa", lazy=True)
    contratos = db.relationship("Contrato", back_populates="empresa", lazy=True)
    muestras = db.relationship("Muestra", back_populates="empresa", lazy=True)

class Sede(TenantMixin, BaseModel):
    __tablename__ = "sedes"

    nombre = db.Column(db.String(150), nullable=False)
    direccion = db.Column(db.Text)
    ciudad = db.Column(db.String(100))
    telefono = db.Column(db.String(50))
    responsable = db.Column(db.String(150))
    estado = db.Column(db.String(30), default="activa")

    empresa = db.relationship("Empresa", back_populates="sedes")
    usuarios = db.relationship("Usuario", back_populates="sede", lazy=True)
    equipos = db.relationship("Equipo", back_populates="sede", lazy=True)