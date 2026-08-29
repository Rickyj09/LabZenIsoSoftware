from datetime import date

from app.extensions import db
from app.models.organigrama import Cargo, ESTADOS_PERSONAL, PerfilPuesto, Personal
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission


PERM_VER = "personal.ver"
PERM_GESTIONAR = "personal.gestionar"


class PersonalError(ValueError):
    pass


def _clean(value, upper=False):
    value = (value or "").strip()
    if upper:
        value = value.upper()
    return value or None


def _bool_from_form(value):
    return value in {True, "1", "true", "on", "si", "SI", "yes", "YES"}


def _date_from_form(value):
    if isinstance(value, date):
        return value
    value = _clean(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PersonalError("Formato de fecha invalido. Usa AAAA-MM-DD.") from exc


def ensure_permission(user, permission_code):
    if not user_has_permission(user, permission_code):
        raise PersonalError("No tienes permisos para realizar esta accion.")


def get_cargo(user, cargo_id):
    return Cargo.query.filter_by(id=cargo_id, empresa_id=user.empresa_id).first()


def get_personal(user, personal_id):
    return Personal.query.filter_by(id=personal_id, empresa_id=user.empresa_id).first()


def get_perfil(user, perfil_id):
    return PerfilPuesto.query.filter_by(id=perfil_id, empresa_id=user.empresa_id).first()


def active_cargos(user):
    return (
        Cargo.query
        .filter_by(empresa_id=user.empresa_id, activo=True)
        .order_by(Cargo.codigo.asc())
        .all()
    )


def company_users(user):
    return (
        Usuario.query
        .filter_by(empresa_id=user.empresa_id, activo=True)
        .order_by(Usuario.nombre.asc(), Usuario.apellido.asc())
        .all()
    )


def validate_cargo_code(user, codigo, current_id=None):
    if not codigo:
        raise PersonalError("El codigo del cargo es obligatorio.")
    query = Cargo.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(Cargo.id != current_id)
    if query.first():
        raise PersonalError("Ya existe un cargo con ese codigo en esta empresa.")


def validate_cargo_name(user, nombre, current_id=None):
    if not nombre:
        raise PersonalError("El nombre del cargo es obligatorio.")
    query = Cargo.query.filter_by(empresa_id=user.empresa_id, nombre=nombre)
    if current_id:
        query = query.filter(Cargo.id != current_id)
    if query.first():
        raise PersonalError("Ya existe un cargo con ese nombre en esta empresa.")


def validate_personal_code(user, codigo, current_id=None):
    if not codigo:
        raise PersonalError("El codigo interno del personal es obligatorio.")
    query = Personal.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(Personal.id != current_id)
    if query.first():
        raise PersonalError("Ya existe una persona con ese codigo en esta empresa.")


def validate_personal_identification(user, identificacion, current_id=None):
    if not identificacion:
        return
    query = Personal.query.filter_by(empresa_id=user.empresa_id, identificacion=identificacion)
    if current_id:
        query = query.filter(Personal.id != current_id)
    if query.first():
        raise PersonalError("Ya existe una persona con esa identificacion en esta empresa.")


def validate_personal_user(user, usuario_id, current_id=None):
    if not usuario_id:
        return None
    selected_user = Usuario.query.filter_by(id=usuario_id, empresa_id=user.empresa_id).first()
    if not selected_user:
        raise PersonalError("El usuario asociado no pertenece a esta empresa.")
    query = Personal.query.filter_by(empresa_id=user.empresa_id, usuario_id=selected_user.id)
    if current_id:
        query = query.filter(Personal.id != current_id)
    if query.first():
        raise PersonalError("Ese usuario ya esta asociado a otro registro de personal.")
    return selected_user


def _validate_cargo_belongs_to_company(user, cargo_id):
    cargo = get_cargo(user, cargo_id)
    if not cargo:
        raise PersonalError("El cargo seleccionado no pertenece a esta empresa.")
    return cargo


def _apply_cargo_data(item, data):
    item.codigo = _clean(data.get("codigo"), upper=True)
    item.nombre = _clean(data.get("nombre"))
    item.descripcion = _clean(data.get("descripcion"))
    item.activo = _bool_from_form(data.get("activo", "1"))


def create_cargo(user, data):
    ensure_permission(user, PERM_GESTIONAR)
    codigo = _clean(data.get("codigo"), upper=True)
    nombre = _clean(data.get("nombre"))
    validate_cargo_code(user, codigo)
    validate_cargo_name(user, nombre)
    item = Cargo(empresa_id=user.empresa_id)
    _apply_cargo_data(item, data)
    db.session.add(item)
    return item


def update_cargo(user, item, data):
    ensure_permission(user, PERM_GESTIONAR)
    codigo = _clean(data.get("codigo"), upper=True)
    nombre = _clean(data.get("nombre"))
    validate_cargo_code(user, codigo, item.id)
    validate_cargo_name(user, nombre, item.id)
    _apply_cargo_data(item, data)
    return item


def set_cargo_active(user, item, active):
    ensure_permission(user, PERM_GESTIONAR)
    item.activo = bool(active)
    return item


def upsert_perfil(user, cargo, data):
    ensure_permission(user, PERM_GESTIONAR)
    if cargo.empresa_id != user.empresa_id:
        raise PersonalError("El cargo seleccionado no pertenece a esta empresa.")
    perfil = cargo.perfil or PerfilPuesto(empresa_id=user.empresa_id, cargo_id=cargo.id)
    perfil.proposito = _clean(data.get("proposito"))
    perfil.funciones = _clean(data.get("funciones"))
    perfil.responsabilidades = _clean(data.get("responsabilidades"))
    perfil.autoridad = _clean(data.get("autoridad"))
    perfil.observaciones = _clean(data.get("perfil_observaciones") or data.get("observaciones_perfil"))
    perfil.activo = _bool_from_form(data.get("perfil_activo", "1"))
    db.session.add(perfil)
    return perfil


def _apply_personal_data(user, item, data, current_id=None):
    item.codigo = _clean(data.get("codigo"), upper=True)
    item.nombres = _clean(data.get("nombres"))
    item.apellidos = _clean(data.get("apellidos"))
    item.identificacion = _clean(data.get("identificacion"))
    item.email = _clean(data.get("email") or data.get("correo"))
    item.telefono = _clean(data.get("telefono"))
    item.fecha_ingreso = _date_from_form(data.get("fecha_ingreso"))
    item.fecha_salida = _date_from_form(data.get("fecha_salida"))
    item.estado = _clean(data.get("estado"), upper=True) or "ACTIVO"
    item.observaciones = _clean(data.get("observaciones"))
    if not item.nombres or not item.apellidos:
        raise PersonalError("Nombres y apellidos son obligatorios.")
    if item.estado not in ESTADOS_PERSONAL:
        raise PersonalError("Estado de personal invalido.")
    if item.fecha_salida and item.fecha_ingreso and item.fecha_salida < item.fecha_ingreso:
        raise PersonalError("La fecha de salida no puede ser anterior a la fecha de ingreso.")
    validate_personal_code(user, item.codigo, current_id)
    validate_personal_identification(user, item.identificacion, current_id)
    cargo = _validate_cargo_belongs_to_company(user, data.get("cargo_id"))
    selected_user = validate_personal_user(user, data.get("usuario_id"), current_id)
    item.cargo_id = cargo.id
    item.usuario_id = selected_user.id if selected_user else None


def create_personal(user, data):
    ensure_permission(user, PERM_GESTIONAR)
    item = Personal(empresa_id=user.empresa_id)
    _apply_personal_data(user, item, data)
    db.session.add(item)
    return item


def update_personal(user, item, data):
    ensure_permission(user, PERM_GESTIONAR)
    _apply_personal_data(user, item, data, current_id=item.id)
    return item


def set_personal_status(user, item, estado):
    ensure_permission(user, PERM_GESTIONAR)
    estado = _clean(estado, upper=True)
    if estado not in ESTADOS_PERSONAL:
        raise PersonalError("Estado de personal invalido.")
    item.estado = estado
    return item
