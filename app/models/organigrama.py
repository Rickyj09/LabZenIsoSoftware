from app.extensions import db
from app.models.base import BaseModel, TenantMixin


ESTADOS_PERSONAL = ("ACTIVO", "INACTIVO")


class Cargo(TenantMixin, BaseModel):
    __tablename__ = "cargos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_cargos_empresa_codigo"),
        db.UniqueConstraint("empresa_id", "nombre", name="uq_cargos_empresa_nombre"),
        db.Index("ix_cargos_empresa_activo", "empresa_id", "activo"),
    )

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa", back_populates="cargos")
    personal = db.relationship("Personal", back_populates="cargo", lazy=True)
    perfil = db.relationship(
        "PerfilPuesto",
        back_populates="cargo",
        uselist=False,
        lazy=True,
        cascade="all, delete-orphan",
    )


class PerfilPuesto(TenantMixin, BaseModel):
    __tablename__ = "perfiles_puesto"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "cargo_id", name="uq_perfiles_puesto_empresa_cargo"),
        db.Index("ix_perfiles_puesto_empresa_activo", "empresa_id", "activo"),
    )

    cargo_id = db.Column(db.Integer, db.ForeignKey("cargos.id"), nullable=False)
    proposito = db.Column(db.Text)
    funciones = db.Column(db.Text)
    responsabilidades = db.Column(db.Text)
    autoridad = db.Column(db.Text)
    observaciones = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa")
    cargo = db.relationship("Cargo", back_populates="perfil")


class Personal(TenantMixin, BaseModel):
    __tablename__ = "personal"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_personal_empresa_codigo"),
        db.UniqueConstraint("empresa_id", "identificacion", name="uq_personal_empresa_identificacion"),
        db.UniqueConstraint("empresa_id", "usuario_id", name="uq_personal_empresa_usuario"),
        db.CheckConstraint("estado IN ('ACTIVO', 'INACTIVO')", name="ck_personal_estado_valido"),
        db.CheckConstraint(
            "fecha_salida IS NULL OR fecha_ingreso IS NULL OR fecha_salida >= fecha_ingreso",
            name="ck_personal_fechas_ordenadas",
        ),
        db.Index("ix_personal_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_personal_empresa_cargo", "empresa_id", "cargo_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False)
    nombres = db.Column(db.String(120), nullable=False)
    apellidos = db.Column(db.String(120), nullable=False)
    identificacion = db.Column(db.String(50))
    email = db.Column(db.String(150))
    correo = db.synonym("email")
    telefono = db.Column(db.String(50))
    cargo_id = db.Column(db.Integer, db.ForeignKey("cargos.id"), nullable=False)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_ingreso = db.Column(db.Date)
    fecha_salida = db.Column(db.Date)
    estado = db.Column(db.String(20), nullable=False, default="ACTIVO")
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa", back_populates="personal")
    cargo = db.relationship("Cargo", back_populates="personal")
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id], back_populates="personal")

    @property
    def nombre(self):
        return self.nombre_completo

    @property
    def nombre_completo(self):
        return " ".join(part for part in [self.nombres, self.apellidos] if part).strip()

    @property
    def activo(self):
        return self.estado == "ACTIVO"
