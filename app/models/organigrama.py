from app.extensions import db
from app.models.base import BaseModel, TenantMixin
from datetime import date


ESTADOS_PERSONAL = ("ACTIVO", "INACTIVO")
TIPOS_CALIFICACION_PERSONAL = ("EDUCACION_FORMAL", "CERTIFICACION", "LICENCIA", "OTRO")
TIPOS_CAPACITACION_PERSONAL = ("INTERNA", "EXTERNA", "INDUCCION", "ACTUALIZACION", "ENTRENAMIENTO", "OTRO")
MODALIDADES_CAPACITACION_PERSONAL = ("PRESENCIAL", "VIRTUAL", "HIBRIDA")
ESTADOS_CAPACITACION_PERSONAL = ("PLANIFICADA", "EN_CURSO", "COMPLETADA", "CANCELADA")
ESTADOS_PARTICIPACION_CAPACITACION = ("INSCRITO", "ASISTIO", "COMPLETO", "NO_ASISTIO", "RETIRADO")
TIPOS_EVIDENCIA_CAPACITACION = ("CERTIFICADO", "LISTA_ASISTENCIA", "DIPLOMA", "CONSTANCIA", "MATERIAL", "OTRO")
TIPOS_COMPETENCIA_PERSONAL = ("TECNICA", "EQUIPO", "METODO", "MUESTREO", "RESULTADOS", "SISTEMA_GESTION", "OTRA")
METODOS_EVALUACION_COMPETENCIA = (
    "OBSERVACION_DIRECTA",
    "DEMOSTRACION_PRACTICA",
    "EXAMEN_TEORICO",
    "EXAMEN_PRACTICO",
    "REVISION_DE_RESULTADOS",
    "MUESTRA_DESCONOCIDA",
    "COMPARACION_INTERLABORATORIO",
    "SUPERVISION",
    "OTRO",
)
RESULTADOS_EVALUACION_COMPETENCIA = (
    "COMPETENTE",
    "COMPETENTE_CON_OBSERVACIONES",
    "REQUIERE_ENTRENAMIENTO",
    "NO_COMPETENTE",
)
TIPOS_EVIDENCIA_EVALUACION_COMPETENCIA = (
    "CHECKLIST",
    "FORMATO_EVALUACION",
    "FOTOGRAFIA",
    "ACTA",
    "INFORME",
    "RESULTADO_PRACTICO",
    "PDF_FIRMADO",
    "HOJA_CALCULO",
    "OTRO",
)
TIPOS_AUTORIZACION_TECNICA = (
    "ACTIVIDAD_TECNICA",
    "EQUIPO",
    "METODO",
    "MUESTREO",
    "REVISION_RESULTADOS",
    "AUTORIZACION_RESULTADOS",
    "OPINION_INTERPRETACION",
    "DESARROLLO_METODO",
    "VALIDACION_METODO",
    "OTRA",
)
ESTADOS_AUTORIZACION_TECNICA = ("VIGENTE", "SUSPENDIDA", "REVOCADA")
TIPOS_EVIDENCIA_AUTORIZACION_TECNICA = (
    "ACTA_AUTORIZACION",
    "MATRIZ_FIRMADA",
    "FORMATO_AUTORIZACION",
    "CERTIFICADO",
    "RESOLUCION_INTERNA",
    "OTRO",
)


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
    capacitaciones_participacion = db.relationship(
        "PersonalCapacitacionParticipante",
        back_populates="personal",
        lazy=True,
        order_by="PersonalCapacitacionParticipante.created_at.desc(), PersonalCapacitacionParticipante.id.desc()",
        cascade="all, delete-orphan",
    )
    evaluaciones_competencia = db.relationship(
        "PersonalEvaluacionCompetencia",
        foreign_keys="PersonalEvaluacionCompetencia.personal_id",
        back_populates="personal",
        lazy=True,
        order_by="PersonalEvaluacionCompetencia.fecha_evaluacion.desc(), PersonalEvaluacionCompetencia.id.desc()",
        cascade="all, delete-orphan",
    )
    evaluaciones_competencia_realizadas = db.relationship(
        "PersonalEvaluacionCompetencia",
        foreign_keys="PersonalEvaluacionCompetencia.evaluador_personal_id",
        back_populates="evaluador_personal",
        lazy=True,
    )
    autorizaciones_tecnicas = db.relationship(
        "PersonalAutorizacionTecnica",
        foreign_keys="PersonalAutorizacionTecnica.personal_id",
        back_populates="personal",
        lazy=True,
        order_by="PersonalAutorizacionTecnica.fecha_inicio.desc(), PersonalAutorizacionTecnica.id.desc()",
        cascade="all, delete-orphan",
    )
    autorizaciones_tecnicas_otorgadas = db.relationship(
        "PersonalAutorizacionTecnica",
        foreign_keys="PersonalAutorizacionTecnica.autorizador_personal_id",
        back_populates="autorizador_personal",
        lazy=True,
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


class PersonalCapacitacion(TenantMixin, BaseModel):
    __tablename__ = "personal_capacitaciones"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_personal_capacitaciones_empresa_codigo"),
        db.CheckConstraint(
            "tipo IN ('INTERNA', 'EXTERNA', 'INDUCCION', 'ACTUALIZACION', 'ENTRENAMIENTO', 'OTRO')",
            name="ck_personal_capacitaciones_tipo_valido",
        ),
        db.CheckConstraint(
            "modalidad IN ('PRESENCIAL', 'VIRTUAL', 'HIBRIDA')",
            name="ck_personal_capacitaciones_modalidad_valida",
        ),
        db.CheckConstraint(
            "estado IN ('PLANIFICADA', 'EN_CURSO', 'COMPLETADA', 'CANCELADA')",
            name="ck_personal_capacitaciones_estado_valido",
        ),
        db.CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_capacitaciones_fechas_ordenadas",
        ),
        db.CheckConstraint(
            "duracion_horas IS NULL OR duracion_horas >= 0",
            name="ck_personal_capacitaciones_duracion_no_negativa",
        ),
        db.Index("ix_personal_capacitaciones_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_personal_capacitaciones_empresa_tipo", "empresa_id", "tipo"),
        db.Index("ix_personal_capacitaciones_empresa_fechas", "empresa_id", "fecha_inicio", "fecha_fin"),
    )

    codigo = db.Column(db.String(50))
    nombre = db.Column(db.String(180), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)
    objetivo = db.Column(db.Text)
    proveedor = db.Column(db.String(180))
    instructor = db.Column(db.String(180))
    modalidad = db.Column(db.String(20), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date)
    duracion_horas = db.Column(db.Numeric(8, 2))
    lugar = db.Column(db.String(180))
    estado = db.Column(db.String(20), nullable=False, default="PLANIFICADA")
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    participantes = db.relationship(
        "PersonalCapacitacionParticipante",
        back_populates="capacitacion",
        lazy=True,
        order_by="PersonalCapacitacionParticipante.created_at.asc(), PersonalCapacitacionParticipante.id.asc()",
        cascade="all, delete-orphan",
    )
    evidencias = db.relationship(
        "PersonalCapacitacionEvidencia",
        back_populates="capacitacion",
        lazy=True,
        order_by="PersonalCapacitacionEvidencia.created_at.desc(), PersonalCapacitacionEvidencia.id.desc()",
        cascade="all, delete-orphan",
    )


