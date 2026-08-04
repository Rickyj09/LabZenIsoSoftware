from datetime import date

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.equipos import (
    AreaAmbiente,
    CRITICIDADES_EQUIPO,
    Equipo,
    EquipoDocumento,
    EquipoHistorial,
    ESTADOS_OPERATIVOS_EQUIPO,
    Instalacion,
)
from app.security.permissions import user_has_permission


class EquipamientoError(ValueError):
    pass


def _split_legacy_location(value):
    value = _clean(value)
    if not value:
        return ""
    parts = value.split(":", 2)
    if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
        return parts[2] or ""
    return value


def equipo_location_label(equipo, instalacion=None, area=None, ubicacion=None):
    instalacion = instalacion if instalacion is not None else getattr(equipo, "instalacion", None)
    area = area if area is not None else getattr(equipo, "area_ambiente", None)
    if ubicacion is None:
        ubicacion = getattr(equipo, "ubicacion_especifica", None) or getattr(equipo, "ubicacion", None)
    parts = [
        getattr(instalacion, "nombre", None),
        getattr(area, "nombre", None),
        ubicacion,
    ]
    return " / ".join(part for part in (_clean(item) for item in parts) if part)


def equipo_history_change_labels(event):
    previous = _split_legacy_location(getattr(event, "estado_anterior", None))
    current = _split_legacy_location(getattr(event, "estado_nuevo", None))
    return previous, current


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
        raise EquipamientoError("Formato de fecha invalido. Usa AAAA-MM-DD.") from exc


def ensure_permission(user, permission_code):
    if not user_has_permission(user, permission_code):
        raise EquipamientoError("No tienes permisos para realizar esta accion.")


def get_instalacion(user, instalacion_id):
    return Instalacion.query.filter_by(id=instalacion_id, empresa_id=user.empresa_id).first()


def get_area(user, area_id):
    return AreaAmbiente.query.filter_by(id=area_id, empresa_id=user.empresa_id).first()


def get_equipo(user, equipo_id):
    return Equipo.query.filter_by(id=equipo_id, empresa_id=user.empresa_id).first()


def active_instalaciones(user):
    return (
        Instalacion.query
        .filter_by(empresa_id=user.empresa_id, estado="activo")
        .order_by(Instalacion.codigo.asc())
        .all()
    )


def active_areas(user, instalacion_id=None):
    query = AreaAmbiente.query.filter_by(empresa_id=user.empresa_id, estado="activo")
    if instalacion_id:
        query = query.filter_by(instalacion_id=instalacion_id)
    return query.order_by(AreaAmbiente.codigo.asc()).all()


def validate_instalacion_code(user, codigo, current_id=None):
    if not codigo:
        raise EquipamientoError("El codigo es obligatorio.")
    query = Instalacion.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(Instalacion.id != current_id)
    if query.first():
        raise EquipamientoError("Ya existe una instalacion con ese codigo en esta empresa.")


def create_instalacion(user, data):
    ensure_permission(user, "instalaciones.crear")
    codigo = _clean(data.get("codigo"), upper=True)
    nombre = _clean(data.get("nombre"))
    validate_instalacion_code(user, codigo)
    if not nombre:
        raise EquipamientoError("El nombre de la instalacion es obligatorio.")
    item = Instalacion(
        empresa_id=user.empresa_id,
        codigo=codigo,
        nombre=nombre,
        descripcion=_clean(data.get("descripcion")),
        direccion=_clean(data.get("direccion")),
        responsable=_clean(data.get("responsable")),
        estado=_clean(data.get("estado")) or "activo",
    )
    db.session.add(item)
    return item


def update_instalacion(user, item, data):
    ensure_permission(user, "instalaciones.editar")
    codigo = _clean(data.get("codigo"), upper=True)
    nombre = _clean(data.get("nombre"))
    validate_instalacion_code(user, codigo, current_id=item.id)
    if not nombre:
        raise EquipamientoError("El nombre de la instalacion es obligatorio.")
    item.codigo = codigo
    item.nombre = nombre
    item.descripcion = _clean(data.get("descripcion"))
    item.direccion = _clean(data.get("direccion"))
    item.responsable = _clean(data.get("responsable"))
    item.estado = _clean(data.get("estado")) or "activo"
    return item


def validate_area_code(user, codigo, current_id=None):
    if not codigo:
        raise EquipamientoError("El codigo es obligatorio.")
    query = AreaAmbiente.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(AreaAmbiente.id != current_id)
    if query.first():
        raise EquipamientoError("Ya existe un area o ambiente con ese codigo en esta empresa.")


