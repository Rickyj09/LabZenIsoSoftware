from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.equipos import (
    Equipo,
    EquipoHistorial,
    EquipoMantenimiento,
    EquipoMantenimientoDocumento,
    EquipoPlanMantenimiento,
)
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission


PERM_VER = "equipos.mantenimientos.ver"
PERM_CREAR_PLAN = "equipos.mantenimientos.planes.crear"
PERM_EDITAR_PLAN = "equipos.mantenimientos.planes.editar"
PERM_PROGRAMAR = "equipos.mantenimientos.programar"
PERM_CREAR_CORRECTIVO = "equipos.mantenimientos.correctivos.crear"
PERM_INICIAR = "equipos.mantenimientos.iniciar"
PERM_COMPLETAR = "equipos.mantenimientos.completar"
PERM_CANCELAR = "equipos.mantenimientos.cancelar"
PERM_VINCULAR_EVIDENCIA = "equipos.mantenimientos.evidencias.vincular"
PERM_DESVINCULAR_EVIDENCIA = "equipos.mantenimientos.evidencias.desvincular"

PENDING_STATES = ("PROGRAMADO", "EN_PROCESO")
OPEN_STATES = ("PROGRAMADO", "EN_PROCESO")
VALID_CURRENCIES = {"USD", "EUR", "COP", "MXN", "PEN", "CLP"}


class EquipoMantenimientoError(ValueError):
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
        raise EquipoMantenimientoError(f"{field_name} debe tener formato AAAA-MM-DD.") from exc


def _require_permission(user, permission):
    if not user_has_permission(user, permission):
        raise EquipoMantenimientoError("No tienes permisos para realizar esta accion.")


def _require_same_company(user, item, message):
    if not item or int(item.empresa_id) != int(user.empresa_id):
        raise EquipoMantenimientoError(message)
    return item


def _get_equipo(user, equipo_id):
    return _require_same_company(
        user,
        Equipo.query.filter_by(id=equipo_id, empresa_id=user.empresa_id).first(),
        "El equipo seleccionado no pertenece a esta empresa.",
    )


def _get_plan(user, plan_id):
    return _require_same_company(
        user,
        EquipoPlanMantenimiento.query.filter_by(id=plan_id, empresa_id=user.empresa_id).first(),
        "El plan de mantenimiento no pertenece a esta empresa.",
    )


def _get_mantenimiento(user, mantenimiento_id):
    return _require_same_company(
        user,
        EquipoMantenimiento.query.filter_by(id=mantenimiento_id, empresa_id=user.empresa_id).first(),
        "El mantenimiento no pertenece a esta empresa.",
    )


def _get_usuario_responsable(user, responsable_id):
    if not responsable_id:
        return None
    responsable = Usuario.query.filter_by(id=responsable_id, empresa_id=user.empresa_id, activo=True).first()
    if not responsable:
        raise EquipoMantenimientoError("El responsable seleccionado no pertenece a esta empresa.")
    return responsable


def _ensure_equipo_habilitado(equipo):
    if (equipo.estado or "").lower() != "activo":
        raise EquipoMantenimientoError("El equipo debe estar activo para gestionar mantenimientos.")
    if equipo.estado_operativo == "RETIRADO":
        raise EquipoMantenimientoError("No se pueden gestionar mantenimientos de equipos retirados.")
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


def _validate_plan_code(user, codigo, current_id=None):
    if not codigo:
        raise EquipoMantenimientoError("El codigo del plan es obligatorio.")
    query = EquipoPlanMantenimiento.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(EquipoPlanMantenimiento.id != current_id)
    if query.first():
        raise EquipoMantenimientoError("Ya existe un plan de mantenimiento con ese codigo en esta empresa.")


def _validate_maintenance_code(user, codigo):
    if EquipoMantenimiento.query.filter_by(empresa_id=user.empresa_id, codigo=codigo).first():
        raise EquipoMantenimientoError("Ya existe un mantenimiento con ese codigo en esta empresa.")


def _next_code(model, empresa_id, prefix):
    like = f"{prefix}-%"
    max_code = (
        db.session.query(func.max(model.codigo))
        .filter(model.empresa_id == empresa_id, model.codigo.like(like))
        .scalar()
    )
    number = 0
    if max_code:
        suffix = max_code.rsplit("-", 1)[-1]
        if suffix.isdigit():
            number = int(suffix)
    return f"{prefix}-{number + 1:04d}"


