from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, login_manager
from app.models.base import BaseModel, TenantMixin


class Usuario(UserMixin, TenantMixin, BaseModel):
    __tablename__ = "usuarios"
    __table_args__ = (
        db.UniqueConstraint("empresa_id", "email", name="uq_usuarios_empresa_email"),
        db.UniqueConstraint("empresa_id", "username", name="uq_usuarios_empresa_username"),
    )

    sede_id = db.Column(db.BigInteger, db.ForeignKey("sedes.id"))
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    username = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    cargo = db.Column(db.String(120))
    telefono = db.Column(db.String(50))
    activo = db.Column(db.Boolean, default=True, nullable=False)
    ultimo_login = db.Column(db.DateTime(timezone=True))

    empresa = db.relationship("Empresa", back_populates="usuarios")
    sede = db.relationship("Sede", back_populates="usuarios")

    roles = db.relationship(
        "UsuarioRol",
        back_populates="usuario",
        cascade="all, delete-orphan",
        lazy=True
    )

    solicitudes_creadas = db.relationship(
        "Solicitud",
        foreign_keys="Solicitud.creado_por_id",
        back_populates="creado_por",
        lazy=True
    )

    muestras_recibidas = db.relationship(
        "Muestra",
        foreign_keys="Muestra.recibido_por_id",
        back_populates="recibido_por",
        lazy=True
    )

    muestra_ensayos_asignados = db.relationship(
        "MuestraEnsayo",
        foreign_keys="MuestraEnsayo.analista_id",
        back_populates="analista",
        lazy=True
    )

    resultados_registrados = db.relationship(
        "Resultado",
        foreign_keys="Resultado.registrado_por_id",
        back_populates="registrado_por",
        lazy=True
    )

    resultados_revisados = db.relationship(
        "Resultado",
        foreign_keys="Resultado.revisado_por_id",
        back_populates="revisado_por",
        lazy=True
    )

    resultados_aprobados = db.relationship(
        "Resultado",
        foreign_keys="Resultado.aprobado_por_id",
        back_populates="aprobado_por",
        lazy=True
    )

    competencias = db.relationship(
        "PersonalCompetencia",
        foreign_keys="PersonalCompetencia.usuario_id",
        back_populates="usuario",
        lazy=True
    )

    logs = db.relationship("AuditoriaLog", back_populates="usuario", lazy=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)


class Rol(BaseModel):
    __tablename__ = "roles"

    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    es_sistema = db.Column(db.Boolean, default=False, nullable=False)

    usuarios = db.relationship(
        "UsuarioRol",
        back_populates="rol",
        cascade="all, delete-orphan",
        lazy=True
    )

    permisos = db.relationship(
        "RolPermiso",
        back_populates="rol",
        cascade="all, delete-orphan",
        lazy=True
    )


class Permiso(BaseModel):
    __tablename__ = "permisos"

    codigo = db.Column(db.String(100), nullable=False, unique=True)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    modulo = db.Column(db.String(100))

    roles = db.relationship(
        "RolPermiso",
        back_populates="permiso",
        cascade="all, delete-orphan",
        lazy=True
    )


class UsuarioRol(BaseModel):
    __tablename__ = "usuario_roles"
    __table_args__ = (
        db.UniqueConstraint("usuario_id", "rol_id", name="uq_usuario_rol"),
    )

    usuario_id = db.Column(db.BigInteger, db.ForeignKey("usuarios.id"), nullable=False)
    rol_id = db.Column(db.BigInteger, db.ForeignKey("roles.id"), nullable=False)

    usuario = db.relationship("Usuario", back_populates="roles")
    rol = db.relationship("Rol", back_populates="usuarios")


class RolPermiso(BaseModel):
    __tablename__ = "rol_permisos"
    __table_args__ = (
        db.UniqueConstraint("rol_id", "permiso_id", name="uq_rol_permiso"),
    )

    rol_id = db.Column(db.BigInteger, db.ForeignKey("roles.id"), nullable=False)
    permiso_id = db.Column(db.BigInteger, db.ForeignKey("permisos.id"), nullable=False)

    rol = db.relationship("Rol", back_populates="permisos")
    permiso = db.relationship("Permiso", back_populates="roles")


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))