def _validate_area_instalacion(user, instalacion_id):
    instalacion = get_instalacion(user, instalacion_id)
    if not instalacion:
        raise EquipamientoError("La instalacion seleccionada no pertenece a esta empresa.")
    return instalacion


def create_area(user, data):
    ensure_permission(user, "areas.crear")
    codigo = _clean(data.get("codigo"), upper=True)
    nombre = _clean(data.get("nombre"))
    validate_area_code(user, codigo)
    if not nombre:
        raise EquipamientoError("El nombre del area o ambiente es obligatorio.")
    instalacion = _validate_area_instalacion(user, data.get("instalacion_id"))
    item = AreaAmbiente(
        empresa_id=user.empresa_id,
        instalacion_id=instalacion.id,
        codigo=codigo,
        nombre=nombre,
        descripcion=_clean(data.get("descripcion")),
        tipo=_clean(data.get("tipo")),
        ubicacion_interna=_clean(data.get("ubicacion_interna")),
        responsable=_clean(data.get("responsable")),
        requiere_control_ambiental=_bool_from_form(data.get("requiere_control_ambiental")),
        estado=_clean(data.get("estado")) or "activo",
    )
    db.session.add(item)
    return item


def update_area(user, item, data):
    ensure_permission(user, "areas.editar")
    codigo = _clean(data.get("codigo"), upper=True)
    nombre = _clean(data.get("nombre"))
    validate_area_code(user, codigo, current_id=item.id)
    if not nombre:
        raise EquipamientoError("El nombre del area o ambiente es obligatorio.")
    instalacion = _validate_area_instalacion(user, data.get("instalacion_id"))
    item.instalacion_id = instalacion.id
    item.codigo = codigo
    item.nombre = nombre
    item.descripcion = _clean(data.get("descripcion"))
    item.tipo = _clean(data.get("tipo"))
    item.ubicacion_interna = _clean(data.get("ubicacion_interna"))
    item.responsable = _clean(data.get("responsable"))
    item.requiere_control_ambiental = _bool_from_form(data.get("requiere_control_ambiental"))
    item.estado = _clean(data.get("estado")) or "activo"
    return item


def validate_equipo_code(user, codigo, current_id=None):
    if not codigo:
        raise EquipamientoError("El codigo interno es obligatorio.")
    query = Equipo.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(Equipo.id != current_id)
    if query.first():
        raise EquipamientoError("Ya existe un equipo con ese codigo en esta empresa.")


def validate_equipo_location(user, instalacion_id, area_id=None):
    instalacion = _validate_area_instalacion(user, instalacion_id)
    area = None
    if area_id:
        area = get_area(user, area_id)
        if not area:
            raise EquipamientoError("El area seleccionada no pertenece a esta empresa.")
        if area.instalacion_id != instalacion.id:
            raise EquipamientoError("El area seleccionada no pertenece a la instalacion indicada.")
    return instalacion, area


def record_equipo_event(user, equipo, tipo_evento, descripcion=None, estado_anterior=None, estado_nuevo=None):
    event = EquipoHistorial(
        empresa_id=equipo.empresa_id,
        equipo_id=equipo.id,
        tipo_evento=tipo_evento,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        descripcion=descripcion,
        usuario_id=getattr(user, "id", None),
    )
    db.session.add(event)
    return event


def _apply_equipo_data(item, data):
    item.codigo = _clean(data.get("codigo"), upper=True)
    item.nombre = _clean(data.get("nombre"))
    item.tipo = _clean(data.get("tipo"))
    item.marca = _clean(data.get("marca"))
    item.modelo = _clean(data.get("modelo"))
    item.serie = _clean(data.get("serie"))
    item.fabricante = _clean(data.get("fabricante"))
    item.ubicacion = _clean(data.get("ubicacion"))
    item.ubicacion_especifica = _clean(data.get("ubicacion_especifica"))
    item.responsable = _clean(data.get("responsable"))
    item.estado = _clean(data.get("estado")) or "activo"
    item.estado_operativo = _clean(data.get("estado_operativo"), upper=True) or "OPERATIVO"
    item.criticidad = _clean(data.get("criticidad"), upper=True)
    item.requiere_calibracion = _bool_from_form(data.get("requiere_calibracion"))
    item.requiere_mantenimiento = _bool_from_form(data.get("requiere_mantenimiento"))
    item.observaciones = _clean(data.get("observaciones"))
    item.fecha_adquisicion = _date_from_form(data.get("fecha_adquisicion"))
    item.fecha_puesta_servicio = _date_from_form(data.get("fecha_puesta_servicio"))


