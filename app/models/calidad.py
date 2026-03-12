from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class NoConformidad(TenantMixin, BaseModel):
    __tablename__ = "no_conformidades"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_nc_empresa_codigo"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    fuente = db.Column(db.String(50), nullable=False)
    fecha_detectada = db.Column(db.Date, nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    impacto = db.Column(db.Text)
    estado = db.Column(db.String(30), default="abierta")
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa", back_populates="no_conformidades")
    acciones_correctivas = db.relationship(
        "AccionCorrectiva",
        back_populates="no_conformidad",
        lazy=True
    )


class AccionCorrectiva(TenantMixin, BaseModel):
    __tablename__ = "acciones_correctivas"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_ac_empresa_codigo"),
    )

    no_conformidad_id = db.Column(db.BigInteger, db.ForeignKey("no_conformidades.id"))
    hallazgo_id = db.Column(db.BigInteger, db.ForeignKey("auditoria_hallazgos.id"))
    codigo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    causa_raiz = db.Column(db.Text)
    plan_accion = db.Column(db.Text)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_compromiso = db.Column(db.Date)
    fecha_cierre = db.Column(db.Date)
    eficaz = db.Column(db.Boolean)
    estado = db.Column(db.String(30), default="abierta")

    empresa = db.relationship("Empresa")
    no_conformidad = db.relationship("NoConformidad", back_populates="acciones_correctivas")
    hallazgo = db.relationship("AuditoriaHallazgo", back_populates="acciones_correctivas")


class Riesgo(TenantMixin, BaseModel):
    __tablename__ = "riesgos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_riesgo_empresa_codigo"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    proceso = db.Column(db.String(100))
    descripcion = db.Column(db.Text, nullable=False)
    probabilidad = db.Column(db.Integer)
    impacto = db.Column(db.Integer)
    nivel_riesgo = db.Column(db.Integer)
    tratamiento = db.Column(db.Text)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    estado = db.Column(db.String(30), default="activo")

    empresa = db.relationship("Empresa")


class PersonalCompetencia(TenantMixin, BaseModel):
    __tablename__ = "personal_competencias"

    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)
    competencia = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    nivel = db.Column(db.String(50))
    fecha_evaluacion = db.Column(db.Date)
    evaluado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    resultado = db.Column(db.String(50))
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    usuario = db.relationship(
        "Usuario",
        foreign_keys=[usuario_id],
        back_populates="competencias"
    )