class PersonalCapacitacionParticipante(TenantMixin, BaseModel):
    __tablename__ = "personal_capacitacion_participantes"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "capacitacion_id", "personal_id", name="uq_personal_cap_participante_unico"),
        db.CheckConstraint(
            "estado_participacion IN ('INSCRITO', 'ASISTIO', 'COMPLETO', 'NO_ASISTIO', 'RETIRADO')",
            name="ck_personal_cap_participantes_estado_valido",
        ),
        db.Index("ix_personal_cap_participantes_empresa_capacitacion", "empresa_id", "capacitacion_id"),
        db.Index("ix_personal_cap_participantes_empresa_personal", "empresa_id", "personal_id"),
        db.Index("ix_personal_cap_participantes_empresa_estado", "empresa_id", "estado_participacion"),
    )

    capacitacion_id = db.Column(db.BigInteger, db.ForeignKey("personal_capacitaciones.id"), nullable=False)
    personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"), nullable=False)
    estado_participacion = db.Column(db.String(20), nullable=False, default="INSCRITO")
    fecha_registro = db.Column(db.Date, nullable=False)
    observaciones = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa")
    capacitacion = db.relationship("PersonalCapacitacion", back_populates="participantes")
    personal = db.relationship("Personal", back_populates="capacitaciones_participacion")
    evidencias = db.relationship(
        "PersonalCapacitacionEvidencia",
        back_populates="participante",
        lazy=True,
        order_by="PersonalCapacitacionEvidencia.created_at.desc(), PersonalCapacitacionEvidencia.id.desc()",
    )


