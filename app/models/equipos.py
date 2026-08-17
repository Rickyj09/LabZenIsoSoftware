from app.extensions import db
from app.models.base import BaseModel, TenantMixin


ESTADOS_OPERATIVOS_EQUIPO = (
    "OPERATIVO",
    "FUERA_DE_SERVICIO",
    "EN_MANTENIMIENTO",
    "EN_CALIBRACION",
    "RETIRADO",
)

CRITICIDADES_EQUIPO = ("BAJA", "MEDIA", "ALTA")

ESTADOS_PLAN_MANTENIMIENTO = ("ACTIVO", "INACTIVO")

TIPOS_MANTENIMIENTO_EQUIPO = ("PREVENTIVO", "CORRECTIVO")

ESTADOS_MANTENIMIENTO_EQUIPO = ("PROGRAMADO", "EN_PROCESO", "COMPLETADO", "CANCELADO")

TIPOS_CONTROL_METROLOGICO = ("CALIBRACION", "VERIFICACION")

ESTADOS_CALIBRACION_EQUIPO = ("PROGRAMADO", "EN_PROCESO", "COMPLETADO", "CANCELADO")

ESTADOS_MEDICION_AMBIENTAL = ("CONFORME", "FUERA_DE_LIMITE")

TIPOS_MATERIAL_REFERENCIA = ("MATERIAL_REFERENCIA", "PATRON_REFERENCIA")

ESTADOS_MATERIAL_REFERENCIA = ("DISPONIBLE", "EN_USO", "AGOTADO", "VENCIDO", "RETIRADO")

TIPOS_EVIDENCIA_MATERIAL_REFERENCIA = ("CERTIFICADO", "FICHA_TECNICA", "HOJA_SEGURIDAD", "OTRO")

TIPOS_EVENTO_MATERIAL_REFERENCIA = (
    "MATERIAL_REFERENCIA_CREADO",
    "MATERIAL_REFERENCIA_PUESTO_EN_USO",
    "MATERIAL_REFERENCIA_AGOTADO",
    "MATERIAL_REFERENCIA_VENCIDO",
    "MATERIAL_REFERENCIA_RETIRADO",
    "EVIDENCIA_MATERIAL_REFERENCIA_VINCULADA",
    "EVIDENCIA_MATERIAL_REFERENCIA_DESVINCULADA",
)

TIPOS_EVENTO_AREA_AMBIENTAL = (
    "CONDICION_AMBIENTAL_CREADA",
    "CONDICION_AMBIENTAL_ACTUALIZADA",
    "CONDICION_AMBIENTAL_INACTIVADA",
    "MEDICION_AMBIENTAL_REGISTRADA",
    "MEDICION_AMBIENTAL_FUERA_DE_LIMITE",
)

TIPOS_EVENTO_EQUIPO = (
    "CREACION",
    "ACTUALIZACION",
    "CAMBIO_UBICACION",
    "CAMBIO_RESPONSABLE",
    "CAMBIO_ESTADO_OPERATIVO",
    "RETIRO",
    "REACTIVACION",
    "VINCULO_DOCUMENTO",
    "PLAN_MANTENIMIENTO_CREADO",
    "PLAN_MANTENIMIENTO_ACTUALIZADO",
    "PLAN_MANTENIMIENTO_INACTIVADO",
    "MANTENIMIENTO_PROGRAMADO",
    "MANTENIMIENTO_CORRECTIVO_CREADO",
    "MANTENIMIENTO_INICIADO",
    "MANTENIMIENTO_COMPLETADO",
    "MANTENIMIENTO_CANCELADO",
    "EVIDENCIA_MANTENIMIENTO_VINCULADA",
    "EVIDENCIA_MANTENIMIENTO_DESVINCULADA",
    "CALIBRACION_PROGRAMADA",
    "VERIFICACION_PROGRAMADA",
    "CALIBRACION_INICIADA",
    "VERIFICACION_INICIADA",
    "CALIBRACION_COMPLETADA",
    "VERIFICACION_COMPLETADA",
    "CALIBRACION_CANCELADA",
    "VERIFICACION_CANCELADA",
    "EVIDENCIA_CALIBRACION_VINCULADA",
    "EVIDENCIA_CALIBRACION_DESVINCULADA",
)