def _add_months(value, months):
    month_index = value.month - 1 + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def crear_plan_preventivo(user, data):
    _require_permission(user, PERM_CREAR_PLAN)
    equipo = _ensure_equipo_habilitado(_get_equipo(user, data.get("equipo_id")))
    responsable = _get_usuario_responsable(user, data.get("responsable_id")) if "responsable_id" in data else None
    codigo = _clean(data.get("codigo"), upper=True) or _next_code(EquipoPlanMantenimiento, user.empresa_id, "PM")
    _validate_plan_code(user, codigo)
    nombre = _clean(data.get("nombre"))
    periodicidad = int(data.get("periodicidad_meses") or 0)
    fecha_inicio = _as_date(data.get("fecha_inicio"), "La fecha de inicio")
    if not nombre:
        raise EquipoMantenimientoError("El nombre del plan es obligatorio.")
    if periodicidad <= 0:
        raise EquipoMantenimientoError("La periodicidad debe ser mayor que cero.")
    if not fecha_inicio:
        raise EquipoMantenimientoError("La fecha de inicio es obligatoria.")
    proxima_fecha = _as_date(data.get("proxima_fecha"), "La proxima fecha") or fecha_inicio
    if proxima_fecha < fecha_inicio:
        raise EquipoMantenimientoError("La proxima fecha no puede ser anterior a la fecha de inicio.")
    plan = EquipoPlanMantenimiento(
        empresa_id=user.empresa_id,
        equipo_id=equipo.id,
        codigo=codigo,
        nombre=nombre,
        descripcion=_clean(data.get("descripcion")),
        periodicidad_meses=periodicidad,
        fecha_inicio=fecha_inicio,
        proxima_fecha=proxima_fecha,
        responsable_id=responsable.id if responsable else None,
        proveedor=_clean(data.get("proveedor")),
        estado="ACTIVO",
    )
    db.session.add(plan)
    db.session.flush()
    _record_event(user, equipo, "PLAN_MANTENIMIENTO_CREADO", f"Plan de mantenimiento creado: {plan.codigo}.")
    return plan


def actualizar_plan_preventivo(user, plan_id, data):
    _require_permission(user, PERM_EDITAR_PLAN)
    plan = _get_plan(user, plan_id)
    if plan.estado != "ACTIVO":
        raise EquipoMantenimientoError("Solo se pueden modificar planes activos.")
    equipo = _ensure_equipo_habilitado(_get_equipo(user, data.get("equipo_id") or plan.equipo_id))
    responsable = _get_usuario_responsable(user, data.get("responsable_id"))
    previous = f"{plan.codigo}|{plan.nombre}|{plan.periodicidad_meses}|{plan.proxima_fecha}|{plan.estado}"
    codigo = _clean(data.get("codigo"), upper=True) or plan.codigo
    _validate_plan_code(user, codigo, current_id=plan.id)
    nombre = _clean(data.get("nombre")) or plan.nombre
    periodicidad = int(data.get("periodicidad_meses") or plan.periodicidad_meses or 0)
    fecha_inicio = _as_date(data.get("fecha_inicio"), "La fecha de inicio") or plan.fecha_inicio
    proxima_fecha = _as_date(data.get("proxima_fecha"), "La proxima fecha") or plan.proxima_fecha or fecha_inicio
    if periodicidad <= 0:
        raise EquipoMantenimientoError("La periodicidad debe ser mayor que cero.")
    if proxima_fecha < fecha_inicio:
        raise EquipoMantenimientoError("La proxima fecha no puede ser anterior a la fecha de inicio.")
    plan.equipo_id = equipo.id
    plan.codigo = codigo
    plan.nombre = nombre
    plan.descripcion = _clean(data.get("descripcion")) if "descripcion" in data else plan.descripcion
    plan.periodicidad_meses = periodicidad
    plan.fecha_inicio = fecha_inicio
    plan.proxima_fecha = proxima_fecha
    if "responsable_id" in data:
        plan.responsable_id = responsable.id if responsable else None
    plan.proveedor = _clean(data.get("proveedor")) if "proveedor" in data else plan.proveedor
    current = f"{plan.codigo}|{plan.nombre}|{plan.periodicidad_meses}|{plan.proxima_fecha}|{plan.estado}"
    _record_event(user, equipo, "PLAN_MANTENIMIENTO_ACTUALIZADO", f"Plan de mantenimiento actualizado: {plan.codigo}.", previous, current)
    return plan