class PersonalCapacitacionEvidencia(TenantMixin, BaseModel):
    __tablename__ = "personal_capacitacion_evidencias"
    __table_args__ = (
        db.CheckConstraint(
            "tipo_evidencia IN ('CERTIFICADO', 'LISTA_ASISTENCIA', 'DIPLOMA', 'CONSTANCIA', 'MATERIAL', 'OTRO')",
            name="ck_personal_cap_evidencias_tipo_valido",
        ),
        db.Index("ix_personal_cap_evidencias_empresa_capacitacion", "empresa_id", "capacitacion_id"),
        db.Index("ix_personal_cap_evidencias_empresa_participante", "empresa_id", "participante_id"),
        db.Index("ix_personal_cap_evidencias_empresa_activo", "empresa_id", "activo"),
    )

    capacitacion_id = db.Column(db.BigInteger, db.ForeignKey("personal_capacitaciones.id"), nullable=False)
    participante_id = db.Column(db.BigInteger, db.ForeignKey("personal_capacitacion_participantes.id"))
    archivo_nombre_original = db.Column(db.String(255), nullable=False)
    archivo_nombre_guardado = db.Column(db.String(255), nullable=False)
    archivo_storage_path = db.Column(db.String(500), nullable=False)
    archivo_mime = db.Column(db.String(150), nullable=False)
    archivo_size = db.Column(db.BigInteger, nullable=False)
    archivo_sha256 = db.Column(db.String(64), nullable=False)
    tipo_evidencia = db.Column(db.String(30), nullable=False)
    cargado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    activo = db.Column(db.Boolean, default=True, nullable=False)
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    capacitacion = db.relationship("PersonalCapacitacion", back_populates="evidencias")
    participante = db.relationship("PersonalCapacitacionParticipante", back_populates="evidencias")
    cargado_por = db.relationship("Usuario", foreign_keys=[cargado_por_id])


class PersonalEvaluacionCompetencia(TenantMixin, BaseModel):
    __tablename__ = "personal_evaluaciones_competencia"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_personal_eval_comp_empresa_codigo"),
        db.CheckConstraint(
            "tipo_competencia IN ('TECNICA', 'EQUIPO', 'METODO', 'MUESTREO', 'RESULTADOS', 'SISTEMA_GESTION', 'OTRA')",
            name="ck_personal_eval_comp_tipo_valido",
        ),
        db.CheckConstraint(
            "metodo_evaluacion IN ('OBSERVACION_DIRECTA', 'DEMOSTRACION_PRACTICA', 'EXAMEN_TEORICO', 'EXAMEN_PRACTICO', 'REVISION_DE_RESULTADOS', 'MUESTRA_DESCONOCIDA', 'COMPARACION_INTERLABORATORIO', 'SUPERVISION', 'OTRO')",
            name="ck_personal_eval_comp_metodo_valido",
        ),
        db.CheckConstraint(
            "resultado IN ('COMPETENTE', 'COMPETENTE_CON_OBSERVACIONES', 'REQUIERE_ENTRENAMIENTO', 'NO_COMPETENTE')",
            name="ck_personal_eval_comp_resultado_valido",
        ),
        db.CheckConstraint(
            "evaluador_personal_id IS NOT NULL OR evaluador_externo_nombre IS NOT NULL",
            name="ck_personal_eval_comp_evaluador_requerido",
        ),
        db.Index("ix_personal_eval_comp_empresa_personal", "empresa_id", "personal_id"),
        db.Index("ix_personal_eval_comp_empresa_evaluador", "empresa_id", "evaluador_personal_id"),
        db.Index("ix_personal_eval_comp_empresa_resultado", "empresa_id", "resultado"),
        db.Index("ix_personal_eval_comp_empresa_tipo", "empresa_id", "tipo_competencia"),
        db.Index("ix_personal_eval_comp_empresa_fecha", "empresa_id", "fecha_evaluacion"),
        db.Index("ix_personal_eval_comp_empresa_activo", "empresa_id", "activo"),
    )

    personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"), nullable=False)
    evaluador_personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"))
    evaluador_usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    capacitacion_id = db.Column(db.BigInteger, db.ForeignKey("personal_capacitaciones.id"))
    capacitacion_participante_id = db.Column(db.BigInteger, db.ForeignKey("personal_capacitacion_participantes.id"))
    codigo = db.Column(db.String(50))
    actividad = db.Column(db.String(180), nullable=False)
    descripcion = db.Column(db.Text)
    tipo_competencia = db.Column(db.String(30), nullable=False, default="TECNICA")
    metodo_evaluacion = db.Column(db.String(40), nullable=False)
    criterio_evaluacion = db.Column(db.Text, nullable=False)
    criterios = db.Column(db.Text)
    descripcion_metodo = db.Column(db.Text)
    fecha_evaluacion = db.Column(db.Date, nullable=False)
    resultado = db.Column(db.String(40), nullable=False)
    conclusion = db.Column(db.Text)
    observaciones = db.Column(db.Text)
    evaluador_externo_nombre = db.Column(db.String(180))
    evaluador_externo_entidad = db.Column(db.String(180))
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa")
    personal = db.relationship("Personal", foreign_keys=[personal_id], back_populates="evaluaciones_competencia")
    evaluador_personal = db.relationship(
        "Personal",
        foreign_keys=[evaluador_personal_id],
        back_populates="evaluaciones_competencia_realizadas",
    )
    evaluador_usuario = db.relationship("Usuario", foreign_keys=[evaluador_usuario_id])
    capacitacion = db.relationship("PersonalCapacitacion")
    capacitacion_participante = db.relationship("PersonalCapacitacionParticipante")
    evidencias = db.relationship(
        "PersonalEvaluacionCompetenciaEvidencia",
        back_populates="evaluacion",
        lazy=True,
        order_by="PersonalEvaluacionCompetenciaEvidencia.created_at.desc(), PersonalEvaluacionCompetenciaEvidencia.id.desc()",
        cascade="all, delete-orphan",
    )

    @property
    def evaluador_nombre(self):
        if self.evaluador_personal:
            return self.evaluador_personal.nombre_completo
        if self.evaluador_externo_nombre:
            return self.evaluador_externo_nombre
        if self.evaluador_usuario:
            return f"{self.evaluador_usuario.nombre} {self.evaluador_usuario.apellido}".strip()
        return "-"


