from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from app.extensions import db
from app.models.equipos import Equipo
from app.models.organigrama import (
    Cargo,
    ESTADOS_AUTORIZACION_TECNICA,
    ESTADOS_CAPACITACION_PERSONAL,
    ESTADOS_PARTICIPACION_CAPACITACION,
    ESTADOS_PERSONAL,
    METODOS_EVALUACION_COMPETENCIA,
    MODALIDADES_CAPACITACION_PERSONAL,
    PerfilPuesto,
    Personal,
    PersonalAutorizacionTecnica,
    PersonalAutorizacionTecnicaEvidencia,
    PersonalCapacitacion,
    PersonalCapacitacionEvidencia,
    PersonalCapacitacionParticipante,
    PersonalCalificacion,
    PersonalCalificacionEvidencia,
    PersonalEvaluacionCompetencia,
    PersonalEvaluacionCompetenciaEvidencia,
    PersonalExperiencia,
    RESULTADOS_EVALUACION_COMPETENCIA,
    TIPOS_AUTORIZACION_TECNICA,
    TIPOS_CALIFICACION_PERSONAL,
    TIPOS_CAPACITACION_PERSONAL,
    TIPOS_COMPETENCIA_PERSONAL,
    TIPOS_EVIDENCIA_CAPACITACION,
    TIPOS_EVIDENCIA_AUTORIZACION_TECNICA,
    TIPOS_EVIDENCIA_EVALUACION_COMPETENCIA,
)
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission
from app.services.storage_service import (
    DocumentStorageError,
    store_personal_authorization_evidence_file,
    store_personal_competency_evidence_file,
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


def get_evaluacion_competencia(user, evaluacion_id):
    return PersonalEvaluacionCompetencia.query.filter_by(id=evaluacion_id, empresa_id=user.empresa_id).first()


def get_evaluacion_competencia_evidencia(user, evidencia_id):
    return PersonalEvaluacionCompetenciaEvidencia.query.filter_by(
        id=evidencia_id,
        empresa_id=user.empresa_id,
    ).first()


def get_autorizacion_tecnica(user, autorizacion_id):
    return PersonalAutorizacionTecnica.query.filter_by(id=autorizacion_id, empresa_id=user.empresa_id).first()


def get_autorizacion_tecnica_evidencia(user, evidencia_id):
    return PersonalAutorizacionTecnicaEvidencia.query.filter_by(id=evidencia_id, empresa_id=user.empresa_id).first()


def get_equipo(user, equipo_id):
    return Equipo.query.filter_by(id=equipo_id, empresa_id=user.empresa_id).first()


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


def _validate_evaluacion_record(user, evaluacion):
    if not evaluacion or evaluacion.empresa_id != user.empresa_id:
        raise PersonalError("La evaluacion de competencia no pertenece a esta empresa.")
    if not evaluacion.personal or evaluacion.personal.empresa_id != user.empresa_id:
        raise PersonalError("El personal evaluado no pertenece a esta empresa.")
    if evaluacion.evaluador_personal and evaluacion.evaluador_personal.empresa_id != user.empresa_id:
        raise PersonalError("El evaluador no pertenece a esta empresa.")
    return evaluacion


def validate_evaluacion_competencia_code(user, codigo, current_id=None):
    if not codigo:
        return
    query = PersonalEvaluacionCompetencia.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(PersonalEvaluacionCompetencia.id != current_id)
    if query.first():
        raise PersonalError("Ya existe una evaluacion de competencia con ese codigo en esta empresa.")


def _validate_evaluacion_training_relation(user, item, data):
    item.capacitacion_id = None
    item.capacitacion_participante_id = None
    capacitacion_id = data.get("capacitacion_id")
    participante_id = data.get("capacitacion_participante_id")
    if capacitacion_id:
        capacitacion = get_capacitacion(user, capacitacion_id)
        if not capacitacion:
            raise PersonalError("La capacitacion asociada no pertenece a esta empresa.")
        item.capacitacion_id = capacitacion.id
    if participante_id:
        participante = get_capacitacion_participante(user, participante_id)
        _validate_participante_record(user, participante)
        if participante.personal_id != item.personal_id:
            raise PersonalError("La participacion asociada no corresponde al personal evaluado.")
        if item.capacitacion_id and participante.capacitacion_id != item.capacitacion_id:
            raise PersonalError("La participacion no corresponde a la capacitacion asociada.")
        item.capacitacion_participante_id = participante.id
        item.capacitacion_id = participante.capacitacion_id


def _apply_evaluacion_competencia_data(user, item, data, personal_id=None, current_id=None):
    selected_personal_id = personal_id if personal_id is not None else (data.get("personal_id") or item.personal_id)
    personal = _validate_personal_record(user, selected_personal_id)
    item.empresa_id = user.empresa_id
    item.personal_id = personal.id
    item.codigo = _clean(data.get("codigo"), upper=True)
    item.actividad = _clean(data.get("actividad"))
    item.descripcion = _clean(data.get("descripcion"))
    item.tipo_competencia = _clean(data.get("tipo_competencia"), upper=True) or "TECNICA"
    item.metodo_evaluacion = _clean(data.get("metodo_evaluacion"), upper=True)
    item.criterio_evaluacion = _clean(data.get("criterio_evaluacion") or data.get("criterios"))
    item.criterios = _clean(data.get("criterios"))
    item.descripcion_metodo = _clean(data.get("descripcion_metodo"))
    item.fecha_evaluacion = _date_from_form(data.get("fecha_evaluacion"))
    item.resultado = _clean(data.get("resultado"), upper=True)
    item.conclusion = _clean(data.get("conclusion"))
    item.observaciones = _clean(data.get("observaciones"))
    item.evaluador_externo_nombre = _clean(data.get("evaluador_externo_nombre"))
    item.evaluador_externo_entidad = _clean(data.get("evaluador_externo_entidad"))
    item.activo = _bool_from_form(data.get("activo", "1"))

    if not item.actividad:
        raise PersonalError("La actividad evaluada es obligatoria.")
    if item.tipo_competencia not in TIPOS_COMPETENCIA_PERSONAL:
        raise PersonalError("Tipo de competencia invalido.")
    if item.metodo_evaluacion not in METODOS_EVALUACION_COMPETENCIA:
        raise PersonalError("Metodo de evaluacion invalido.")
    if not item.criterio_evaluacion:
        raise PersonalError("El criterio de evaluacion es obligatorio.")
    if not item.fecha_evaluacion:
        raise PersonalError("La fecha de evaluacion es obligatoria.")
    if item.resultado not in RESULTADOS_EVALUACION_COMPETENCIA:
        raise PersonalError("Resultado de evaluacion invalido.")

    item.evaluador_personal_id = None
    evaluador_personal_id = data.get("evaluador_personal_id")
    if evaluador_personal_id:
        with db.session.no_autoflush:
            evaluador = _validate_personal_record(user, evaluador_personal_id)
        item.evaluador_personal_id = evaluador.id
        item.evaluador_externo_nombre = None
        item.evaluador_externo_entidad = None
    if not item.evaluador_personal_id and not item.evaluador_externo_nombre:
        raise PersonalError("Indica un evaluador interno o externo.")

    item.evaluador_usuario_id = None
    evaluador_usuario_id = data.get("evaluador_usuario_id")
    if evaluador_usuario_id:
        selected_user = Usuario.query.filter_by(id=evaluador_usuario_id, empresa_id=user.empresa_id).first()
        if not selected_user:
            raise PersonalError("El usuario evaluador no pertenece a esta empresa.")
        item.evaluador_usuario_id = selected_user.id

    validate_evaluacion_competencia_code(user, item.codigo, current_id)
    _validate_evaluacion_training_relation(user, item, data)


def create_evaluacion_competencia(user, personal_id, data):
    ensure_permission(user, PERM_GESTIONAR)
    item = PersonalEvaluacionCompetencia()
    _apply_evaluacion_competencia_data(user, item, data, personal_id=personal_id)
    db.session.add(item)
    return item


def update_evaluacion_competencia(user, item, data):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_evaluacion_record(user, item)
    _apply_evaluacion_competencia_data(user, item, data, current_id=item.id)
    return item


def set_evaluacion_competencia_active(user, item, active):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_evaluacion_record(user, item)
    item.activo = bool(active)
    return item


def evaluaciones_competencia_query(user, filters=None):
    filters = filters or {}
    query = PersonalEvaluacionCompetencia.query.filter_by(empresa_id=user.empresa_id)
    if filters.get("persona_id"):
        query = query.filter(PersonalEvaluacionCompetencia.personal_id == filters["persona_id"])
    if filters.get("resultado"):
        query = query.filter(PersonalEvaluacionCompetencia.resultado == filters["resultado"])
    if filters.get("tipo"):
        query = query.filter(PersonalEvaluacionCompetencia.tipo_competencia == filters["tipo"])
    if filters.get("desde"):
        query = query.filter(PersonalEvaluacionCompetencia.fecha_evaluacion >= _date_from_form(filters["desde"]))
    if filters.get("hasta"):
        query = query.filter(PersonalEvaluacionCompetencia.fecha_evaluacion <= _date_from_form(filters["hasta"]))
    if filters.get("q"):
        like = f"%{filters['q']}%"
        query = query.join(Personal, Personal.id == PersonalEvaluacionCompetencia.personal_id).filter(
            or_(
                PersonalEvaluacionCompetencia.codigo.ilike(like),
                PersonalEvaluacionCompetencia.actividad.ilike(like),
                PersonalEvaluacionCompetencia.descripcion.ilike(like),
                Personal.nombres.ilike(like),
                Personal.apellidos.ilike(like),
                Personal.codigo.ilike(like),
            )
        )
    return query.order_by(
        PersonalEvaluacionCompetencia.fecha_evaluacion.desc(),
        PersonalEvaluacionCompetencia.id.desc(),
    )


def add_evaluacion_competencia_evidencia(user, evaluacion, file_storage, data=None):
    ensure_permission(user, PERM_GESTIONAR)
    data = data or {}
    _validate_evaluacion_record(user, evaluacion)
    tipo_evidencia = _clean(data.get("tipo_evidencia"), upper=True) or "OTRO"
    if tipo_evidencia not in TIPOS_EVIDENCIA_EVALUACION_COMPETENCIA:
        raise PersonalError("Tipo de evidencia de evaluacion invalido.")
    if not file_storage or not file_storage.filename:
        raise PersonalError("Selecciona un archivo de evidencia.")
    try:
        stored = store_personal_competency_evidence_file(file_storage, evaluacion=evaluacion)
    except DocumentStorageError as exc:
        raise PersonalError(str(exc)) from exc
    evidencia = PersonalEvaluacionCompetenciaEvidencia(
        empresa_id=user.empresa_id,
        evaluacion_id=evaluacion.id,
        tipo_evidencia=tipo_evidencia,
        archivo_nombre_original=stored.original_name,
        archivo_nombre_guardado=stored.stored_name,
        archivo_storage_path=stored.storage_path,
        archivo_mime=stored.mime_type,
        archivo_size=stored.size,
        archivo_sha256=stored.sha256,
        cargado_por_id=user.id,
        observaciones=_clean(data.get("observaciones")),
        activo=True,
    )
    db.session.add(evidencia)
    return evidencia


def set_evaluacion_competencia_evidencia_active(user, evidencia, active):
    ensure_permission(user, PERM_GESTIONAR)
    if not evidencia or evidencia.empresa_id != user.empresa_id:
        raise PersonalError("La evidencia no pertenece a esta empresa.")
    _validate_evaluacion_record(user, evidencia.evaluacion)
    evidencia.activo = bool(active)
    return evidencia


def estado_efectivo_autorizacion(autorizacion, today=None):
    today = today or date.today()
    if autorizacion.estado == "REVOCADA":
        return "REVOCADA"
    if autorizacion.estado == "SUSPENDIDA":
        return "SUSPENDIDA"
    if autorizacion.fecha_fin and autorizacion.fecha_fin < today:
        return "VENCIDA"
    return "VIGENTE"


def _validate_autorizacion_record(user, autorizacion):
    if not autorizacion or autorizacion.empresa_id != user.empresa_id:
        raise PersonalError("La autorizacion tecnica no pertenece a esta empresa.")
    if not autorizacion.personal or autorizacion.personal.empresa_id != user.empresa_id:
        raise PersonalError("El personal autorizado no pertenece a esta empresa.")
    if autorizacion.equipo and autorizacion.equipo.empresa_id != user.empresa_id:
        raise PersonalError("El equipo autorizado no pertenece a esta empresa.")
    if autorizacion.evaluacion_competencia:
        _validate_evaluacion_record(user, autorizacion.evaluacion_competencia)
    if autorizacion.autorizador_personal and autorizacion.autorizador_personal.empresa_id != user.empresa_id:
        raise PersonalError("El autorizador no pertenece a esta empresa.")
    if autorizacion.autorizador_usuario and autorizacion.autorizador_usuario.empresa_id != user.empresa_id:
        raise PersonalError("El usuario autorizador no pertenece a esta empresa.")
    return autorizacion


def validate_autorizacion_tecnica_code(user, codigo, current_id=None):
    if not codigo:
        return
    query = PersonalAutorizacionTecnica.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(PersonalAutorizacionTecnica.id != current_id)
    if query.first():
        raise PersonalError("Ya existe una autorizacion tecnica con ese codigo en esta empresa.")


def _validate_authorization_evaluation(user, item, evaluacion_id):
    item.evaluacion_competencia_id = None
    if not evaluacion_id:
        return None
    evaluacion = get_evaluacion_competencia(user, evaluacion_id)
    if not evaluacion:
        raise PersonalError("La evaluacion de competencia no pertenece a esta empresa.")
    _validate_evaluacion_record(user, evaluacion)
    if evaluacion.personal_id != item.personal_id:
        raise PersonalError("La evaluacion de competencia no corresponde al personal autorizado.")
    if evaluacion.resultado not in {"COMPETENTE", "COMPETENTE_CON_OBSERVACIONES"}:
        raise PersonalError("La evaluacion de competencia no es compatible con una autorizacion.")
    item.evaluacion_competencia_id = evaluacion.id
    return evaluacion


def _apply_authorizer_data(user, item, data):
    item.autorizador_personal_id = None
    item.autorizador_usuario_id = None
    item.autorizador_externo_nombre = _clean(data.get("autorizador_externo_nombre"))
    item.autorizador_externo_entidad = _clean(data.get("autorizador_externo_entidad"))

    autorizador_personal_id = data.get("autorizador_personal_id")
    if autorizador_personal_id:
        with db.session.no_autoflush:
            autorizador = _validate_personal_record(user, autorizador_personal_id)
        item.autorizador_personal_id = autorizador.id
        item.autorizador_externo_nombre = None
        item.autorizador_externo_entidad = None

    autorizador_usuario_id = data.get("autorizador_usuario_id")
    if autorizador_usuario_id:
        selected_user = Usuario.query.filter_by(id=autorizador_usuario_id, empresa_id=user.empresa_id).first()
        if not selected_user:
            raise PersonalError("El usuario autorizador no pertenece a esta empresa.")
        item.autorizador_usuario_id = selected_user.id

    if not item.autorizador_personal_id and not item.autorizador_usuario_id and not item.autorizador_externo_nombre:
        raise PersonalError("Indica quien otorgo la autorizacion.")


def _apply_autorizacion_tecnica_data(user, item, data, personal_id=None, current_id=None):
    if item.estado == "REVOCADA":
        raise PersonalError("Una autorizacion revocada no puede editarse.")
    selected_personal_id = personal_id if personal_id is not None else (data.get("personal_id") or item.personal_id)
    personal = _validate_personal_record(user, selected_personal_id)
    item.empresa_id = user.empresa_id
    item.personal_id = personal.id
    item.codigo = _clean(data.get("codigo"), upper=True)
    item.tipo_autorizacion = _clean(data.get("tipo_autorizacion"), upper=True)
    item.actividad = _clean(data.get("actividad"))
    item.alcance = _clean(data.get("alcance"))
    item.descripcion = _clean(data.get("descripcion"))
    item.metodo_referencia = _clean(data.get("metodo_referencia"), upper=True)
    item.metodo_descripcion = _clean(data.get("metodo_descripcion"))
    item.fecha_autorizacion = _date_from_form(data.get("fecha_autorizacion"))
    item.fecha_inicio = _date_from_form(data.get("fecha_inicio"))
    item.fecha_fin = _date_from_form(data.get("fecha_fin"))
    item.estado = _clean(data.get("estado"), upper=True) or item.estado or "VIGENTE"
    item.fundamento = _clean(data.get("fundamento") or data.get("justificacion"))
    item.observaciones = _clean(data.get("observaciones"))

    if item.tipo_autorizacion not in TIPOS_AUTORIZACION_TECNICA:
        raise PersonalError("Tipo de autorizacion tecnica invalido.")
    if item.estado not in ESTADOS_AUTORIZACION_TECNICA:
        raise PersonalError("Estado de autorizacion invalido.")
    if not item.actividad:
        raise PersonalError("La actividad autorizada es obligatoria.")
    if not item.alcance:
        raise PersonalError("El alcance de la autorizacion es obligatorio.")
    if not item.fecha_autorizacion:
        raise PersonalError("La fecha de autorizacion es obligatoria.")
    if not item.fecha_inicio:
        raise PersonalError("La fecha de inicio es obligatoria.")
    if item.fecha_fin and item.fecha_fin < item.fecha_inicio:
        raise PersonalError("La fecha de fin no puede ser anterior a la fecha de inicio.")

    item.equipo_id = None
    equipo_id = data.get("equipo_id")
    if item.tipo_autorizacion == "EQUIPO":
        equipo = get_equipo(user, equipo_id)
        if not equipo:
            raise PersonalError("El equipo autorizado no pertenece a esta empresa.")
        item.equipo_id = equipo.id
    elif equipo_id:
        equipo = get_equipo(user, equipo_id)
        if not equipo:
            raise PersonalError("El equipo autorizado no pertenece a esta empresa.")
        item.equipo_id = equipo.id

    if item.tipo_autorizacion == "METODO" and not item.metodo_referencia:
        raise PersonalError("La referencia del metodo es obligatoria para autorizaciones de metodo.")
    if item.tipo_autorizacion != "METODO" and not data.get("metodo_referencia"):
        item.metodo_referencia = None
        item.metodo_descripcion = None

    evaluacion = _validate_authorization_evaluation(user, item, data.get("evaluacion_competencia_id"))
    if not evaluacion and not item.fundamento:
        raise PersonalError("El fundamento o justificacion es obligatorio cuando no se asocia una evaluacion.")

    _apply_authorizer_data(user, item, data)
    validate_autorizacion_tecnica_code(user, item.codigo, current_id)


def create_autorizacion_tecnica(user, personal_id, data):
    ensure_permission(user, PERM_GESTIONAR)
    item = PersonalAutorizacionTecnica(estado="VIGENTE")
    _apply_autorizacion_tecnica_data(user, item, data, personal_id=personal_id)
    db.session.add(item)
    return item


def update_autorizacion_tecnica(user, item, data):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_autorizacion_record(user, item)
    _apply_autorizacion_tecnica_data(user, item, data, current_id=item.id)
    return item


def autorizaciones_tecnicas_query(user, filters=None):
    filters = filters or {}
    query = PersonalAutorizacionTecnica.query.filter_by(empresa_id=user.empresa_id)
    if filters.get("persona_id"):
        query = query.filter(PersonalAutorizacionTecnica.personal_id == filters["persona_id"])
    if filters.get("tipo"):
        query = query.filter(PersonalAutorizacionTecnica.tipo_autorizacion == filters["tipo"])
    if filters.get("estado"):
        estado = filters["estado"]
        if estado == "VENCIDA":
            query = query.filter(
                PersonalAutorizacionTecnica.estado == "VIGENTE",
                PersonalAutorizacionTecnica.fecha_fin.isnot(None),
                PersonalAutorizacionTecnica.fecha_fin < date.today(),
            )
        else:
            query = query.filter(PersonalAutorizacionTecnica.estado == estado)
    if filters.get("equipo_id"):
        query = query.filter(PersonalAutorizacionTecnica.equipo_id == filters["equipo_id"])
    if filters.get("q"):
        like = f"%{filters['q']}%"
        query = query.join(Personal, Personal.id == PersonalAutorizacionTecnica.personal_id).filter(
            or_(
                PersonalAutorizacionTecnica.codigo.ilike(like),
                PersonalAutorizacionTecnica.actividad.ilike(like),
                PersonalAutorizacionTecnica.alcance.ilike(like),
                PersonalAutorizacionTecnica.metodo_referencia.ilike(like),
                Personal.nombres.ilike(like),
                Personal.apellidos.ilike(like),
                Personal.codigo.ilike(like),
            )
        )
    return query.order_by(PersonalAutorizacionTecnica.fecha_inicio.desc(), PersonalAutorizacionTecnica.id.desc())


def set_autorizacion_tecnica_estado(user, item, estado, motivo=None, fecha_estado=None):
    ensure_permission(user, PERM_GESTIONAR)
    _validate_autorizacion_record(user, item)
    estado = _clean(estado, upper=True)
    if estado not in ESTADOS_AUTORIZACION_TECNICA:
        raise PersonalError("Estado de autorizacion invalido.")
    if item.estado == "REVOCADA" and estado != "REVOCADA":
        raise PersonalError("Una autorizacion revocada no puede reactivarse.")
    if item.estado != "SUSPENDIDA" and estado == "VIGENTE":
        raise PersonalError("Solo una autorizacion suspendida puede reactivarse.")
    if estado in {"SUSPENDIDA", "REVOCADA"} and not _clean(motivo):
        raise PersonalError("El motivo del cambio de estado es obligatorio.")
    item.estado = estado
    item.motivo_estado = _clean(motivo)
    item.fecha_estado = _date_from_form(fecha_estado) or date.today()
    return item


def suspender_autorizacion_tecnica(user, item, motivo, fecha_estado=None):
    return set_autorizacion_tecnica_estado(user, item, "SUSPENDIDA", motivo, fecha_estado)


def reactivar_autorizacion_tecnica(user, item, motivo=None, fecha_estado=None):
    return set_autorizacion_tecnica_estado(user, item, "VIGENTE", motivo, fecha_estado)


def revocar_autorizacion_tecnica(user, item, motivo, fecha_estado=None):
    return set_autorizacion_tecnica_estado(user, item, "REVOCADA", motivo, fecha_estado)


def add_autorizacion_tecnica_evidencia(user, autorizacion, file_storage, data=None):
    ensure_permission(user, PERM_GESTIONAR)
    data = data or {}
    _validate_autorizacion_record(user, autorizacion)
    tipo_evidencia = _clean(data.get("tipo_evidencia"), upper=True) or "OTRO"
    if tipo_evidencia not in TIPOS_EVIDENCIA_AUTORIZACION_TECNICA:
        raise PersonalError("Tipo de evidencia de autorizacion invalido.")
    if not file_storage or not file_storage.filename:
        raise PersonalError("Selecciona un archivo de evidencia.")
    try:
        stored = store_personal_authorization_evidence_file(file_storage, autorizacion=autorizacion)
    except DocumentStorageError as exc:
        raise PersonalError(str(exc)) from exc
    evidencia = PersonalAutorizacionTecnicaEvidencia(
        empresa_id=user.empresa_id,
        autorizacion_id=autorizacion.id,
        tipo_evidencia=tipo_evidencia,
        archivo_nombre_original=stored.original_name,
        archivo_nombre_guardado=stored.stored_name,
        archivo_storage_path=stored.storage_path,
        archivo_mime=stored.mime_type,
        archivo_size=stored.size,
        archivo_sha256=stored.sha256,
        cargado_por_id=user.id,
        observaciones=_clean(data.get("observaciones")),
        activo=True,
    )
    db.session.add(evidencia)
    return evidencia


def set_autorizacion_tecnica_evidencia_active(user, evidencia, active):
    ensure_permission(user, PERM_GESTIONAR)
    if not evidencia or evidencia.empresa_id != user.empresa_id:
        raise PersonalError("La evidencia no pertenece a esta empresa.")
    _validate_autorizacion_record(user, evidencia.autorizacion)
    evidencia.activo = bool(active)
    return evidencia