def inactivar_plan_preventivo(user, plan_id, motivo=None):
    _require_permission(user, PERM_EDITAR_PLAN)
    plan = _get_plan(user, plan_id)
    if plan.estado != "ACTIVO":
        raise EquipoMantenimientoError("El plan ya se encuentra inactivo.")
    previous = plan.estado
    plan.estado = "INACTIVO"
    _record_event(user, plan.equipo, "PLAN_MANTENIMIENTO_INACTIVADO", f"Plan de mantenimiento inactivado: {plan.codigo}. {(_clean(motivo) or '').strip()}", previous, plan.estado)
    return plan


def programar_mantenimiento_desde_plan(user, plan_id, fecha_planificada=None, observaciones=None):
    _require_permission(user, PERM_PROGRAMAR)
    plan = _get_plan(user, plan_id)
    if plan.estado != "ACTIVO":
        raise EquipoMantenimientoError("No se pueden programar mantenimientos desde un plan inactivo.")
    equipo = _ensure_equipo_habilitado(plan.equipo)
    planned_date = _as_date(fecha_planificada, "La fecha planificada") or plan.proxima_fecha
    if not planned_date:
        raise EquipoMantenimientoError("La fecha planificada es obligatoria.")
    duplicate = EquipoMantenimiento.query.filter(
        EquipoMantenimiento.empresa_id == user.empresa_id,
        EquipoMantenimiento.plan_id == plan.id,
        EquipoMantenimiento.fecha_planificada == planned_date,
        EquipoMantenimiento.estado.in_(OPEN_STATES),
    ).first()
    if duplicate:
        raise EquipoMantenimientoError("Ya existe una orden abierta para ese plan y fecha.")
    codigo = _next_code(EquipoMantenimiento, user.empresa_id, "MANT")
    _validate_maintenance_code(user, codigo)
    maintenance = EquipoMantenimiento(
        empresa_id=user.empresa_id,
        equipo_id=equipo.id,
        plan_id=plan.id,
        codigo=codigo,
        tipo_mantenimiento="PREVENTIVO",
        estado="PROGRAMADO",
        fecha_planificada=planned_date,
        descripcion_trabajo=plan.descripcion,
        responsable_id=plan.responsable_id,
        proveedor=plan.proveedor,
        observaciones=_clean(observaciones),
    )
    db.session.add(maintenance)
    db.session.flush()
    _record_event(user, equipo, "MANTENIMIENTO_PROGRAMADO", f"Mantenimiento preventivo programado: {maintenance.codigo}.")
    return maintenance


def crear_mantenimiento_correctivo(user, equipo_id, data):
    _require_permission(user, PERM_CREAR_CORRECTIVO)
    equipo = _ensure_equipo_habilitado(_get_equipo(user, equipo_id))
    responsable = _get_usuario_responsable(user, data.get("responsable_id"))
    descripcion = _clean(data.get("descripcion_trabajo") or data.get("descripcion") or data.get("problema"))
    fecha_planificada = _as_date(data.get("fecha_planificada"), "La fecha planificada")
    if not descripcion:
        raise EquipoMantenimientoError("La descripcion del trabajo correctivo es obligatoria.")
    if not fecha_planificada:
        raise EquipoMantenimientoError("La fecha planificada es obligatoria.")
    codigo = _clean(data.get("codigo"), upper=True) or _next_code(EquipoMantenimiento, user.empresa_id, "MANT")
    _validate_maintenance_code(user, codigo)
    maintenance = EquipoMantenimiento(
        empresa_id=user.empresa_id,
        equipo_id=equipo.id,
        codigo=codigo,
        tipo_mantenimiento="CORRECTIVO",
        estado="PROGRAMADO",
        fecha_planificada=fecha_planificada,
        descripcion_trabajo=descripcion,
        responsable_id=responsable.id if responsable else None,
        proveedor=_clean(data.get("proveedor")),
        observaciones=_clean(data.get("observaciones")),
    )
    db.session.add(maintenance)
    db.session.flush()
    _record_event(user, equipo, "MANTENIMIENTO_CORRECTIVO_CREADO", f"Mantenimiento correctivo creado: {maintenance.codigo}.")
    return maintenance


def iniciar_mantenimiento(user, mantenimiento_id, fecha_inicio=None):
    _require_permission(user, PERM_INICIAR)
    maintenance = _get_mantenimiento(user, mantenimiento_id)
    if maintenance.estado != "PROGRAMADO":
        raise EquipoMantenimientoError("Solo se pueden iniciar mantenimientos programados.")
    start_date = _as_date(fecha_inicio, "La fecha de inicio") or date.today()
    maintenance.estado = "EN_PROCESO"
    maintenance.fecha_inicio = maintenance.fecha_inicio or start_date
    _record_event(user, maintenance.equipo, "MANTENIMIENTO_INICIADO", f"Mantenimiento iniciado: {maintenance.codigo}.", "PROGRAMADO", "EN_PROCESO")
    return maintenance