class Instalacion(TenantMixin, BaseModel):
    __tablename__ = "instalaciones"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_instalaciones_empresa_codigo"),
        db.Index("ix_instalaciones_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_instalaciones_estado", "estado"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    direccion = db.Column(db.Text)
    responsable = db.Column(db.String(150))
    estado = db.Column(db.String(20), nullable=False, default="activo")

    empresa = db.relationship("Empresa", back_populates="instalaciones")
    areas = db.relationship("AreaAmbiente", back_populates="instalacion", lazy=True)
    equipos = db.relationship("Equipo", back_populates="instalacion", lazy=True)


class AreaAmbiente(TenantMixin, BaseModel):
    __tablename__ = "areas_ambientes"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_areas_ambientes_empresa_codigo"),
        db.Index("ix_areas_ambientes_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_areas_ambientes_instalacion_id", "instalacion_id"),
        db.Index("ix_areas_ambientes_estado", "estado"),
    )

    instalacion_id = db.Column(db.BigInteger, db.ForeignKey("instalaciones.id"), nullable=False)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    tipo = db.Column(db.String(80))
    ubicacion_interna = db.Column(db.String(150))
    responsable = db.Column(db.String(150))
    requiere_control_ambiental = db.Column(db.Boolean, nullable=False, default=False)
    estado = db.Column(db.String(20), nullable=False, default="activo")

    empresa = db.relationship("Empresa", back_populates="areas_ambientes")
    instalacion = db.relationship("Instalacion", back_populates="areas")
    equipos = db.relationship("Equipo", back_populates="area_ambiente", lazy=True)
    condiciones_ambientales = db.relationship(
        "AreaCondicionAmbiental",
        back_populates="area_ambiente",
        lazy=True,
        cascade="all, delete-orphan",
    )
    mediciones_ambientales = db.relationship(
        "AreaMedicionAmbiental",
        back_populates="area_ambiente",
        lazy=True,
        cascade="all, delete-orphan",
    )
    historial_ambiental = db.relationship(
        "AreaHistorialAmbiental",
        back_populates="area_ambiente",
        lazy=True,
        order_by="AreaHistorialAmbiental.created_at.desc(), AreaHistorialAmbiental.id.desc()",
        cascade="all, delete-orphan",
    )


class AreaCondicionAmbiental(TenantMixin, BaseModel):
    __tablename__ = "area_condiciones_ambientales"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "area_ambiente_id", "codigo", name="uq_area_condicion_ambiental_codigo"),
        db.CheckConstraint(
            "limite_minimo IS NOT NULL OR limite_maximo IS NOT NULL",
            name="ck_area_condicion_ambiental_limite_requerido",
        ),
        db.CheckConstraint(
            "limite_minimo IS NULL OR limite_maximo IS NULL OR limite_minimo <= limite_maximo",
            name="ck_area_condicion_ambiental_limites_ordenados",
        ),
        db.Index("ix_area_condiciones_ambientales_empresa_area", "empresa_id", "area_ambiente_id"),
        db.Index("ix_area_condiciones_ambientales_empresa_activa", "empresa_id", "activa"),
    )

    area_ambiente_id = db.Column(db.BigInteger, db.ForeignKey("areas_ambientes.id"), nullable=False)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    unidad = db.Column(db.String(30), nullable=False)
    limite_minimo = db.Column(db.Numeric(14, 4))
    limite_maximo = db.Column(db.Numeric(14, 4))
    valor_referencia = db.Column(db.Numeric(14, 4))
    activa = db.Column(db.Boolean, nullable=False, default=True)
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    area_ambiente = db.relationship("AreaAmbiente", back_populates="condiciones_ambientales")
    mediciones = db.relationship(
        "AreaMedicionAmbiental",
        back_populates="condicion_ambiental",
        lazy=True,
        cascade="all, delete-orphan",
    )


