from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from app.extensions import db
from app.models.organigrama import (
    Cargo,
    ESTADOS_CAPACITACION_PERSONAL,
    ESTADOS_PARTICIPACION_CAPACITACION,
    ESTADOS_PERSONAL,
    MODALIDADES_CAPACITACION_PERSONAL,
    PerfilPuesto,
    Personal,
    PersonalCapacitacion,
    PersonalCapacitacionEvidencia,
    PersonalCapacitacionParticipante,
    PersonalCalificacion,
    PersonalCalificacionEvidencia,
    PersonalExperiencia,
    TIPOS_CALIFICACION_PERSONAL,
    TIPOS_CAPACITACION_PERSONAL,
    TIPOS_EVIDENCIA_CAPACITACION,
)
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission
from app.services.storage_service import (
    DocumentStorageError,
    store_personal_evidence_file,
    store_personal_training_evidence_file,
)


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


def _decimal_from_form(value):
    value = _clean(value)
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise PersonalError("La duracion debe ser un numero valido.") from exc


def ensure_permission(user, permission_code):
    if not user_has_permission(user, permission_code):
        raise PersonalError("No tienes permisos para realizar esta accion.")


def get_cargo(user, cargo_id):
    return Cargo.query.filter_by(id=cargo_id, empresa_id=user.empresa_id).first()


def get_personal(user, personal_id):
    return Personal.query.filter_by(id=personal_id, empresa_id=user.empresa_id).first()


def get_perfil(user, perfil_id):
    return PerfilPuesto.query.filter_by(id=perfil_id, empresa_id=user.empresa_id).first()


def get_calificacion(user, calificacion_id):
    return PersonalCalificacion.query.filter_by(id=calificacion_id, empresa_id=user.empresa_id).first()


def get_experiencia(user, experiencia_id):
    return PersonalExperiencia.query.filter_by(id=experiencia_id, empresa_id=user.empresa_id).first()


def get_evidencia(user, evidencia_id):
    return PersonalCalificacionEvidencia.query.filter_by(id=evidencia_id, empresa_id=user.empresa_id).first()


def get_capacitacion(user, capacitacion_id):
    return PersonalCapacitacion.query.filter_by(id=capacitacion_id, empresa_id=user.empresa_id).first()


def get_capacitacion_participante(user, participante_id):
    return PersonalCapacitacionParticipante.query.filter_by(id=participante_id, empresa_id=user.empresa_id).first()


def get_capacitacion_evidencia(user, evidencia_id):
    return PersonalCapacitacionEvidencia.query.filter_by(id=evidencia_id, empresa_id=user.empresa_id).first()


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


def _validate_personal_record(user, personal_id):
    personal = get_personal(user, personal_id)
    if not personal:
        raise PersonalError("El personal seleccionado no pertenece a esta empresa.")
    return personal


def _apply_calificacion_data(user, item, data):
    personal = _validate_personal_record(user, data.get("personal_id") or item.personal_id)
    item.empresa_id = user.empresa_id
    item.personal_id = personal.id
    item.tipo = _clean(data.get("tipo"), upper=True) or "OTRO"
    item.institucion = _clean(data.get("institucion"))
    item.titulo = _clean(data.get("titulo"))
    item.area_especialidad = _clean(data.get("area_especialidad"))
    item.fecha_inicio = _date_from_form(data.get("fecha_inicio"))
    item.fecha_fin = _date_from_form(data.get("fecha_fin"))
    item.numero_registro = _clean(data.get("numero_registro"))
    item.observaciones = _clean(data.get("observaciones"))
    item.activo = _bool_from_form(data.get("activo", "1"))
    if item.tipo not in TIPOS_CALIFICACION_PERSONAL:
        raise PersonalError("Tipo de calificacion invalido.")
    if not item.institucion:
        raise PersonalError("La institucion es obligatoria.")
    if not item.titulo:
        raise PersonalError("El titulo o denominacion es obligatorio.")
    if item.fecha_inicio and item.fecha_fin and item.fecha_fin < item.fecha_inicio:
        raise PersonalError("La fecha de fin no puede ser anterior a la fecha de inicio.")


def create_calificacion(user, personal_id, data):
    ensure_permission(user, PERM_GESTIONAR)
    item = PersonalCalificacion()
    payload = dict(data)
    payload["personal_id"] = personal_id
    _apply_calificacion_data(user, item, payload)
    db.session.add(item)
    return item


def update_calificacion(user, item, data):
    ensure_permission(user, PERM_GESTIONAR)
    if item.empresa_id != user.empresa_id:
        raise PersonalError("La calificacion no pertenece a esta empresa.")
    _apply_calificacion_data(user, item, data)
    return item