def completar_mantenimiento(user, mantenimiento_id, data):
    _require_permission(user, PERM_COMPLETAR)
    maintenance = _get_mantenimiento(user, mantenimiento_id)
    if maintenance.estado != "EN_PROCESO":
        raise EquipoMantenimientoError("Solo se pueden completar mantenimientos en proceso.")
    completion_date = _as_date(data.get("fecha_finalizacion"), "La fecha de finalizacion")
    descripcion = _clean(data.get("descripcion_trabajo") or data.get("trabajo_realizado"))
    resultado = _clean(data.get("resultado"))
    costo = data.get("costo")
    moneda = _clean(data.get("moneda"), upper=True)
    if not completion_date:
        raise EquipoMantenimientoError("La fecha de finalizacion es obligatoria.")
    if maintenance.fecha_inicio and completion_date < maintenance.fecha_inicio:
        raise EquipoMantenimientoError("La fecha de finalizacion no puede ser anterior al inicio.")
    if not descripcion:
        raise EquipoMantenimientoError("La descripcion del trabajo realizado es obligatoria.")
    if not resultado:
        raise EquipoMantenimientoError("El resultado del mantenimiento es obligatorio.")
    if costo in ("", None):
        costo = None
    else:
        costo = Decimal(str(costo))
        if costo < 0:
            raise EquipoMantenimientoError("El costo no puede ser negativo.")
        if not moneda or moneda not in VALID_CURRENCIES:
            raise EquipoMantenimientoError("La moneda es obligatoria y debe ser valida cuando existe costo.")
    maintenance.estado = "COMPLETADO"
    maintenance.fecha_finalizacion = completion_date
    maintenance.fecha_mantenimiento = completion_date
    maintenance.descripcion_trabajo = descripcion
    maintenance.resultado = resultado
    maintenance.costo = costo
    maintenance.moneda = moneda if costo is not None else None
    if maintenance.tipo_mantenimiento == "PREVENTIVO" and maintenance.plan and maintenance.plan.estado == "ACTIVO":
        next_date = _add_months(completion_date, maintenance.plan.periodicidad_meses)
        maintenance.plan.proxima_fecha = next_date
        maintenance.fecha_proxima = next_date
    _record_event(user, maintenance.equipo, "MANTENIMIENTO_COMPLETADO", f"Mantenimiento completado: {maintenance.codigo}.", "EN_PROCESO", "COMPLETADO")
    return maintenance


def cancelar_mantenimiento(user, mantenimiento_id, motivo):
    _require_permission(user, PERM_CANCELAR)
    maintenance = _get_mantenimiento(user, mantenimiento_id)
    if maintenance.estado not in OPEN_STATES:
        raise EquipoMantenimientoError("Solo se pueden cancelar mantenimientos programados o en proceso.")
    motivo = _clean(motivo)
    if not motivo or len(motivo) < 5:
        raise EquipoMantenimientoError("El motivo de cancelacion es obligatorio.")
    previous = maintenance.estado
    maintenance.estado = "CANCELADO"
    maintenance.cancelado_por_id = user.id
    maintenance.motivo_cancelacion = motivo
    _record_event(user, maintenance.equipo, "MANTENIMIENTO_CANCELADO", f"Mantenimiento cancelado: {maintenance.codigo}. Motivo: {motivo}", previous, "CANCELADO")
    return maintenance


def esta_vencido(mantenimiento, today=None):
    today = today or date.today()
    return mantenimiento.estado in PENDING_STATES and mantenimiento.fecha_planificada and mantenimiento.fecha_planificada < today


def mantenimientos_pendientes(user, equipo_id=None):
    _require_permission(user, PERM_VER)
    query = EquipoMantenimiento.query.filter(
        EquipoMantenimiento.empresa_id == user.empresa_id,
        EquipoMantenimiento.estado.in_(PENDING_STATES),
    )
    if equipo_id:
        _get_equipo(user, equipo_id)
        query = query.filter(EquipoMantenimiento.equipo_id == equipo_id)
    return query.order_by(EquipoMantenimiento.fecha_planificada.asc(), EquipoMantenimiento.codigo.asc()).all()


