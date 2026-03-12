from app.extensions import db
from app.models.base import BaseModel, TenantMixin


class Muestra(TenantMixin, BaseModel):
    __tablename__ = "muestras"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo_interno", name="uq_muestras_empresa_codigo_interno"),
    )

    solicitud_id = db.Column(db.BigInteger, db.ForeignKey("solicitudes.id"), nullable=False)
    codigo_interno = db.Column(db.String(50), nullable=False)
    codigo_cliente = db.Column(db.String(50))
    tipo_muestra = db.Column(db.String(100))
    descripcion = db.Column(db.Text)
    fecha_recepcion = db.Column(db.Date)
    fecha_muestreo = db.Column(db.Date)
    recibido_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    condicion_recepcion = db.Column(db.Text)
    ubicacion_almacenamiento = db.Column(db.String(150))
    estado = db.Column(db.String(30), default="recibida")
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa", back_populates="muestras")
    solicitud = db.relationship("Solicitud", back_populates="muestras")
    recibido_por = db.relationship(
        "Usuario",
        foreign_keys=[recibido_por_id],
        back_populates="muestras_recibidas"
    )
    ensayos = db.relationship(
        "MuestraEnsayo",
        back_populates="muestra",
        lazy=True,
        cascade="all, delete-orphan"
    )
    custodias = db.relationship(
        "CadenaCustodia",
        back_populates="muestra",
        lazy=True,
        cascade="all, delete-orphan"
    )


class EnsayoCatalogo(TenantMixin, BaseModel):
    __tablename__ = "ensayos_catalogo"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_ensayo_catalogo_empresa_codigo"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    area = db.Column(db.String(100))
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa", back_populates="ensayos_catalogo")
    muestra_ensayos = db.relationship("MuestraEnsayo", back_populates="ensayo", lazy=True)
    metodos = db.relationship(
        "EnsayoMetodo",
        back_populates="ensayo",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Metodo(TenantMixin, BaseModel):
    __tablename__ = "metodos"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_metodos_empresa_codigo"),
    )

    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    version = db.Column(db.String(20))
    tipo = db.Column(db.String(50))
    norma_referencia = db.Column(db.String(150))
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    fecha_vigencia = db.Column(db.Date)

    empresa = db.relationship("Empresa", back_populates="metodos")
    parametros = db.relationship(
        "MetodoParametro",
        back_populates="metodo",
        lazy=True,
        cascade="all, delete-orphan"
    )
    muestra_ensayos = db.relationship("MuestraEnsayo", back_populates="metodo", lazy=True)
    ensayos = db.relationship(
        "EnsayoMetodo",
        back_populates="metodo",
        lazy=True,
        cascade="all, delete-orphan"
    )


class MetodoParametro(TenantMixin, BaseModel):
    __tablename__ = "metodo_parametros"

    metodo_id = db.Column(db.BigInteger, db.ForeignKey("metodos.id"), nullable=False)
    codigo = db.Column(db.String(50))
    nombre = db.Column(db.String(150), nullable=False)
    unidad = db.Column(db.String(50))
    tipo_dato = db.Column(db.String(30))
    limite_min = db.Column(db.Numeric(18, 6))
    limite_max = db.Column(db.Numeric(18, 6))
    orden = db.Column(db.Integer, default=1)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa")
    metodo = db.relationship("Metodo", back_populates="parametros")
    resultados = db.relationship("Resultado", back_populates="parametro", lazy=True)


class EnsayoMetodo(TenantMixin, BaseModel):
    __tablename__ = "ensayo_metodos"
    __table_args__ = (
        db.UniqueConstraint("ensayo_id", "metodo_id", name="uq_ensayo_metodo"),
    )

    ensayo_id = db.Column(db.BigInteger, db.ForeignKey("ensayos_catalogo.id"), nullable=False)
    metodo_id = db.Column(db.BigInteger, db.ForeignKey("metodos.id"), nullable=False)
    predeterminado = db.Column(db.Boolean, default=False, nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    empresa = db.relationship("Empresa")
    ensayo = db.relationship("EnsayoCatalogo", back_populates="metodos")
    metodo = db.relationship("Metodo", back_populates="ensayos")


class MuestraEnsayo(TenantMixin, BaseModel):
    __tablename__ = "muestra_ensayos"

    muestra_id = db.Column(db.BigInteger, db.ForeignKey("muestras.id"), nullable=False)
    ensayo_id = db.Column(db.BigInteger, db.ForeignKey("ensayos_catalogo.id"), nullable=False)
    metodo_id = db.Column(db.BigInteger, db.ForeignKey("metodos.id"), nullable=False)
    analista_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_programada = db.Column(db.Date)
    fecha_inicio = db.Column(db.Date)
    fecha_fin = db.Column(db.Date)
    estado = db.Column(db.String(30), default="pendiente")
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    muestra = db.relationship("Muestra", back_populates="ensayos")
    ensayo = db.relationship("EnsayoCatalogo", back_populates="muestra_ensayos")
    metodo = db.relationship("Metodo", back_populates="muestra_ensayos")
    analista = db.relationship(
        "Usuario",
        foreign_keys=[analista_id],
        back_populates="muestra_ensayos_asignados"
    )
    resultados = db.relationship(
        "Resultado",
        back_populates="muestra_ensayo",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Resultado(TenantMixin, BaseModel):
    __tablename__ = "resultados"

    muestra_ensayo_id = db.Column(db.BigInteger, db.ForeignKey("muestra_ensayos.id"), nullable=False)
    parametro_id = db.Column(db.BigInteger, db.ForeignKey("metodo_parametros.id"), nullable=False)

    valor_texto = db.Column(db.Text)
    valor_numero = db.Column(db.Numeric(18, 6))
    unidad = db.Column(db.String(50))
    cumple = db.Column(db.Boolean)
    incertidumbre = db.Column(db.Numeric(18, 6))
    limite_deteccion = db.Column(db.Numeric(18, 6))
    observaciones = db.Column(db.Text)

    registrado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_registro = db.Column(db.DateTime(timezone=True))
    revisado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_revision = db.Column(db.DateTime(timezone=True))
    aprobado_por_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"))
    fecha_aprobacion = db.Column(db.DateTime(timezone=True))

    empresa = db.relationship("Empresa")
    muestra_ensayo = db.relationship("MuestraEnsayo", back_populates="resultados")
    parametro = db.relationship("MetodoParametro", back_populates="resultados")

    registrado_por = db.relationship(
        "Usuario",
        foreign_keys=[registrado_por_id],
        back_populates="resultados_registrados"
    )
    revisado_por = db.relationship(
        "Usuario",
        foreign_keys=[revisado_por_id],
        back_populates="resultados_revisados"
    )
    aprobado_por = db.relationship(
        "Usuario",
        foreign_keys=[aprobado_por_id],
        back_populates="resultados_aprobados"
    )


class CadenaCustodia(TenantMixin, BaseModel):
    __tablename__ = "cadena_custodia"

    muestra_id = db.Column(db.BigInteger, db.ForeignKey("muestras.id"), nullable=False)
    fecha_hora = db.Column(db.DateTime(timezone=True), nullable=False)
    ubicacion = db.Column(db.String(150))
    responsable_entrega = db.Column(db.String(150))
    responsable_recibe = db.Column(db.String(150))
    evento = db.Column(db.String(100), nullable=False)
    observaciones = db.Column(db.Text)

    empresa = db.relationship("Empresa")
    muestra = db.relationship("Muestra", back_populates="custodias")