class AreaMedicionAmbiental(TenantMixin, BaseModel):
    __tablename__ = "area_mediciones_ambientales"
    __table_args__ = (
        db.CheckConstraint("estado IN ('CONFORME', 'FUERA_DE_LIMITE')", name="ck_area_medicion_ambiental_estado_valido"),
        db.Index("ix_area_mediciones_ambientales_empresa_area", "empresa_id", "area_ambiente_id"),
        db.Index("ix_area_mediciones_ambientales_condicion", "condicion_ambiental_id"),
        db.Index("ix_area_mediciones_ambientales_fecha", "fecha_hora_medicion"),
        db.Index("ix_area_mediciones_ambientales_empresa_estado", "empresa_id", "estado"),
    )

    area_ambiente_id = db.Column(db.BigInteger, db.ForeignKey("areas_ambientes.id"), nullable=False)
    condicion_ambiental_id = db.Column(db.BigInteger, db.ForeignKey("area_condiciones_ambientales.id"), nullable=False)
    fecha_hora_medicion = db.Column(db.DateTime(timezone=True), nullable=False)
    valor = db.Column(db.Numeric(14, 4), nullable=False)
    estado = db.Column(db.String(30), nullable=False)
    limite_minimo_aplicado = db.Column(db.Numeric(14, 4))
    limite_maximo_aplicado = db.Column(db.Numeric(14, 4))
    unidad_aplicada = db.Column(db.String(30), nullable=False)
    observaciones = db.Column(db.Text)
    registrado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)

    empresa = db.relationship("Empresa")
    area_ambiente = db.relationship("AreaAmbiente", back_populates="mediciones_ambientales")
    condicion_ambiental = db.relationship("AreaCondicionAmbiental", back_populates="mediciones")
    registrado_por = db.relationship("Usuario", foreign_keys=[registrado_por_id])


class AreaHistorialAmbiental(TenantMixin, BaseModel):
    __tablename__ = "area_historial_ambiental"
    __table_args__ = (
        db.CheckConstraint(
            "tipo_evento IN ('CONDICION_AMBIENTAL_CREADA', 'CONDICION_AMBIENTAL_ACTUALIZADA', 'CONDICION_AMBIENTAL_INACTIVADA', 'MEDICION_AMBIENTAL_REGISTRADA', 'MEDICION_AMBIENTAL_FUERA_DE_LIMITE')",
            name="ck_area_historial_ambiental_tipo_evento_valido",
        ),
        db.Index("ix_area_historial_ambiental_empresa_area", "empresa_id", "area_ambiente_id"),
        db.Index("ix_area_historial_ambiental_tipo_evento", "tipo_evento"),
    )

    area_ambiente_id = db.Column(db.BigInteger, db.ForeignKey("areas_ambientes.id"), nullable=False)
    condicion_ambiental_id = db.Column(db.BigInteger, db.ForeignKey("area_condiciones_ambientales.id"))
    medicion_ambiental_id = db.Column(db.BigInteger, db.ForeignKey("area_mediciones_ambientales.id"))
    tipo_evento = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text)
    datos_antes = db.Column(db.JSON)
    datos_despues = db.Column(db.JSON)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa")
    area_ambiente = db.relationship("AreaAmbiente", back_populates="historial_ambiental")
    condicion_ambiental = db.relationship("AreaCondicionAmbiental", foreign_keys=[condicion_ambiental_id])
    medicion_ambiental = db.relationship("AreaMedicionAmbiental", foreign_keys=[medicion_ambiental_id])
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])