def set_calificacion_active(user, item, active):
    ensure_permission(user, PERM_GESTIONAR)
    if item.empresa_id != user.empresa_id:
        raise PersonalError("La calificacion no pertenece a esta empresa.")
    item.activo = bool(active)
    return item


def add_calificacion_evidencia(user, calificacion, file_storage, observaciones=None):
    ensure_permission(user, PERM_GESTIONAR)
    if not calificacion or calificacion.empresa_id != user.empresa_id:
        raise PersonalError("La calificacion no pertenece a esta empresa.")
    if not calificacion.personal or calificacion.personal.empresa_id != user.empresa_id:
        raise PersonalError("El personal de la calificacion no pertenece a esta empresa.")
    if not file_storage or not file_storage.filename:
        raise PersonalError("Selecciona un archivo de evidencia.")
    try:
        stored = store_personal_evidence_file(
            file_storage,
            personal=calificacion.personal,
            calificacion=calificacion,
        )
    except DocumentStorageError as exc:
        raise PersonalError(str(exc)) from exc
    evidencia = PersonalCalificacionEvidencia(
        empresa_id=user.empresa_id,
        personal_id=calificacion.personal_id,
        calificacion_id=calificacion.id,
        archivo_nombre_original=stored.original_name,
        archivo_nombre_guardado=stored.stored_name,
        archivo_storage_path=stored.storage_path,
        archivo_mime=stored.mime_type,
        archivo_size=stored.size,
        archivo_sha256=stored.sha256,
        cargado_por_id=user.id,
        observaciones=_clean(observaciones),
        activo=True,
    )
    db.session.add(evidencia)
    return evidencia


def set_evidencia_active(user, evidencia, active):
    ensure_permission(user, PERM_GESTIONAR)
    if not evidencia or evidencia.empresa_id != user.empresa_id:
        raise PersonalError("La evidencia no pertenece a esta empresa.")
    if evidencia.calificacion.empresa_id != user.empresa_id or evidencia.personal.empresa_id != user.empresa_id:
        raise PersonalError("La evidencia no pertenece a esta empresa.")
    evidencia.activo = bool(active)
    return evidencia


def _apply_experiencia_data(user, item, data):
    personal = _validate_personal_record(user, data.get("personal_id") or item.personal_id)
    item.empresa_id = user.empresa_id
    item.personal_id = personal.id
    item.organizacion = _clean(data.get("organizacion"))
    item.cargo_funcion = _clean(data.get("cargo_funcion"))
    item.area_especialidad = _clean(data.get("area_especialidad"))
    item.descripcion_actividades = _clean(data.get("descripcion_actividades"))
    item.fecha_inicio = _date_from_form(data.get("fecha_inicio"))
    item.fecha_fin = _date_from_form(data.get("fecha_fin"))
    item.experiencia_actual = _bool_from_form(data.get("experiencia_actual"))
    item.observaciones = _clean(data.get("observaciones"))
    item.activo = _bool_from_form(data.get("activo", "1"))
    if not item.organizacion:
        raise PersonalError("La organizacion es obligatoria.")
    if not item.cargo_funcion:
        raise PersonalError("El cargo o funcion es obligatorio.")
    if not item.fecha_inicio:
        raise PersonalError("La fecha de inicio es obligatoria.")
    if item.experiencia_actual:
        item.fecha_fin = None
    if item.fecha_fin and item.fecha_fin < item.fecha_inicio:
        raise PersonalError("La fecha de fin no puede ser anterior a la fecha de inicio.")


def create_experiencia(user, personal_id, data):
    ensure_permission(user, PERM_GESTIONAR)
    item = PersonalExperiencia()
    payload = dict(data)
    payload["personal_id"] = personal_id
    _apply_experiencia_data(user, item, payload)
    db.session.add(item)
    return item


def update_experiencia(user, item, data):
    ensure_permission(user, PERM_GESTIONAR)
    if item.empresa_id != user.empresa_id:
        raise PersonalError("La experiencia no pertenece a esta empresa.")
    _apply_experiencia_data(user, item, data)
    return item


def cerrar_experiencia_actual(user, item, fecha_fin):
    ensure_permission(user, PERM_GESTIONAR)
    if item.empresa_id != user.empresa_id:
        raise PersonalError("La experiencia no pertenece a esta empresa.")
    fecha_fin = _date_from_form(fecha_fin)
    if not fecha_fin:
        raise PersonalError("La fecha de cierre es obligatoria.")
    if fecha_fin < item.fecha_inicio:
        raise PersonalError("La fecha de fin no puede ser anterior a la fecha de inicio.")
    item.experiencia_actual = False
    item.fecha_fin = fecha_fin
    return item


def set_experiencia_active(user, item, active):
    ensure_permission(user, PERM_GESTIONAR)
    if item.empresa_id != user.empresa_id:
        raise PersonalError("La experiencia no pertenece a esta empresa.")
    item.activo = bool(active)
    return item


