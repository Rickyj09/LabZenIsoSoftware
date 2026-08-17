from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.equipos import (
    AreaAmbiente,
    AreaCondicionAmbiental,
    AreaHistorialAmbiental,
    AreaMedicionAmbiental,
)
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission


PERM_VER = "equipos.ver"
PERM_GESTIONAR = "equipos.editar"

ESTADO_CONFORME = "CONFORME"
ESTADO_FUERA_DE_LIMITE = "FUERA_DE_LIMITE"


class CondicionAmbientalError(ValueError):
    pass


def _clean(value, upper=False):
    value = (value or "").strip() if isinstance(value, str) else value
    if isinstance(value, str) and upper:
        value = value.upper()
    return value or None


def _as_decimal(value, field_name, required=False):
    if value in ("", None):
        if required:
            raise CondicionAmbientalError(f"{field_name} es obligatorio.")
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CondicionAmbientalError(f"{field_name} debe ser numerico.") from exc


def _as_datetime(value):
    if isinstance(value, datetime):
        measurement_time = value
    else:
        value = _clean(value)
        if not value:
            return datetime.now(timezone.utc)
        try:
            measurement_time = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CondicionAmbientalError("La fecha y hora de medicion debe tener formato ISO.") from exc
    if measurement_time.tzinfo is None:
        return measurement_time.replace(tzinfo=timezone.utc)
    return measurement_time


def _require_permission(user, permission):
    if not user_has_permission(user, permission):
        raise CondicionAmbientalError("No tienes permisos para realizar esta accion.")


def _require_same_company(user, item, message):
    if not item or int(item.empresa_id) != int(user.empresa_id):
        raise CondicionAmbientalError(message)
    return item


def _get_area(user, area_ambiente_id):
    return _require_same_company(
        user,
        AreaAmbiente.query.filter_by(id=area_ambiente_id, empresa_id=user.empresa_id).first(),
        "El area o ambiente seleccionado no pertenece a esta empresa.",
    )


def _get_condicion(user, condicion_id):
    return _require_same_company(
        user,
        AreaCondicionAmbiental.query.filter_by(id=condicion_id, empresa_id=user.empresa_id).first(),
        "La condicion ambiental no pertenece a esta empresa.",
    )


def _get_usuario(user, usuario_id):
    usuario = Usuario.query.filter_by(id=usuario_id, empresa_id=user.empresa_id, activo=True).first()
    if not usuario:
        raise CondicionAmbientalError("El usuario que registra la medicion no pertenece a esta empresa.")
    return usuario


def _ensure_area_habilitada(area):
    if (area.estado or "").lower() != "activo":
        raise CondicionAmbientalError("El area o ambiente debe estar activo para controlar condiciones ambientales.")
    if not area.requiere_control_ambiental:
        raise CondicionAmbientalError("El area o ambiente no tiene control ambiental habilitado.")
    return area


def _validate_limites(limite_minimo, limite_maximo):
    if limite_minimo is None and limite_maximo is None:
        raise CondicionAmbientalError("Debe configurarse al menos un limite ambiental.")
    if limite_minimo is not None and limite_maximo is not None and limite_minimo > limite_maximo:
        raise CondicionAmbientalError("El limite minimo no puede ser mayor que el limite maximo.")


def _condition_snapshot(condicion):
    return {
        "codigo": condicion.codigo,
        "nombre": condicion.nombre,
        "unidad": condicion.unidad,
        "limite_minimo": str(condicion.limite_minimo) if condicion.limite_minimo is not None else None,
        "limite_maximo": str(condicion.limite_maximo) if condicion.limite_maximo is not None else None,
        "valor_referencia": str(condicion.valor_referencia) if condicion.valor_referencia is not None else None,
        "activa": condicion.activa,
        "observaciones": condicion.observaciones,
    }


def _record_event(user, area, tipo_evento, descripcion, condicion=None, medicion=None, datos_antes=None, datos_despues=None):
    event = AreaHistorialAmbiental(
        empresa_id=area.empresa_id,
        area_ambiente_id=area.id,
        condicion_ambiental_id=getattr(condicion, "id", None),
        medicion_ambiental_id=getattr(medicion, "id", None),
        tipo_evento=tipo_evento,
        descripcion=descripcion,
        datos_antes=datos_antes,
        datos_despues=datos_despues,
        usuario_id=getattr(user, "id", None),
    )
    db.session.add(event)
    return event


def evaluar_medicion(valor, limite_minimo=None, limite_maximo=None):
    valor = _as_decimal(valor, "El valor", required=True)
    limite_minimo = _as_decimal(limite_minimo, "El limite minimo")
    limite_maximo = _as_decimal(limite_maximo, "El limite maximo")
    _validate_limites(limite_minimo, limite_maximo)
    if limite_minimo is not None and valor < limite_minimo:
        return ESTADO_FUERA_DE_LIMITE
    if limite_maximo is not None and valor > limite_maximo:
        return ESTADO_FUERA_DE_LIMITE
    return ESTADO_CONFORME