class MaterialReferencia(TenantMixin, BaseModel):
    __tablename__ = "materiales_referencia"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_materiales_referencia_empresa_codigo"),
        db.CheckConstraint(
            "tipo IN ('MATERIAL_REFERENCIA', 'PATRON_REFERENCIA')",
            name="ck_materiales_referencia_tipo_valido",
        ),
        db.CheckConstraint(
            "estado IN ('DISPONIBLE', 'EN_USO', 'AGOTADO', 'VENCIDO', 'RETIRADO')",
            name="ck_materiales_referencia_estado_valido",
        ),
        db.CheckConstraint(
            "fecha_caducidad IS NULL OR fecha_caducidad >= fecha_recepcion",
            name="ck_materiales_referencia_caducidad_recepcion",
        ),
        db.CheckConstraint(
            "cantidad_inicial IS NULL OR cantidad_inicial >= 0",
            name="ck_materiales_referencia_cantidad_inicial_no_negativa",
        ),
        db.CheckConstraint(
            "cantidad_disponible IS NULL OR cantidad_disponible >= 0",
            name="ck_materiales_referencia_cantidad_disponible_no_negativa",
        ),
        db.CheckConstraint(
            "cantidad_inicial IS NULL OR cantidad_disponible IS NULL OR cantidad_disponible <= cantidad_inicial",
            name="ck_materiales_referencia_cantidad_disponible_maxima",
        ),
        db.Index("ix_materiales_referencia_empresa_tipo", "empresa_id", "tipo"),
        db.Index("ix_materiales_referencia_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_materiales_referencia_empresa_caducidad", "empresa_id", "fecha_caducidad"),
        db.Index("ix_materiales_referencia_responsable_id", "responsable_id"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    tipo = db.Column(db.String(30), nullable=False)
    fabricante = db.Column(db.String(150))
    proveedor = db.Column(db.String(150))
    lote = db.Column(db.String(100))
    certificado_numero = db.Column(db.String(100))
    referencia_fabricante = db.Column(db.String(100))
    fecha_recepcion = db.Column(db.Date, nullable=False)
    fecha_apertura = db.Column(db.Date)
    fecha_puesta_en_uso = db.Column(db.Date)
    fecha_caducidad = db.Column(db.Date)
    estado = db.Column(db.String(30), nullable=False, default="DISPONIBLE")
    ubicacion = db.Column(db.String(150))
    condiciones_almacenamiento = db.Column(db.Text)
    observaciones = db.Column(db.Text)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    cantidad_inicial = db.Column(db.Numeric(14, 4))
    cantidad_disponible = db.Column(db.Numeric(14, 4))
    unidad = db.Column(db.String(30))
    activo = db.Column(db.Boolean, nullable=False, default=True)

    empresa = db.relationship("Empresa")
    responsable = db.relationship("Usuario", foreign_keys=[responsable_id])
    evidencias = db.relationship(
        "MaterialReferenciaDocumento",
        back_populates="material_referencia",
        lazy=True,
        cascade="all, delete-orphan",
    )
    historial = db.relationship(
        "MaterialReferenciaHistorial",
        back_populates="material_referencia",
        lazy=True,
        order_by="MaterialReferenciaHistorial.created_at.desc(), MaterialReferenciaHistorial.id.desc()",
        cascade="all, delete-orphan",
    )


class MaterialReferenciaDocumento(TenantMixin, BaseModel):
    __tablename__ = "material_referencia_documentos"
    __table_args__ = (
        db.UniqueConstraint("material_referencia_id", "documento_version_id", name="uq_material_referencia_documento_version"),
        db.CheckConstraint(
            "tipo_evidencia IN ('CERTIFICADO', 'FICHA_TECNICA', 'HOJA_SEGURIDAD', 'OTRO')",
            name="ck_material_referencia_documentos_tipo_valido",
        ),
        db.Index("ix_material_referencia_documentos_empresa_material", "empresa_id", "material_referencia_id"),
        db.Index("ix_material_referencia_documentos_documento_version_id", "documento_version_id"),
    )

    material_referencia_id = db.Column(db.BigInteger, db.ForeignKey("materiales_referencia.id"), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    tipo_evidencia = db.Column(db.String(50), nullable=False)
    observaciones = db.Column(db.Text)
    vinculado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa")
    material_referencia = db.relationship("MaterialReferencia", back_populates="evidencias")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    vinculado_por = db.relationship("Usuario", foreign_keys=[vinculado_por_id])


class MaterialReferenciaHistorial(TenantMixin, BaseModel):
    __tablename__ = "material_referencia_historial"
    __table_args__ = (
        db.CheckConstraint(
            "tipo_evento IN ('MATERIAL_REFERENCIA_CREADO', 'MATERIAL_REFERENCIA_PUESTO_EN_USO', 'MATERIAL_REFERENCIA_AGOTADO', 'MATERIAL_REFERENCIA_VENCIDO', 'MATERIAL_REFERENCIA_RETIRADO', 'EVIDENCIA_MATERIAL_REFERENCIA_VINCULADA', 'EVIDENCIA_MATERIAL_REFERENCIA_DESVINCULADA')",
            name="ck_material_referencia_historial_tipo_evento_valido",
        ),
        db.Index("ix_material_referencia_historial_empresa_material", "empresa_id", "material_referencia_id"),
        db.Index("ix_material_referencia_historial_tipo_evento", "tipo_evento"),
    )

    material_referencia_id = db.Column(db.BigInteger, db.ForeignKey("materiales_referencia.id"), nullable=False)
    tipo_evento = db.Column(db.String(60), nullable=False)
    estado_anterior = db.Column(db.String(30))
    estado_nuevo = db.Column(db.String(30))
    descripcion = db.Column(db.Text)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    datos_antes = db.Column(db.JSON)
    datos_despues = db.Column(db.JSON)

    empresa = db.relationship("Empresa")
    material_referencia = db.relationship("MaterialReferencia", back_populates="historial")
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])