def _validate_capacitacion_record(user, capacitacion):
    if not capacitacion or capacitacion.empresa_id != user.empresa_id:
        raise PersonalError("La capacitacion no pertenece a esta empresa.")
    return capacitacion


def _validate_participante_record(user, participante):
    if not participante or participante.empresa_id != user.empresa_id:
        raise PersonalError("El participante no pertenece a esta empresa.")
    if not participante.capacitacion or participante.capacitacion.empresa_id != user.empresa_id:
        raise PersonalError("La capacitacion del participante no pertenece a esta empresa.")
    if not participante.personal or participante.personal.empresa_id != user.empresa_id:
        raise PersonalError("El personal participante no pertenece a esta empresa.")
    return participante


def validate_capacitacion_code(user, codigo, current_id=None):
    if not codigo:
        return
    query = PersonalCapacitacion.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(PersonalCapacitacion.id != current_id)
    if query.first():
        raise PersonalError("Ya existe una capacitacion con ese codigo en esta empresa.")


def _apply_capacitacion_data(user, item, data, current_id=None):
    item.empresa_id = user.empresa_id
    item.codigo = _clean(data.get("codigo"), upper=True)
    item.nombre = _clean(data.get("nombre") or data.get("tema"))
    item.tipo = _clean(data.get("tipo"), upper=True) or "OTRO"
    item.objetivo = _clean(data.get("objetivo"))
    item.proveedor = _clean(data.get("proveedor") or data.get("institucion"))
    item.instructor = _clean(data.get("instructor"))
    item.modalidad = _clean(data.get("modalidad"), upper=True) or "PRESENCIAL"
    item.fecha_inicio = _date_from_form(data.get("fecha_inicio"))
    item.fecha_fin = _date_from_form(data.get("fecha_fin"))
    item.duracion_horas = _decimal_from_form(data.get("duracion_horas"))
    item.lugar = _clean(data.get("lugar"))
    item.estado = _clean(data.get("estado"), upper=True) or "PLANIFICADA"
    item.observaciones = _clean(data.get("observaciones"))

    if not item.nombre:
        raise PersonalError("El nombre de la capacitacion es obligatorio.")
    if item.tipo not in TIPOS_CAPACITACION_PERSONAL:
        raise PersonalError("Tipo de capacitacion invalido.")
    if item.modalidad not in MODALIDADES_CAPACITACION_PERSONAL:
        raise PersonalError("Modalidad de capacitacion invalida.")
    if item.estado not in ESTADOS_CAPACITACION_PERSONAL:
        raise PersonalError("Estado de capacitacion invalido.")
    if not item.fecha_inicio:
        raise PersonalError("La fecha de inicio es obligatoria.")
    if item.fecha_fin and item.fecha_fin < item.fecha_inicio:
        raise PersonalError("La fecha de fin no puede ser anterior a la fecha de inicio.")
    if item.duracion_horas is not None and item.duracion_horas < 0:
        raise PersonalError("La duracion no puede ser negativa.")
    validate_capacitacion_code(user, item.codigo, current_id)


def create_capacitacion(user, data):
    ensure_permission(user, PERM_GESTIONAR)
    item = PersonalCapacitacion()
    _apply_capacitacion_data(user, item, data)
    db.session.add(item)
    return item


def update_capacitacion(user, item, data):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_capacitacion_record(user, item)
    if item.estado == "CANCELADA" and _clean(data.get("estado"), upper=True) == "COMPLETADA":
        raise PersonalError("Una capacitacion cancelada no puede completarse directamente.")
    _apply_capacitacion_data(user, item, data, current_id=item.id)
    return item


def set_capacitacion_estado(user, item, estado):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_capacitacion_record(user, item)
    estado = _clean(estado, upper=True)
    if estado not in ESTADOS_CAPACITACION_PERSONAL:
        raise PersonalError("Estado de capacitacion invalido.")
    if item.estado == "CANCELADA" and estado == "COMPLETADA":
        raise PersonalError("Una capacitacion cancelada no puede completarse directamente.")
    item.estado = estado
    return item


def capacitaciones_query(user, filters=None):
    filters = filters or {}
    query = PersonalCapacitacion.query.filter_by(empresa_id=user.empresa_id)
    if filters.get("q"):
        like = f"%{filters['q']}%"
        query = query.filter(
            or_(
                PersonalCapacitacion.codigo.ilike(like),
                PersonalCapacitacion.nombre.ilike(like),
                PersonalCapacitacion.proveedor.ilike(like),
            )
        )
    if filters.get("estado"):
        query = query.filter(PersonalCapacitacion.estado == filters["estado"])
    if filters.get("tipo"):
        query = query.filter(PersonalCapacitacion.tipo == filters["tipo"])
    return query.order_by(PersonalCapacitacion.fecha_inicio.desc(), PersonalCapacitacion.id.desc())