def crear_condicion(user, area_ambiente_id, data):
    _require_permission(user, PERM_GESTIONAR)
    area = _ensure_area_habilitada(_get_area(user, area_ambiente_id))
    codigo = _clean(data.get("codigo"), upper=True)
    nombre = _clean(data.get("nombre"))
    unidad = _clean(data.get("unidad"))
    if not codigo:
        raise CondicionAmbientalError("El codigo de la condicion ambiental es obligatorio.")
    if not nombre:
        raise CondicionAmbientalError("El nombre de la condicion ambiental es obligatorio.")
    if not unidad:
        raise CondicionAmbientalError("La unidad de la condicion ambiental es obligatoria.")
    if AreaCondicionAmbiental.query.filter_by(empresa_id=user.empresa_id, area_ambiente_id=area.id, codigo=codigo).first():
        raise CondicionAmbientalError("Ya existe una condicion ambiental con ese codigo para el area.")
    limite_minimo = _as_decimal(data.get("limite_minimo"), "El limite minimo")
    limite_maximo = _as_decimal(data.get("limite_maximo"), "El limite maximo")
    _validate_limites(limite_minimo, limite_maximo)
    condicion = AreaCondicionAmbiental(
        empresa_id=user.empresa_id,
        area_ambiente_id=area.id,
        codigo=codigo,
        nombre=nombre,
        unidad=unidad,
        limite_minimo=limite_minimo,
        limite_maximo=limite_maximo,
        valor_referencia=_as_decimal(data.get("valor_referencia") or data.get("objetivo"), "El valor de referencia"),
        activa=True,
        observaciones=_clean(data.get("observaciones")),
    )
    db.session.add(condicion)
    db.session.flush()
    _record_event(
        user,
        area,
        "CONDICION_AMBIENTAL_CREADA",
        f"Condicion ambiental creada: {condicion.codigo} ({condicion.nombre}).",
        condicion=condicion,
        datos_despues=_condition_snapshot(condicion),
    )
    return condicion


def actualizar_condicion(user, condicion_id, data):
    _require_permission(user, PERM_GESTIONAR)
    condicion = _get_condicion(user, condicion_id)
    area = _ensure_area_habilitada(condicion.area_ambiente)
    previous = _condition_snapshot(condicion)
    codigo = _clean(data.get("codigo", condicion.codigo), upper=True)
    nombre = _clean(data.get("nombre", condicion.nombre))
    unidad = _clean(data.get("unidad", condicion.unidad))
    if not codigo:
        raise CondicionAmbientalError("El codigo de la condicion ambiental es obligatorio.")
    if not nombre:
        raise CondicionAmbientalError("El nombre de la condicion ambiental es obligatorio.")
    if not unidad:
        raise CondicionAmbientalError("La unidad de la condicion ambiental es obligatoria.")
    duplicate = AreaCondicionAmbiental.query.filter_by(
        empresa_id=user.empresa_id,
        area_ambiente_id=area.id,
        codigo=codigo,
    ).filter(AreaCondicionAmbiental.id != condicion.id).first()
    if duplicate:
        raise CondicionAmbientalError("Ya existe una condicion ambiental con ese codigo para el area.")
    limite_minimo = _as_decimal(data.get("limite_minimo"), "El limite minimo") if "limite_minimo" in data else condicion.limite_minimo
    limite_maximo = _as_decimal(data.get("limite_maximo"), "El limite maximo") if "limite_maximo" in data else condicion.limite_maximo
    _validate_limites(limite_minimo, limite_maximo)
    condicion.codigo = codigo
    condicion.nombre = nombre
    condicion.unidad = unidad
    condicion.limite_minimo = limite_minimo
    condicion.limite_maximo = limite_maximo
    if "valor_referencia" in data or "objetivo" in data:
        condicion.valor_referencia = _as_decimal(data.get("valor_referencia") or data.get("objetivo"), "El valor de referencia")
    if "observaciones" in data:
        condicion.observaciones = _clean(data.get("observaciones"))
    _record_event(
        user,
        area,
        "CONDICION_AMBIENTAL_ACTUALIZADA",
        f"Condicion ambiental actualizada: {condicion.codigo}.",
        condicion=condicion,
        datos_antes=previous,
        datos_despues=_condition_snapshot(condicion),
    )
    return condicion