class Equipo(TenantMixin, BaseModel):
    __tablename__ = "equipos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_equipos_empresa_codigo"),
        db.CheckConstraint(
            "estado_operativo IN ('OPERATIVO', 'FUERA_DE_SERVICIO', 'EN_MANTENIMIENTO', 'EN_CALIBRACION', 'RETIRADO')",
            name="ck_equipos_estado_operativo_valido",
        ),
        db.CheckConstraint("criticidad IS NULL OR criticidad IN ('BAJA', 'MEDIA', 'ALTA')", name="ck_equipos_criticidad_valida"),
        db.Index("ix_equipos_estado", "estado"),
        db.Index("ix_equipos_estado_operativo", "estado_operativo"),
        db.Index("ix_equipos_instalacion_id", "instalacion_id"),
        db.Index("ix_equipos_area_ambiente_id", "area_ambiente_id"),
    )

    sede_id = db.Column(db.BigInteger, db.ForeignKey("sedes.id"))
    instalacion_id = db.Column(db.BigInteger, db.ForeignKey("instalaciones.id"))
    area_ambiente_id = db.Column(db.BigInteger, db.ForeignKey("areas_ambientes.id"))
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    tipo = db.Column(db.String(100))
    marca = db.Column(db.String(100))
    modelo = db.Column(db.String(100))
    serie = db.Column(db.String(100))
    fabricante = db.Column(db.String(150))
    ubicacion = db.Column(db.String(150))
    ubicacion_especifica = db.Column(db.String(150))
    fecha_adquisicion = db.Column(db.Date)
    fecha_puesta_servicio = db.Column(db.Date)
    estado = db.Column(db.String(30), default="activo")
    estado_operativo = db.Column(db.String(30), nullable=False, default="OPERATIVO")
    criticidad = db.Column(db.String(30))
    requiere_calibracion = db.Column(db.Boolean, default=False, nullable=False)
    requiere_mantenimiento = db.Column(db.Boolean, default=False, nullable=False)
    frecuencia_calibracion_meses = db.Column(db.Integer)
    frecuencia_mantenimiento_meses = db.Column(db.Integer)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    responsable = db.Column(db.String(150))
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa", back_populates="equipos")
    sede = db.relationship("Sede", back_populates="equipos")
    instalacion = db.relationship("Instalacion", back_populates="equipos")
    area_ambiente = db.relationship("AreaAmbiente", back_populates="equipos")
    responsable_usuario = db.relationship("Usuario", foreign_keys=[responsable_id])
    calibraciones = db.relationship(
        "EquipoCalibracion",
        back_populates="equipo",
        lazy=True,
        cascade="all, delete-orphan"
    )
    mantenimientos = db.relationship(
        "EquipoMantenimiento",
        back_populates="equipo",
        lazy=True,
        cascade="all, delete-orphan"
    )
    planes_mantenimiento = db.relationship(
        "EquipoPlanMantenimiento",
        back_populates="equipo",
        lazy=True,
        cascade="all, delete-orphan"
    )
    documentos = db.relationship(
        "EquipoDocumento",
        back_populates="equipo",
        lazy=True,
        cascade="all, delete-orphan"
    )
    historial = db.relationship(
        "EquipoHistorial",
        back_populates="equipo",
        lazy=True,
        order_by="EquipoHistorial.created_at.desc(), EquipoHistorial.id.desc()",
        cascade="all, delete-orphan",
    )


