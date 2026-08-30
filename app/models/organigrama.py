from app.extensions import db
from app.models.base import BaseModel, TenantMixin


ESTADOS_PERSONAL = ("ACTIVO", "INACTIVO")
TIPOS_CALIFICACION_PERSONAL = ("EDUCACION_FORMAL", "CERTIFICACION", "LICENCIA", "OTRO")


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
    calificaciones = db.relationship(
        "PersonalCalificacion",
        back_populates="personal",
        lazy=True,
        order_by="PersonalCalificacion.fecha_fin.desc(), PersonalCalificacion.id.desc()",
        cascade="all, delete-orphan",
    )
    experiencias = db.relationship(
        "PersonalExperiencia",
        back_populates="personal",
        lazy=True,
        order_by="PersonalExperiencia.fecha_inicio.desc(), PersonalExperiencia.id.desc()",
        cascade="all, delete-orphan",
    )

    @property
    def nombre(self):
        return self.nombre_completo

    @property
    def nombre_completo(self):
        return " ".join(part for part in [self.nombres, self.apellidos] if part).strip()

    @property
    def activo(self):
        return self.estado == "ACTIVO"


class PersonalCalificacion(TenantMixin, BaseModel):
    __tablename__ = "personal_calificaciones"
    __table_args__ = (
        db.CheckConstraint(
            "tipo IN ('EDUCACION_FORMAL', 'CERTIFICACION', 'LICENCIA', 'OTRO')",
            name="ck_personal_calificaciones_tipo_valido",
        ),
        db.CheckConstraint(
            "fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_calificaciones_fechas_ordenadas",
        ),
        db.Index("ix_personal_calificaciones_empresa_personal", "empresa_id", "personal_id"),
        db.Index("ix_personal_calificaciones_empresa_tipo", "empresa_id", "tipo"),
        db.Index("ix_personal_calificaciones_empresa_activo", "empresa_id", "activo"),
    )

    personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)
    institucion = db.Column(db.String(180), nullable=False)
    titulo = db.Column(db.String(180), nullable=False)
    area_especialidad = db.Column(db.String(150))
    fecha_inicio = db.Column(db.Date)
    fecha_fin = db.Column(db.Date)
    numero_registro = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa")
    personal = db.relationship("Personal", back_populates="calificaciones")
    evidencias = db.relationship(
        "PersonalCalificacionEvidencia",
        back_populates="calificacion",
        lazy=True,
        order_by="PersonalCalificacionEvidencia.created_at.desc(), PersonalCalificacionEvidencia.id.desc()",
        cascade="all, delete-orphan",
    )


class PersonalExperiencia(TenantMixin, BaseModel):
    __tablename__ = "personal_experiencias"
    __table_args__ = (
        db.CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_experiencias_fechas_ordenadas",
        ),
        db.CheckConstraint(
            "experiencia_actual = FALSE OR fecha_fin IS NULL",
            name="ck_personal_experiencias_actual_sin_fecha_fin",
        ),
        db.Index("ix_personal_experiencias_empresa_personal", "empresa_id", "personal_id"),
        db.Index("ix_personal_experiencias_empresa_activo", "empresa_id", "activo"),
    )

    personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"), nullable=False)
    organizacion = db.Column(db.String(180), nullable=False)
    cargo_funcion = db.Column(db.String(180), nullable=False)
    area_especialidad = db.Column(db.String(150))
    descripcion_actividades = db.Column(db.Text)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date)
    experiencia_actual = db.Column(db.Boolean, default=False, nullable=False)
    observaciones = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa")
    personal = db.relationship("Personal", back_populates="experiencias")


class PersonalCalificacionEvidencia(TenantMixin, BaseModel):
    __tablename__ = "personal_calificacion_evidencias"
    __table_args__ = (
        db.Index("ix_personal_calificacion_evidencias_empresa_calificacion", "empresa_id", "calificacion_id"),
        db.Index("ix_personal_calificacion_evidencias_empresa_personal", "empresa_id", "personal_id"),
        db.Index("ix_personal_calificacion_evidencias_empresa_activo", "empresa_id", "activo"),
    )

    personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"), nullable=False)
    calificacion_id = db.Column(db.BigInteger, db.ForeignKey("personal_calificaciones.id"), nullable=False)
    archivo_nombre_original = db.Column(db.String(255), nullable=False)
    archivo_nombre_guardado = db.Column(db.String(255), nullable=False)
    archivo_storage_path = db.Column(db.String(500), nullable=False)
    archivo_mime = db.Column(db.String(150), nullable=False)
    archivo_size = db.Column(db.BigInteger, nullable=False)
    archivo_sha256 = db.Column(db.String(64), nullable=False)
    cargado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    activo = db.Column(db.Boolean, default=True, nullable=False)
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    personal = db.relationship("Personal")
    calificacion = db.relationship("PersonalCalificacion", back_populates="evidencias")
    cargado_por = db.relationship("Usuario", foreign_keys=[cargado_por_id])