def _validate_equipo_required(item):
    if not item.codigo or not item.nombre:
        raise EquipamientoError("Codigo interno y nombre del equipo son obligatorios.")
    if item.estado_operativo not in ESTADOS_OPERATIVOS_EQUIPO:
        raise EquipamientoError("Estado operativo invalido.")
    if item.criticidad and item.criticidad not in CRITICIDADES_EQUIPO:
        raise EquipamientoError("Criticidad invalida.")


def create_equipo(user, data):
    ensure_permission(user, "equipos.crear")
    codigo = _clean(data.get("codigo"), upper=True)
    validate_equipo_code(user, codigo)
    instalacion, area = validate_equipo_location(user, data.get("instalacion_id"), data.get("area_ambiente_id"))
    item = Equipo(empresa_id=user.empresa_id, instalacion_id=instalacion.id, area_ambiente_id=area.id if area else None)
    _apply_equipo_data(item, data)
    _validate_equipo_required(item)
    db.session.add(item)
    db.session.flush()
    record_equipo_event(user, item, "CREACION", "Equipo creado.")
    return item


def update_equipo(user, item, data):
    ensure_permission(user, "equipos.editar")
    previous_location = equipo_location_label(item)
    previous_responsible = item.responsable or ""
    previous_state = item.estado_operativo
    codigo = _clean(data.get("codigo"), upper=True)
    validate_equipo_code(user, codigo, current_id=item.id)
    instalacion, area = validate_equipo_location(user, data.get("instalacion_id"), data.get("area_ambiente_id"))
    item.instalacion_id = instalacion.id
    item.area_ambiente_id = area.id if area else None
    _apply_equipo_data(item, data)
    _validate_equipo_required(item)
    record_equipo_event(user, item, "ACTUALIZACION", "Datos maestros actualizados.")
    new_location = equipo_location_label(item, instalacion=instalacion, area=area)
    if new_location != previous_location:
        record_equipo_event(user, item, "CAMBIO_UBICACION", "Ubicacion del equipo actualizada.", previous_location, new_location)
    if (item.responsable or "") != previous_responsible:
        record_equipo_event(user, item, "CAMBIO_RESPONSABLE", "Responsable o custodio actualizado.", previous_responsible, item.responsable)
    if item.estado_operativo != previous_state:
        event_type = "RETIRO" if item.estado_operativo == "RETIRADO" else "REACTIVACION" if previous_state == "RETIRADO" else "CAMBIO_ESTADO_OPERATIVO"
        record_equipo_event(user, item, event_type, "Estado operativo actualizado.", previous_state, item.estado_operativo)
    return item


def change_equipo_status(user, item, estado_operativo, descripcion=None):
    ensure_permission(user, "equipos.cambiar_estado")
    estado_operativo = _clean(estado_operativo, upper=True)
    if estado_operativo not in ESTADOS_OPERATIVOS_EQUIPO:
        raise EquipamientoError("Estado operativo invalido.")
    previous = item.estado_operativo
    item.estado_operativo = estado_operativo
    event_type = "RETIRO" if estado_operativo == "RETIRADO" else "REACTIVACION" if previous == "RETIRADO" else "CAMBIO_ESTADO_OPERATIVO"
    record_equipo_event(user, item, event_type, descripcion or "Estado operativo actualizado.", previous, estado_operativo)
    return item


def link_document_version(user, equipo, documento_version_id, tipo_documento, observaciones=None):
    ensure_permission(user, "equipos.documentos.vincular")
    version = DocumentoVersion.query.filter_by(id=documento_version_id, empresa_id=user.empresa_id).first()
    if not version:
        raise EquipamientoError("La version documental seleccionada no pertenece a esta empresa.")
    document = Documento.query.filter_by(id=version.documento_id, empresa_id=user.empresa_id).first()
    if not document:
        raise EquipamientoError("El documento seleccionado no pertenece a esta empresa.")
    existing = EquipoDocumento.query.filter_by(equipo_id=equipo.id, documento_version_id=version.id).first()
    if existing:
        raise EquipamientoError("Esa version documental ya esta vinculada al equipo.")
    link = EquipoDocumento(
        empresa_id=user.empresa_id,
        equipo_id=equipo.id,
        documento_id=document.id,
        documento_version_id=version.id,
        tipo_documento=_clean(tipo_documento) or document.tipo_documento,
        nombre=document.titulo,
        version=version.version,
        fecha_documento=version.fecha_version,
        vinculado_por_id=user.id,
        observaciones=_clean(observaciones),
    )
    db.session.add(link)
    record_equipo_event(user, equipo, "VINCULO_DOCUMENTO", f"Documento vinculado: {document.codigo} v{version.version}.")
    return link