class EquipoCalibracion(TenantMixin, BaseModel):
    __tablename__ = "equipo_calibraciones"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_equipo_calibracion_empresa_codigo"),
        db.CheckConstraint("tipo_control IN ('CALIBRACION', 'VERIFICACION')", name="ck_equipo_calibracion_tipo_valido"),
        db.CheckConstraint("estado IN ('PROGRAMADO', 'EN_PROCESO', 'COMPLETADO', 'CANCELADO')", name="ck_equipo_calibracion_estado_valido"),
        db.CheckConstraint("costo IS NULL OR costo >= 0", name="ck_equipo_calibracion_costo_no_negativo"),
        db.Index("ix_equipo_calibracion_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_equipo_calibracion_empresa_fecha_planificada", "empresa_id", "fecha_planificada"),
        db.Index("ix_equipo_calibracion_empresa_equipo_estado", "empresa_id", "equipo_id", "estado"),
    )

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    codigo = db.Column(db.String(50), nullable=False)
    tipo_control = db.Column(db.String(30), nullable=False)
    estado = db.Column(db.String(30), nullable=False, default="PROGRAMADO")
    fecha_planificada = db.Column(db.Date, nullable=False)
    fecha_calibracion = db.Column(db.Date)
    fecha_inicio = db.Column(db.Date)
    fecha_finalizacion = db.Column(db.Date)
    fecha_proxima = db.Column(db.Date)
    periodicidad_meses = db.Column(db.Integer)
    proveedor = db.Column(db.String(150))
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    resultado = db.Column(db.String(50))
    certificado_numero = db.Column(db.String(100))
    archivo_url = db.Column(db.String(255))
    costo = db.Column(db.Numeric(12, 2))
    moneda = db.Column(db.String(3))
    cancelado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    motivo_cancelacion = db.Column(db.Text)
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="calibraciones")
    responsable = db.relationship("Usuario", foreign_keys=[responsable_id])
    cancelado_por = db.relationship("Usuario", foreign_keys=[cancelado_por_id])
    evidencias = db.relationship(
        "EquipoCalibracionDocumento",
        back_populates="calibracion",
        lazy=True,
        cascade="all, delete-orphan",
    )