def mantenimientos_vencidos(user, today=None, equipo_id=None):
    _require_permission(user, PERM_VER)
    today = today or date.today()
    query = EquipoMantenimiento.query.filter(
        EquipoMantenimiento.empresa_id == user.empresa_id,
        EquipoMantenimiento.estado.in_(PENDING_STATES),
        EquipoMantenimiento.fecha_planificada < today,
    )
    if equipo_id:
        _get_equipo(user, equipo_id)
        query = query.filter(EquipoMantenimiento.equipo_id == equipo_id)
    return query.order_by(EquipoMantenimiento.fecha_planificada.asc(), EquipoMantenimiento.codigo.asc()).all()


def mantenimientos_proximos(user, today=None, days=30, equipo_id=None):
    _require_permission(user, PERM_VER)
    today = today or date.today()
    limit = today.toordinal() + int(days)
    end_date = date.fromordinal(limit)
    query = EquipoMantenimiento.query.filter(
        EquipoMantenimiento.empresa_id == user.empresa_id,
        EquipoMantenimiento.estado.in_(PENDING_STATES),
        EquipoMantenimiento.fecha_planificada >= today,
        EquipoMantenimiento.fecha_planificada <= end_date,
    )
    if equipo_id:
        _get_equipo(user, equipo_id)
        query = query.filter(EquipoMantenimiento.equipo_id == equipo_id)
    return query.order_by(EquipoMantenimiento.fecha_planificada.asc(), EquipoMantenimiento.codigo.asc()).all()


def vincular_evidencia_documental(user, mantenimiento_id, documento_id, documento_version_id, tipo_evidencia, observaciones=None):
    _require_permission(user, PERM_VINCULAR_EVIDENCIA)
    maintenance = _get_mantenimiento(user, mantenimiento_id)
    if maintenance.estado == "CANCELADO":
        raise EquipoMantenimientoError("No se pueden vincular evidencias a mantenimientos cancelados.")
    document = Documento.query.filter_by(id=documento_id, empresa_id=user.empresa_id).first()
    if not document:
        raise EquipoMantenimientoError("El documento seleccionado no pertenece a esta empresa.")
    version = DocumentoVersion.query.filter_by(id=documento_version_id, empresa_id=user.empresa_id).first()
    if not version:
        raise EquipoMantenimientoError("La version documental seleccionada no pertenece a esta empresa.")
    if version.documento_id != document.id:
        raise EquipoMantenimientoError("La version documental no pertenece al documento indicado.")
    if EquipoMantenimientoDocumento.query.filter_by(mantenimiento_id=maintenance.id, documento_version_id=version.id).first():
        raise EquipoMantenimientoError("Esa version documental ya esta vinculada al mantenimiento.")
    evidence_type = _clean(tipo_evidencia)
    if not evidence_type:
        raise EquipoMantenimientoError("El tipo de evidencia es obligatorio.")
    evidence = EquipoMantenimientoDocumento(
        empresa_id=user.empresa_id,
        mantenimiento_id=maintenance.id,
        documento_id=document.id,
        documento_version_id=version.id,
        tipo_evidencia=evidence_type,
        observaciones=_clean(observaciones),
        vinculado_por_id=user.id,
    )
    db.session.add(evidence)
    db.session.flush()
    _record_event(user, maintenance.equipo, "EVIDENCIA_MANTENIMIENTO_VINCULADA", f"Evidencia vinculada a {maintenance.codigo}: {document.codigo} v{version.version}.")
    return evidence


def desvincular_evidencia_documental(user, evidencia_id, motivo=None):
    _require_permission(user, PERM_DESVINCULAR_EVIDENCIA)
    evidence = _require_same_company(
        user,
        EquipoMantenimientoDocumento.query.filter_by(id=evidencia_id, empresa_id=user.empresa_id).first(),
        "La evidencia no pertenece a esta empresa.",
    )
    maintenance = evidence.mantenimiento
    document_code = evidence.documento.codigo if evidence.documento else str(evidence.documento_id)
    version_label = evidence.documento_version.version if evidence.documento_version else str(evidence.documento_version_id)
    description = f"Evidencia desvinculada de {maintenance.codigo}: {document_code} v{version_label}."
    if maintenance.estado == "COMPLETADO":
        description += f" Motivo: {_clean(motivo) or 'No especificado'}."
    _record_event(user, maintenance.equipo, "EVIDENCIA_MANTENIMIENTO_DESVINCULADA", description)
    db.session.delete(evidence)
    return True