def add_capacitacion_participante(user, capacitacion, personal_id, data=None):
    ensure_permission(user, PERM_GESTIONAR)
    data = data or {}
    _validate_capacitacion_record(user, capacitacion)
    personal = _validate_personal_record(user, personal_id)
    if personal.estado != "ACTIVO":
        raise PersonalError("No se puede agregar personal inactivo a una capacitacion nueva.")
    existing = PersonalCapacitacionParticipante.query.filter_by(
        empresa_id=user.empresa_id,
        capacitacion_id=capacitacion.id,
        personal_id=personal.id,
    ).first()
    if existing:
        raise PersonalError("La persona ya esta registrada en esta capacitacion.")
    estado = _clean(data.get("estado_participacion"), upper=True) or "INSCRITO"
    if estado not in ESTADOS_PARTICIPACION_CAPACITACION:
        raise PersonalError("Estado de participacion invalido.")
    participante = PersonalCapacitacionParticipante(
        empresa_id=user.empresa_id,
        capacitacion_id=capacitacion.id,
        personal_id=personal.id,
        estado_participacion=estado,
        fecha_registro=_date_from_form(data.get("fecha_registro")) or date.today(),
        observaciones=_clean(data.get("observaciones")),
        activo=True,
    )
    db.session.add(participante)
    return participante


def update_capacitacion_participante(user, participante, data):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_participante_record(user, participante)
    estado = _clean(data.get("estado_participacion"), upper=True) or participante.estado_participacion
    if estado not in ESTADOS_PARTICIPACION_CAPACITACION:
        raise PersonalError("Estado de participacion invalido.")
    participante.estado_participacion = estado
    participante.fecha_registro = _date_from_form(data.get("fecha_registro")) or participante.fecha_registro
    participante.observaciones = _clean(data.get("observaciones"))
    participante.activo = _bool_from_form(data.get("activo", "1"))
    return participante


def set_capacitacion_participante_active(user, participante, active):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_participante_record(user, participante)
    participante.activo = bool(active)
    if not active and participante.estado_participacion not in {"COMPLETO", "NO_ASISTIO"}:
        participante.estado_participacion = "RETIRADO"
    return participante


def add_capacitacion_evidencia(user, capacitacion, file_storage, data=None):
    ensure_permission(user, PERM_GESTIONAR)
    data = data or {}
    _validate_capacitacion_record(user, capacitacion)
    participante = None
    participante_id = data.get("participante_id")
    if participante_id:
        participante = get_capacitacion_participante(user, participante_id)
        _validate_participante_record(user, participante)
        if participante.capacitacion_id != capacitacion.id:
            raise PersonalError("El participante no pertenece a esta capacitacion.")
    tipo_evidencia = _clean(data.get("tipo_evidencia"), upper=True) or "OTRO"
    if tipo_evidencia not in TIPOS_EVIDENCIA_CAPACITACION:
        raise PersonalError("Tipo de evidencia de capacitacion invalido.")
    if not file_storage or not file_storage.filename:
        raise PersonalError("Selecciona un archivo de evidencia.")
    try:
        stored = store_personal_training_evidence_file(
            file_storage,
            capacitacion=capacitacion,
            participante=participante,
        )
    except DocumentStorageError as exc:
        raise PersonalError(str(exc)) from exc
    evidencia = PersonalCapacitacionEvidencia(
        empresa_id=user.empresa_id,
        capacitacion_id=capacitacion.id,
        participante_id=participante.id if participante else None,
        archivo_nombre_original=stored.original_name,
        archivo_nombre_guardado=stored.stored_name,
        archivo_storage_path=stored.storage_path,
        archivo_mime=stored.mime_type,
        archivo_size=stored.size,
        archivo_sha256=stored.sha256,
        tipo_evidencia=tipo_evidencia,
        cargado_por_id=user.id,
        observaciones=_clean(data.get("observaciones")),
        activo=True,
    )
    db.session.add(evidencia)
    return evidencia


def set_capacitacion_evidencia_active(user, evidencia, active):
    ensure_permission(user, PERM_GESTIONAR)
    if not evidencia or evidencia.empresa_id != user.empresa_id:
        raise PersonalError("La evidencia no pertenece a esta empresa.")
    if evidencia.capacitacion.empresa_id != user.empresa_id:
        raise PersonalError("La evidencia no pertenece a esta empresa.")
    if evidencia.participante:
        _validate_participante_record(user, evidencia.participante)
        if evidencia.participante.capacitacion_id != evidencia.capacitacion_id:
            raise PersonalError("La evidencia no corresponde a esta capacitacion.")
    evidencia.activo = bool(active)
    return evidencia