class EquipoCalibracionDocumento(TenantMixin, BaseModel):
    __tablename__ = "equipo_calibracion_documentos"
    __table_args__ = (
        db.UniqueConstraint("calibracion_id", "documento_version_id", name="uq_equipo_calibracion_documento_version"),
        db.Index("ix_equipo_calibracion_documentos_empresa_calibracion", "empresa_id", "calibracion_id"),
        db.Index("ix_equipo_calibracion_documentos_documento_version_id", "documento_version_id"),
    )

    calibracion_id = db.Column(db.BigInteger, db.ForeignKey("equipo_calibraciones.id"), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    tipo_evidencia = db.Column(db.String(50), nullable=False)
    observaciones = db.Column(db.Text)
    vinculado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa")
    calibracion = db.relationship("EquipoCalibracion", back_populates="evidencias")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    vinculado_por = db.relationship("Usuario", foreign_keys=[vinculado_por_id])


class EquipoPlanMantenimiento(TenantMixin, BaseModel):
    __tablename__ = "equipo_planes_mantenimiento"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_equipo_plan_mantenimiento_empresa_codigo"),
        db.CheckConstraint("periodicidad_meses > 0", name="ck_equipo_plan_mantenimiento_periodicidad_positiva"),
        db.CheckConstraint("estado IN ('ACTIVO', 'INACTIVO')", name="ck_equipo_plan_mantenimiento_estado_valido"),
        db.Index("ix_equipo_plan_mantenimiento_empresa_equipo", "empresa_id", "equipo_id"),
        db.Index("ix_equipo_plan_mantenimiento_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_equipo_plan_mantenimiento_empresa_proxima", "empresa_id", "proxima_fecha"),
    )

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    periodicidad_meses = db.Column(db.Integer, nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    proxima_fecha = db.Column(db.Date)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    proveedor = db.Column(db.String(150))
    estado = db.Column(db.String(20), nullable=False, default="ACTIVO")

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="planes_mantenimiento")
    responsable = db.relationship("Usuario", foreign_keys=[responsable_id])
    mantenimientos = db.relationship("EquipoMantenimiento", back_populates="plan", lazy=True)


class EquipoMantenimiento(TenantMixin, BaseModel):
    __tablename__ = "equipo_mantenimientos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_equipo_mantenimiento_empresa_codigo"),
        db.CheckConstraint("tipo_mantenimiento IN ('PREVENTIVO', 'CORRECTIVO')", name="ck_equipo_mantenimiento_tipo_valido"),
        db.CheckConstraint("estado IN ('PROGRAMADO', 'EN_PROCESO', 'COMPLETADO', 'CANCELADO')", name="ck_equipo_mantenimiento_estado_valido"),
        db.CheckConstraint("costo IS NULL OR costo >= 0", name="ck_equipo_mantenimiento_costo_no_negativo"),
        db.Index("ix_equipo_mantenimiento_empresa_estado", "empresa_id", "estado"),
        db.Index("ix_equipo_mantenimiento_empresa_fecha_planificada", "empresa_id", "fecha_planificada"),
        db.Index("ix_equipo_mantenimiento_empresa_equipo_estado", "empresa_id", "equipo_id", "estado"),
        db.Index("ix_equipo_mantenimiento_plan_id", "plan_id"),
    )

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    plan_id = db.Column(db.BigInteger, db.ForeignKey("equipo_planes_mantenimiento.id"))
    codigo = db.Column(db.String(50), nullable=False)
    tipo_mantenimiento = db.Column(db.String(50), nullable=False)
    estado = db.Column(db.String(30), nullable=False, default="PROGRAMADO")
    fecha_planificada = db.Column(db.Date, nullable=False)
    fecha_mantenimiento = db.Column(db.Date)
    fecha_inicio = db.Column(db.Date)
    fecha_finalizacion = db.Column(db.Date)
    fecha_proxima = db.Column(db.Date)
    descripcion_trabajo = db.Column(db.Text)
    responsable_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    proveedor = db.Column(db.String(150))
    resultado = db.Column(db.String(50))
    costo = db.Column(db.Numeric(12, 2))
    moneda = db.Column(db.String(3))
    cancelado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    motivo_cancelacion = db.Column(db.Text)
    observaciones = db.Column(db.Text)
    archivo_url = db.Column(db.String(255))

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="mantenimientos")
    plan = db.relationship("EquipoPlanMantenimiento", back_populates="mantenimientos")
    responsable = db.relationship("Usuario", foreign_keys=[responsable_id])
    cancelado_por = db.relationship("Usuario", foreign_keys=[cancelado_por_id])
    evidencias = db.relationship(
        "EquipoMantenimientoDocumento",
        back_populates="mantenimiento",
        lazy=True,
        cascade="all, delete-orphan"
    )


