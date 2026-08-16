from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.equipos import Equipo, EquipoCalibracion, EquipoCalibracionDocumento, EquipoHistorial
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission


PERM_VER = "equipos.ver"
PERM_GESTIONAR = "equipos.editar"
PERM_VINCULAR_EVIDENCIA = "equipos.documentos.vincular"
PERM_DESVINCULAR_EVIDENCIA = "equipos.documentos.vincular"

VALID_TYPES = {"CALIBRACION", "VERIFICACION"}
PENDING_STATES = ("PROGRAMADO", "EN_PROCESO")
OPEN_STATES = ("PROGRAMADO", "EN_PROCESO")
VALID_CURRENCIES = {"USD", "EUR", "COP", "MXN", "PEN", "CLP"}


class EquipoCalibracionError(ValueError):
    pass


def _clean(value, upper=False):
    value = (value or "").strip() if isinstance(value, str) else value
    if isinstance(value, str) and upper:
        value = value.upper()
    return value or None


def _as_date(value, field_name):
    if isinstance(value, date):
        return value
    value = _clean(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EquipoCalibracionError(f"{field_name} debe tener formato AAAA-MM-DD.") from exc


def _require_permission(user, permission):
    if not user_has_permission(user, permission):
        raise EquipoCalibracionError("No tienes permisos para realizar esta accion.")


def _require_same_company(user, item, message):
    if not item or int(item.empresa_id) != int(user.empresa_id):
        raise EquipoCalibracionError(message)
    return item


def _get_equipo(user, equipo_id):
    return _require_same_company(
        user,
        Equipo.query.filter_by(id=equipo_id, empresa_id=user.empresa_id).first(),
        "El equipo seleccionado no pertenece a esta empresa.",
    )


def _get_calibracion(user, calibracion_id):
    return _require_same_company(
        user,
        EquipoCalibracion.query.filter_by(id=calibracion_id, empresa_id=user.empresa_id).first(),
        "La calibracion o verificacion no pertenece a esta empresa.",
    )


def _get_usuario_responsable(user, responsable_id):
    if not responsable_id:
        return None
    responsable = Usuario.query.filter_by(id=responsable_id, empresa_id=user.empresa_id, activo=True).first()
    if not responsable:
        raise EquipoCalibracionError("El responsable seleccionado no pertenece a esta empresa.")
    return responsable


def _ensure_equipo_habilitado(equipo):
    if (equipo.estado or "").lower() != "activo":
        raise EquipoCalibracionError("El equipo debe estar activo para gestionar calibraciones o verificaciones.")
    if equipo.estado_operativo == "RETIRADO":
        raise EquipoCalibracionError("No se pueden gestionar calibraciones o verificaciones de equipos retirados.")
    return equipo


def _record_event(user, equipo, tipo_evento, descripcion, estado_anterior=None, estado_nuevo=None):
    event = EquipoHistorial(
        empresa_id=equipo.empresa_id,
        equipo_id=equipo.id,
        tipo_evento=tipo_evento,
        descripcion=descripcion,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        usuario_id=getattr(user, "id", None),
    )
    db.session.add(event)
    return event


def _next_code(empresa_id, prefix="CAL"):
    like = f"{prefix}-%"
    max_code = (
        db.session.query(func.max(EquipoCalibracion.codigo))
        .filter(EquipoCalibracion.empresa_id == empresa_id, EquipoCalibracion.codigo.like(like))
        .scalar()
    )
    number = 0
    if max_code:
        suffix = max_code.rsplit("-", 1)[-1]
        if suffix.isdigit():
            number = int(suffix)
    return f"{prefix}-{number + 1:04d}"


def _validate_code(user, codigo):
    if EquipoCalibracion.query.filter_by(empresa_id=user.empresa_id, codigo=codigo).first():
        raise EquipoCalibracionError("Ya existe una calibracion o verificacion con ese codigo en esta empresa.")


def _add_months(value, months):
    month_index = value.month - 1 + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _event_prefix(calibracion):
    return "CALIBRACION" if calibracion.tipo_control == "CALIBRACION" else "VERIFICACION"


def _operation_label(calibracion):
    return "Calibracion" if calibracion.tipo_control == "CALIBRACION" else "Verificacion metrologica"


def programar_control(user, equipo_id, data):
    _require_permission(user, PERM_GESTIONAR)
    equipo = _ensure_equipo_habilitado(_get_equipo(user, equipo_id))
    tipo_control = _clean(data.get("tipo_control") or data.get("tipo"), upper=True)
    if tipo_control not in VALID_TYPES:
        raise EquipoCalibracionError("El tipo de control metrologico debe ser CALIBRACION o VERIFICACION.")
    fecha_planificada = _as_date(data.get("fecha_planificada") or data.get("fecha_calibracion"), "La fecha planificada")
    if not fecha_planificada:
        raise EquipoCalibracionError("La fecha planificada es obligatoria.")
    responsable = _get_usuario_responsable(user, data.get("responsable_id"))
    codigo = _clean(data.get("codigo"), upper=True) or _next_code(user.empresa_id, "CAL" if tipo_control == "CALIBRACION" else "VER")
    _validate_code(user, codigo)
    periodicidad = data.get("periodicidad_meses")
    periodicidad = int(periodicidad) if periodicidad not in ("", None) else None
    if periodicidad is not None and periodicidad <= 0:
        raise EquipoCalibracionError("La periodicidad debe ser mayor que cero.")
    control = EquipoCalibracion(
        empresa_id=user.empresa_id,
        equipo_id=equipo.id,
        codigo=codigo,
        tipo_control=tipo_control,
        estado="PROGRAMADO",
        fecha_planificada=fecha_planificada,
        periodicidad_meses=periodicidad,
        proveedor=_clean(data.get("proveedor")),
        responsable_id=responsable.id if responsable else None,
        certificado_numero=_clean(data.get("certificado_numero")),
        archivo_url=_clean(data.get("archivo_url")),
        observaciones=_clean(data.get("observaciones")),
    )
    db.session.add(control)
    db.session.flush()
    _record_event(user, equipo, f"{tipo_control}_PROGRAMADA", f"{_operation_label(control)} programada: {control.codigo}.")
    return control


def iniciar_control(user, calibracion_id, fecha_inicio=None):
    _require_permission(user, PERM_GESTIONAR)
    control = _get_calibracion(user, calibracion_id)
    if control.estado != "PROGRAMADO":
        raise EquipoCalibracionError("Solo se pueden iniciar controles metrologicos programados.")
    start_date = _as_date(fecha_inicio, "La fecha de inicio") or date.today()
    control.estado = "EN_PROCESO"
    control.fecha_inicio = control.fecha_inicio or start_date
    _record_event(user, control.equipo, f"{_event_prefix(control)}_INICIADA", f"{_operation_label(control)} iniciada: {control.codigo}.", "PROGRAMADO", "EN_PROCESO")
    return control


def completar_control(user, calibracion_id, data):
    _require_permission(user, PERM_GESTIONAR)
    control = _get_calibracion(user, calibracion_id)
    if control.estado != "EN_PROCESO":
        raise EquipoCalibracionError("Solo se pueden completar controles metrologicos en proceso.")
    completion_date = _as_date(data.get("fecha_finalizacion") or data.get("fecha_calibracion"), "La fecha de finalizacion")
    resultado = _clean(data.get("resultado"))
    costo = data.get("costo")
    moneda = _clean(data.get("moneda"), upper=True)
    periodicidad = data.get("periodicidad_meses")
    if not completion_date:
        raise EquipoCalibracionError("La fecha de finalizacion es obligatoria.")
    if control.fecha_inicio and completion_date < control.fecha_inicio:
        raise EquipoCalibracionError("La fecha de finalizacion no puede ser anterior al inicio.")
    if not resultado:
        raise EquipoCalibracionError("El resultado del control metrologico es obligatorio.")
    if costo in ("", None):
        costo = None
    else:
        costo = Decimal(str(costo))
        if costo < 0:
            raise EquipoCalibracionError("El costo no puede ser negativo.")
        if not moneda or moneda not in VALID_CURRENCIES:
            raise EquipoCalibracionError("La moneda es obligatoria y debe ser valida cuando existe costo.")
    if periodicidad not in ("", None):
        periodicidad = int(periodicidad)
        if periodicidad <= 0:
            raise EquipoCalibracionError("La periodicidad debe ser mayor que cero.")
        control.periodicidad_meses = periodicidad
    control.estado = "COMPLETADO"
    control.fecha_finalizacion = completion_date
    control.fecha_calibracion = completion_date
    control.resultado = resultado
    control.observaciones = _clean(data.get("observaciones") or data.get("trabajo_realizado")) or control.observaciones
    control.costo = costo
    control.moneda = moneda if costo is not None else None
    if control.periodicidad_meses:
        next_date = _add_months(completion_date, control.periodicidad_meses)
        if next_date <= completion_date:
            raise EquipoCalibracionError("La proxima fecha debe ser posterior a la fecha de finalizacion.")
        control.fecha_proxima = next_date
    _record_event(user, control.equipo, f"{_event_prefix(control)}_COMPLETADA", f"{_operation_label(control)} completada: {control.codigo}.", "EN_PROCESO", "COMPLETADO")
    return control


def cancelar_control(user, calibracion_id, motivo):
    _require_permission(user, PERM_GESTIONAR)
    control = _get_calibracion(user, calibracion_id)
    if control.estado not in OPEN_STATES:
        raise EquipoCalibracionError("Solo se pueden cancelar controles metrologicos programados o en proceso.")
    motivo = _clean(motivo)
    if not motivo or len(motivo) < 5:
        raise EquipoCalibracionError("El motivo de cancelacion es obligatorio.")
    previous = control.estado
    control.estado = "CANCELADO"
    control.cancelado_por_id = user.id
    control.motivo_cancelacion = motivo
    _record_event(user, control.equipo, f"{_event_prefix(control)}_CANCELADA", f"{_operation_label(control)} cancelada: {control.codigo}. Motivo: {motivo}", previous, "CANCELADO")
    return control


def esta_vencido(control, today=None):
    today = today or date.today()
    return control.estado in PENDING_STATES and control.fecha_planificada and control.fecha_planificada < today


def controles_pendientes(user, equipo_id=None):
    _require_permission(user, PERM_VER)
    query = EquipoCalibracion.query.filter(
        EquipoCalibracion.empresa_id == user.empresa_id,
        EquipoCalibracion.estado.in_(PENDING_STATES),
    )
    if equipo_id:
        _get_equipo(user, equipo_id)
        query = query.filter(EquipoCalibracion.equipo_id == equipo_id)
    return query.order_by(EquipoCalibracion.fecha_planificada.asc(), EquipoCalibracion.codigo.asc()).all()


def vincular_evidencia_documental(user, calibracion_id, documento_id, documento_version_id, tipo_evidencia="CERTIFICADO", observaciones=None):
    _require_permission(user, PERM_VINCULAR_EVIDENCIA)
    control = _get_calibracion(user, calibracion_id)
    if control.estado == "COMPLETADO":
        raise EquipoCalibracionError("No se pueden modificar evidencias de un control metrologico completado.")
    if control.estado == "CANCELADO":
        raise EquipoCalibracionError("No se pueden modificar evidencias de un control metrologico cancelado.")
    document = Documento.query.filter_by(id=documento_id, empresa_id=user.empresa_id).first()
    if not document:
        raise EquipoCalibracionError("El documento seleccionado no pertenece a esta empresa.")
    version = DocumentoVersion.query.filter_by(id=documento_version_id, empresa_id=user.empresa_id).first()
    if not version:
        raise EquipoCalibracionError("La version documental seleccionada no pertenece a esta empresa.")
    if version.documento_id != document.id:
        raise EquipoCalibracionError("La version documental no pertenece al documento indicado.")
    if EquipoCalibracionDocumento.query.filter_by(calibracion_id=control.id, documento_version_id=version.id).first():
        raise EquipoCalibracionError("Esa version documental ya esta vinculada al control metrologico.")
    evidence_type = _clean(tipo_evidencia) or "CERTIFICADO"
    evidence = EquipoCalibracionDocumento(
        empresa_id=user.empresa_id,
        calibracion_id=control.id,
        documento_id=document.id,
        documento_version_id=version.id,
        tipo_evidencia=evidence_type,
        observaciones=_clean(observaciones),
        vinculado_por_id=user.id,
    )
    db.session.add(evidence)
    db.session.flush()
    _record_event(user, control.equipo, "EVIDENCIA_CALIBRACION_VINCULADA", f"Evidencia vinculada a {control.codigo}: {document.codigo} v{version.version}.")
    return evidence


def desvincular_evidencia_documental(user, evidencia_id, motivo=None):
    _require_permission(user, PERM_DESVINCULAR_EVIDENCIA)
    evidence = _require_same_company(
        user,
        EquipoCalibracionDocumento.query.filter_by(id=evidencia_id, empresa_id=user.empresa_id).first(),
        "La evidencia no pertenece a esta empresa.",
    )
    control = evidence.calibracion
    if control.estado == "COMPLETADO":
        raise EquipoCalibracionError("No se pueden modificar evidencias de un control metrologico completado.")
    if control.estado == "CANCELADO":
        raise EquipoCalibracionError("No se pueden modificar evidencias de un control metrologico cancelado.")
    document_code = evidence.documento.codigo if evidence.documento else str(evidence.documento_id)
    version_label = evidence.documento_version.version if evidence.documento_version else str(evidence.documento_version_id)
    description = f"Evidencia desvinculada de {control.codigo}: {document_code} v{version_label}."
    description += f" Motivo: {_clean(motivo) or 'No especificado'}."
    _record_event(user, control.equipo, "EVIDENCIA_CALIBRACION_DESVINCULADA", description)
    db.session.delete(evidence)
    return True