def inactivar_condicion(user, condicion_id, observaciones=None):
    _require_permission(user, PERM_GESTIONAR)
    condicion = _get_condicion(user, condicion_id)
    if not condicion.activa:
        return condicion
    previous = _condition_snapshot(condicion)
    condicion.activa = False
    if observaciones:
        condicion.observaciones = _clean(observaciones)
    _record_event(
        user,
        condicion.area_ambiente,
        "CONDICION_AMBIENTAL_INACTIVADA",
        f"Condicion ambiental inactivada: {condicion.codigo}.",
        condicion=condicion,
        datos_antes=previous,
        datos_despues=_condition_snapshot(condicion),
    )
    return condicion


def registrar_medicion(user, area_ambiente_id, condicion_id, data):
    _require_permission(user, PERM_GESTIONAR)
    area = _ensure_area_habilitada(_get_area(user, area_ambiente_id))
    condicion = _get_condicion(user, condicion_id)
    if condicion.area_ambiente_id != area.id:
        raise CondicionAmbientalError("La condicion ambiental no pertenece al area indicada.")
    if not condicion.activa:
        raise CondicionAmbientalError("No se pueden registrar mediciones sobre una condicion ambiental inactiva.")
    registrado_por_id = data.get("registrado_por_id") or getattr(user, "id", None)
    registrado_por = _get_usuario(user, registrado_por_id)
    valor = _as_decimal(data.get("valor"), "El valor", required=True)
    fecha_hora = _as_datetime(data.get("fecha_hora_medicion") or data.get("fecha_hora"))
    estado = evaluar_medicion(valor, condicion.limite_minimo, condicion.limite_maximo)
    medicion = AreaMedicionAmbiental(
        empresa_id=user.empresa_id,
        area_ambiente_id=area.id,
        condicion_ambiental_id=condicion.id,
        fecha_hora_medicion=fecha_hora,
        valor=valor,
        estado=estado,
        limite_minimo_aplicado=condicion.limite_minimo,
        limite_maximo_aplicado=condicion.limite_maximo,
        unidad_aplicada=condicion.unidad,
        observaciones=_clean(data.get("observaciones")),
        registrado_por_id=registrado_por.id,
    )
    db.session.add(medicion)
    db.session.flush()
    limits_label = (
        f"min={medicion.limite_minimo_aplicado if medicion.limite_minimo_aplicado is not None else '-'}, "
        f"max={medicion.limite_maximo_aplicado if medicion.limite_maximo_aplicado is not None else '-'}"
    )
    event_type = "MEDICION_AMBIENTAL_FUERA_DE_LIMITE" if estado == ESTADO_FUERA_DE_LIMITE else "MEDICION_AMBIENTAL_REGISTRADA"
    _record_event(
        user,
        area,
        event_type,
        f"Medicion ambiental {estado}: {condicion.codigo}={medicion.valor} {medicion.unidad_aplicada} ({limits_label}).",
        condicion=condicion,
        medicion=medicion,
        datos_despues={
            "valor": str(medicion.valor),
            "unidad": medicion.unidad_aplicada,
            "estado": estado,
            "limite_minimo_aplicado": str(medicion.limite_minimo_aplicado) if medicion.limite_minimo_aplicado is not None else None,
            "limite_maximo_aplicado": str(medicion.limite_maximo_aplicado) if medicion.limite_maximo_aplicado is not None else None,
            "fecha_hora_medicion": medicion.fecha_hora_medicion.isoformat(),
            "registrado_por_id": registrado_por.id,
        },
    )
    return medicion


def condiciones_area(user, area_ambiente_id, solo_activas=False):
    _require_permission(user, PERM_VER)
    area = _get_area(user, area_ambiente_id)
    query = AreaCondicionAmbiental.query.filter_by(empresa_id=user.empresa_id, area_ambiente_id=area.id)
    if solo_activas:
        query = query.filter_by(activa=True)
    return query.order_by(AreaCondicionAmbiental.codigo.asc()).all()


def condiciones_activas_area(user, area_ambiente_id):
    return condiciones_area(user, area_ambiente_id, solo_activas=True)


def mediciones_area(user, area_ambiente_id):
    _require_permission(user, PERM_VER)
    area = _get_area(user, area_ambiente_id)
    return (
        AreaMedicionAmbiental.query
        .filter_by(empresa_id=user.empresa_id, area_ambiente_id=area.id)
        .order_by(AreaMedicionAmbiental.fecha_hora_medicion.desc(), AreaMedicionAmbiental.id.desc())
        .all()
    )


def mediciones_fuera_de_limite(user, area_ambiente_id=None):
    _require_permission(user, PERM_VER)
    query = AreaMedicionAmbiental.query.filter_by(empresa_id=user.empresa_id, estado=ESTADO_FUERA_DE_LIMITE)
    if area_ambiente_id:
        area = _get_area(user, area_ambiente_id)
        query = query.filter_by(area_ambiente_id=area.id)
    return query.order_by(AreaMedicionAmbiental.fecha_hora_medicion.desc(), AreaMedicionAmbiental.id.desc()).all()