class EquipoMantenimientoDocumento(TenantMixin, BaseModel):
    __tablename__ = "equipo_mantenimiento_documentos"
    __table_args__ = (
        db.UniqueConstraint("mantenimiento_id", "documento_version_id", name="uq_equipo_mantenimiento_documento_version"),
        db.Index("ix_equipo_mantenimiento_documentos_empresa_mantenimiento", "empresa_id", "mantenimiento_id"),
        db.Index("ix_equipo_mantenimiento_documentos_documento_version_id", "documento_version_id"),
    )

    mantenimiento_id = db.Column(db.BigInteger, db.ForeignKey("equipo_mantenimientos.id"), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"), nullable=False)
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"), nullable=False)
    tipo_evidencia = db.Column(db.String(50), nullable=False)
    observaciones = db.Column(db.Text)
    vinculado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa")
    mantenimiento = db.relationship("EquipoMantenimiento", back_populates="evidencias")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    vinculado_por = db.relationship("Usuario", foreign_keys=[vinculado_por_id])


class EquipoDocumento(TenantMixin, BaseModel):
    __tablename__ = "equipo_documentos"
    __table_args__ = (
        db.UniqueConstraint("equipo_id", "documento_version_id", name="uq_equipo_documento_version"),
        db.Index("ix_equipo_documentos_equipo_id", "equipo_id"),
        db.Index("ix_equipo_documentos_documento_id", "documento_id"),
        db.Index("ix_equipo_documentos_documento_version_id", "documento_version_id"),
    )

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    documento_id = db.Column(db.BigInteger, db.ForeignKey("documentos.id"))
    documento_version_id = db.Column(db.BigInteger, db.ForeignKey("documento_versiones.id"))
    tipo_documento = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    archivo_url = db.Column(db.String(255))
    version = db.Column(db.String(20))
    fecha_documento = db.Column(db.Date)
    vinculado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="documentos")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    documento_version = db.relationship("DocumentoVersion", foreign_keys=[documento_version_id])
    vinculado_por = db.relationship("Usuario", foreign_keys=[vinculado_por_id])


class EquipoHistorial(TenantMixin, BaseModel):
    __tablename__ = "equipo_historial"
    __table_args__ = (
        db.CheckConstraint(
            "tipo_evento IN ('CREACION', 'ACTUALIZACION', 'CAMBIO_UBICACION', 'CAMBIO_RESPONSABLE', 'CAMBIO_ESTADO_OPERATIVO', 'RETIRO', 'REACTIVACION', 'VINCULO_DOCUMENTO', 'PLAN_MANTENIMIENTO_CREADO', 'PLAN_MANTENIMIENTO_ACTUALIZADO', 'PLAN_MANTENIMIENTO_INACTIVADO', 'MANTENIMIENTO_PROGRAMADO', 'MANTENIMIENTO_CORRECTIVO_CREADO', 'MANTENIMIENTO_INICIADO', 'MANTENIMIENTO_COMPLETADO', 'MANTENIMIENTO_CANCELADO', 'EVIDENCIA_MANTENIMIENTO_VINCULADA', 'EVIDENCIA_MANTENIMIENTO_DESVINCULADA', 'CALIBRACION_PROGRAMADA', 'VERIFICACION_PROGRAMADA', 'CALIBRACION_INICIADA', 'VERIFICACION_INICIADA', 'CALIBRACION_COMPLETADA', 'VERIFICACION_COMPLETADA', 'CALIBRACION_CANCELADA', 'VERIFICACION_CANCELADA', 'EVIDENCIA_CALIBRACION_VINCULADA', 'EVIDENCIA_CALIBRACION_DESVINCULADA')",
            name="ck_equipo_historial_tipo_evento_valido",
        ),
        db.Index("ix_equipo_historial_equipo_id", "equipo_id"),
        db.Index("ix_equipo_historial_tipo_evento", "tipo_evento"),
    )

    equipo_id = db.Column(db.BigInteger, db.ForeignKey("equipos.id"), nullable=False)
    tipo_evento = db.Column(db.String(40), nullable=False)
    estado_anterior = db.Column(db.String(100))
    estado_nuevo = db.Column(db.String(100))
    descripcion = db.Column(db.Text)
    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))

    empresa = db.relationship("Empresa")
    equipo = db.relationship("Equipo", back_populates="historial")
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