class PersonalEvaluacionCompetenciaEvidencia(TenantMixin, BaseModel):
    __tablename__ = "personal_evaluacion_competencia_evidencias"
    __table_args__ = (
        db.CheckConstraint(
            "tipo_evidencia IN ('CHECKLIST', 'FORMATO_EVALUACION', 'FOTOGRAFIA', 'ACTA', 'INFORME', 'RESULTADO_PRACTICO', 'PDF_FIRMADO', 'HOJA_CALCULO', 'OTRO')",
            name="ck_personal_eval_comp_evidencias_tipo_valido",
        ),
        db.Index("ix_personal_eval_comp_evid_empresa_eval", "empresa_id", "evaluacion_id"),
        db.Index("ix_personal_eval_comp_evid_empresa_activo", "empresa_id", "activo"),
    )

    evaluacion_id = db.Column(db.BigInteger, db.ForeignKey("personal_evaluaciones_competencia.id"), nullable=False)
    tipo_evidencia = db.Column(db.String(30), nullable=False)
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
    evaluacion = db.relationship("PersonalEvaluacionCompetencia", back_populates="evidencias")
    cargado_por = db.relationship("Usuario", foreign_keys=[cargado_por_id])


class PersonalAutorizacionTecnica(TenantMixin, BaseModel):
    __tablename__ = "personal_autorizaciones_tecnicas"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_personal_aut_tec_empresa_codigo"),
        db.CheckConstraint(
            "tipo_autorizacion IN ('ACTIVIDAD_TECNICA', 'EQUIPO', 'METODO', 'MUESTREO', 'REVISION_RESULTADOS', 'AUTORIZACION_RESULTADOS', 'OPINION_INTERPRETACION', 'DESARROLLO_METODO', 'VALIDACION_METODO', 'OTRA')",
            name="ck_personal_aut_tec_tipo_valido",
        ),
        db.CheckConstraint(
            "estado IN ('VIGENTE', 'SUSPENDIDA', 'REVOCADA')",
            name="ck_personal_aut_tec_estado_valido",
        ),
        db.CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio",
            name="ck_personal_aut_tec_fechas_ordenadas",
        ),
        db.CheckConstraint(
            "tipo_autorizacion <> 'EQUIPO' OR equipo_id IS NOT NULL",
            name="ck_personal_aut_tec_equipo_requerido",
        ),
        db.CheckConstraint(
            "tipo_autorizacion <> 'METODO' OR metodo_referencia IS NOT NULL",
            name="ck_personal_aut_tec_metodo_requerido",
        ),
        db.CheckConstraint(
            "autorizador_personal_id IS NOT NULL OR autorizador_usuario_id IS NOT NULL OR autorizador_externo_nombre IS NOT NULL",
            name="ck_personal_aut_tec_autorizador_requerido",
        ),
        db.Index("ix_personal_aut_tec_empresa_personal", "empresa_id", "personal_id"),
        db.Index("ix_personal_aut_tec_empresa_equipo", "empresa_id", "equipo_id"),
        db.Index("ix_personal_aut_tec_empresa_evaluacion", "empresa_id", "evaluacion_competencia_id"),
        db.Index("ix_personal_aut_tec_empresa_tipo", "empresa_id", "tipo_autorizacion"),
        db.Index("ix_personal_aut_tec_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_personal_aut_tec_empresa_vigencia", "empresa_id", "fecha_inicio", "fecha_fin"),
    )

    personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"), nullable=False)
    codigo = db.Column(db.String(50))
    tipo_autorizacion = db.Column(db.String(40), nullable=False)
    actividad = db.Column(db.String(180), nullable=False)
    alcance = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.Text)
    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"))
    metodo_referencia = db.Column(db.String(120))
    metodo_descripcion = db.Column(db.Text)
    evaluacion_competencia_id = db.Column(db.BigInteger, db.ForeignKey("personal_evaluaciones_competencia.id"))
    autorizador_personal_id = db.Column(db.BigInteger, db.ForeignKey("personal.id"))
    autorizador_usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    autorizador_externo_nombre = db.Column(db.String(180))
    autorizador_externo_entidad = db.Column(db.String(180))
    fecha_autorizacion = db.Column(db.Date, nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date)
    estado = db.Column(db.String(20), nullable=False, default="VIGENTE")
    fundamento = db.Column(db.Text, nullable=False)
    observaciones = db.Column(db.Text)
    motivo_estado = db.Column(db.Text)
    fecha_estado = db.Column(db.Date)

    empresa = db.relationship("Empresa")
    personal = db.relationship("Personal", foreign_keys=[personal_id], back_populates="autorizaciones_tecnicas")
    equipo = db.relationship("Equipo")
    evaluacion_competencia = db.relationship("PersonalEvaluacionCompetencia")
    autorizador_personal = db.relationship(
        "Personal",
        foreign_keys=[autorizador_personal_id],
        back_populates="autorizaciones_tecnicas_otorgadas",
    )
    autorizador_usuario = db.relationship("Usuario", foreign_keys=[autorizador_usuario_id])
    evidencias = db.relationship(
        "PersonalAutorizacionTecnicaEvidencia",
        back_populates="autorizacion",
        lazy=True,
        order_by="PersonalAutorizacionTecnicaEvidencia.created_at.desc(), PersonalAutorizacionTecnicaEvidencia.id.desc()",
        cascade="all, delete-orphan",
    )

    @property
    def autorizador_nombre(self):
        if self.autorizador_personal:
            return self.autorizador_personal.nombre_completo
        if self.autorizador_usuario:
            return f"{self.autorizador_usuario.nombre} {self.autorizador_usuario.apellido}".strip()
        if self.autorizador_externo_nombre:
            return self.autorizador_externo_nombre
        return "-"

    @property
    def estado_efectivo(self):
        if self.estado in {"REVOCADA", "SUSPENDIDA"}:
            return self.estado
        if self.fecha_fin and self.fecha_fin < date.today():
            return "VENCIDA"
        return "VIGENTE"

    @property
    def referencia_tecnica(self):
        if self.equipo:
            return f"{self.equipo.codigo} - {self.equipo.nombre}"
        if self.metodo_referencia:
            return self.metodo_referencia
        return "-"


class PersonalAutorizacionTecnicaEvidencia(TenantMixin, BaseModel):
    __tablename__ = "personal_autorizacion_tecnica_evidencias"
    __table_args__ = (
        db.CheckConstraint(
            "tipo_evidencia IN ('ACTA_AUTORIZACION', 'MATRIZ_FIRMADA', 'FORMATO_AUTORIZACION', 'CERTIFICADO', 'RESOLUCION_INTERNA', 'OTRO')",
            name="ck_personal_aut_tec_evidencias_tipo_valido",
        ),
        db.Index("ix_personal_aut_tec_evid_empresa_aut", "empresa_id", "autorizacion_id"),
        db.Index("ix_personal_aut_tec_evid_empresa_activo", "empresa_id", "activo"),
    )

    autorizacion_id = db.Column(db.BigInteger, db.ForeignKey("personal_autorizaciones_tecnicas.id"), nullable=False)
    tipo_evidencia = db.Column(db.String(40), nullable=False)
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
    autorizacion = db.relationship("PersonalAutorizacionTecnica", back_populates="evidencias")
    cargado_por = db.relationship("Usuario", foreign_keys=[cargado_por_id])
