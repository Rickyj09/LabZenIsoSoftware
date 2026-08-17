from datetime import date
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.equipos import (
    MaterialReferencia,
    MaterialReferenciaDocumento,
    MaterialReferenciaHistorial,
)
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission


PERM_VER = "equipos.ver"
PERM_GESTIONAR = "equipos.editar"
PERM_VINCULAR_EVIDENCIA = "equipos.documentos.vincular"
PERM_DESVINCULAR_EVIDENCIA = "equipos.documentos.vincular"

TIPO_MATERIAL_REFERENCIA = "MATERIAL_REFERENCIA"
TIPO_PATRON_REFERENCIA = "PATRON_REFERENCIA"
VALID_TYPES = {TIPO_MATERIAL_REFERENCIA, TIPO_PATRON_REFERENCIA}

ESTADO_DISPONIBLE = "DISPONIBLE"
ESTADO_EN_USO = "EN_USO"
ESTADO_AGOTADO = "AGOTADO"
ESTADO_VENCIDO = "VENCIDO"
ESTADO_RETIRADO = "RETIRADO"
VALID_STATES = {ESTADO_DISPONIBLE, ESTADO_EN_USO, ESTADO_AGOTADO, ESTADO_VENCIDO, ESTADO_RETIRADO}
TERMINAL_STATES = {ESTADO_AGOTADO, ESTADO_VENCIDO, ESTADO_RETIRADO}
OPERATIVE_STATES = {ESTADO_DISPONIBLE, ESTADO_EN_USO}

VALID_EVIDENCE_TYPES = {"CERTIFICADO", "FICHA_TECNICA", "HOJA_SEGURIDAD", "OTRO"}


class MaterialReferenciaError(ValueError):
    pass


def _clean(value, upper=False):
    value = (value or "").strip() if isinstance(value, str) else value
    if isinstance(value, str) and upper:
        value = value.upper()
    return value or None


def _as_date(value, field_name, required=False):
    if isinstance(value, date):
        return value
    value = _clean(value)
    if not value:
        if required:
            raise MaterialReferenciaError(f"{field_name} es obligatoria.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MaterialReferenciaError(f"{field_name} debe tener formato AAAA-MM-DD.") from exc


def _as_decimal(value, field_name):
    if value in ("", None):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MaterialReferenciaError(f"{field_name} debe ser numerico.") from exc


def _require_permission(user, permission):
    if not user_has_permission(user, permission):
        raise MaterialReferenciaError("No tienes permisos para realizar esta accion.")


def _require_same_company(user, item, message):
    if not item or int(item.empresa_id) != int(user.empresa_id):
        raise MaterialReferenciaError(message)
    return item


def _get_material(user, material_id):
    return _require_same_company(
        user,
        MaterialReferencia.query.filter_by(id=material_id, empresa_id=user.empresa_id).first(),
        "El material o patron de referencia no pertenece a esta empresa.",
    )


def _get_usuario_responsable(user, responsable_id):
    if not responsable_id:
        return None
    usuario = Usuario.query.filter_by(id=responsable_id, empresa_id=user.empresa_id, activo=True).first()
    if not usuario:
        raise MaterialReferenciaError("El responsable seleccionado no pertenece a esta empresa.")
    return usuario


def _record_event(user, material, tipo_evento, descripcion, estado_anterior=None, estado_nuevo=None, datos_antes=None, datos_despues=None):
    event = MaterialReferenciaHistorial(
        empresa_id=material.empresa_id,
        material_referencia_id=material.id,
        tipo_evento=tipo_evento,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        descripcion=descripcion,
        usuario_id=getattr(user, "id", None),
        datos_antes=datos_antes,
        datos_despues=datos_despues,
    )
    db.session.add(event)
    return event


def _validate_code(user, codigo, current_id=None):
    if not codigo:
        raise MaterialReferenciaError("El codigo del material o patron de referencia es obligatorio.")
    query = MaterialReferencia.query.filter_by(empresa_id=user.empresa_id, codigo=codigo)
    if current_id:
        query = query.filter(MaterialReferencia.id != current_id)
    if query.first():
        raise MaterialReferenciaError("Ya existe un material o patron de referencia con ese codigo en esta empresa.")


def _validate_dates(fecha_recepcion, fecha_caducidad, fecha_apertura=None, fecha_puesta_en_uso=None):
    if fecha_caducidad and fecha_caducidad < fecha_recepcion:
        raise MaterialReferenciaError("La fecha de caducidad no puede ser anterior a la fecha de recepcion.")
    if fecha_apertura and fecha_apertura < fecha_recepcion:
        raise MaterialReferenciaError("La fecha de apertura no puede ser anterior a la fecha de recepcion.")
    if fecha_puesta_en_uso and fecha_puesta_en_uso < fecha_recepcion:
        raise MaterialReferenciaError("La fecha de puesta en uso no puede ser anterior a la fecha de recepcion.")


def _validate_quantities(cantidad_inicial, cantidad_disponible, unidad):
    if cantidad_inicial is not None and cantidad_inicial < 0:
        raise MaterialReferenciaError("La cantidad inicial no puede ser negativa.")
    if cantidad_disponible is not None and cantidad_disponible < 0:
        raise MaterialReferenciaError("La cantidad disponible no puede ser negativa.")
    if cantidad_inicial is not None and cantidad_disponible is not None and cantidad_disponible > cantidad_inicial:
        raise MaterialReferenciaError("La cantidad disponible no puede ser mayor que la cantidad inicial.")
    if (cantidad_inicial is not None or cantidad_disponible is not None) and not unidad:
        raise MaterialReferenciaError("La unidad es obligatoria cuando se informa cantidad.")


def _ensure_not_terminal(material, action):
    if material.estado in TERMINAL_STATES:
        raise MaterialReferenciaError(f"No se puede {action} un material o patron en estado terminal.")


def _material_snapshot(material):
    return {
        "codigo": material.codigo,
        "nombre": material.nombre,
        "tipo": material.tipo,
        "estado": material.estado,
        "fecha_recepcion": material.fecha_recepcion.isoformat() if material.fecha_recepcion else None,
        "fecha_apertura": material.fecha_apertura.isoformat() if material.fecha_apertura else None,
        "fecha_puesta_en_uso": material.fecha_puesta_en_uso.isoformat() if material.fecha_puesta_en_uso else None,
        "fecha_caducidad": material.fecha_caducidad.isoformat() if material.fecha_caducidad else None,
        "cantidad_inicial": str(material.cantidad_inicial) if material.cantidad_inicial is not None else None,
        "cantidad_disponible": str(material.cantidad_disponible) if material.cantidad_disponible is not None else None,
        "unidad": material.unidad,
    }


def crear_material_referencia(user, data):
    _require_permission(user, PERM_GESTIONAR)
    codigo = _clean(data.get("codigo"), upper=True)
    _validate_code(user, codigo)
    nombre = _clean(data.get("nombre"))
    if not nombre:
        raise MaterialReferenciaError("El nombre del material o patron de referencia es obligatorio.")
    tipo = _clean(data.get("tipo"), upper=True)
    if tipo not in VALID_TYPES:
        raise MaterialReferenciaError("El tipo debe ser MATERIAL_REFERENCIA o PATRON_REFERENCIA.")
    fecha_recepcion = _as_date(data.get("fecha_recepcion"), "La fecha de recepcion", required=True)
    fecha_caducidad = _as_date(data.get("fecha_caducidad"), "La fecha de caducidad")
    _validate_dates(fecha_recepcion, fecha_caducidad)
    responsable = _get_usuario_responsable(user, data.get("responsable_id"))
    cantidad_inicial = _as_decimal(data.get("cantidad_inicial"), "La cantidad inicial")
    cantidad_disponible = _as_decimal(data.get("cantidad_disponible"), "La cantidad disponible")
    if cantidad_inicial is not None and cantidad_disponible is None:
        cantidad_disponible = cantidad_inicial
    unidad = _clean(data.get("unidad"))
    _validate_quantities(cantidad_inicial, cantidad_disponible, unidad)
    material = MaterialReferencia(
        empresa_id=user.empresa_id,
        codigo=codigo,
        nombre=nombre,
        descripcion=_clean(data.get("descripcion")),
        tipo=tipo,
        fabricante=_clean(data.get("fabricante")),
        proveedor=_clean(data.get("proveedor")),
        lote=_clean(data.get("lote")),
        certificado_numero=_clean(data.get("certificado_numero") or data.get("certificado")),
        referencia_fabricante=_clean(data.get("referencia_fabricante") or data.get("codigo_fabricante")),
        fecha_recepcion=fecha_recepcion,
        fecha_caducidad=fecha_caducidad,
        estado=ESTADO_DISPONIBLE,
        ubicacion=_clean(data.get("ubicacion") or data.get("almacenamiento")),
        condiciones_almacenamiento=_clean(data.get("condiciones_almacenamiento")),
        observaciones=_clean(data.get("observaciones")),
        responsable_id=responsable.id if responsable else None,
        cantidad_inicial=cantidad_inicial,
        cantidad_disponible=cantidad_disponible,
        unidad=unidad,
        activo=True,
    )
    db.session.add(material)
    db.session.flush()
    _record_event(
        user,
        material,
        "MATERIAL_REFERENCIA_CREADO",
        f"Material o patron de referencia creado: {material.codigo}.",
        estado_nuevo=material.estado,
        datos_despues=_material_snapshot(material),
    )
    return material


def poner_en_uso(user, material_id, fecha=None, observaciones=None):
    _require_permission(user, PERM_GESTIONAR)
    material = _get_material(user, material_id)
    _ensure_not_terminal(material, "poner en uso")
    if material.estado == ESTADO_EN_USO:
        raise MaterialReferenciaError("El material o patron de referencia ya se encuentra en uso.")
    if material.estado != ESTADO_DISPONIBLE:
        raise MaterialReferenciaError("Solo se pueden poner en uso materiales o patrones disponibles.")
    fecha_uso = _as_date(fecha, "La fecha de apertura o puesta en uso") or date.today()
    _validate_dates(material.fecha_recepcion, material.fecha_caducidad, fecha_apertura=fecha_uso, fecha_puesta_en_uso=fecha_uso)
    if material.fecha_apertura and material.fecha_apertura != fecha_uso:
        raise MaterialReferenciaError("La fecha de apertura ya fue registrada y no puede modificarse silenciosamente.")
    previous = material.estado
    material.estado = ESTADO_EN_USO
    material.fecha_apertura = material.fecha_apertura or fecha_uso
    material.fecha_puesta_en_uso = material.fecha_puesta_en_uso or fecha_uso
    if observaciones:
        material.observaciones = _clean(observaciones)
    _record_event(
        user,
        material,
        "MATERIAL_REFERENCIA_PUESTO_EN_USO",
        f"Material o patron de referencia puesto en uso: {material.codigo}.",
        previous,
        material.estado,
    )
    return material


def esta_vencido(material, today=None):
    today = today or date.today()
    return bool(material.fecha_caducidad and material.fecha_caducidad < today and material.estado not in {ESTADO_AGOTADO, ESTADO_RETIRADO})


def marcar_vencido(user, material_id, today=None):
    _require_permission(user, PERM_GESTIONAR)
    material = _get_material(user, material_id)
    if material.estado == ESTADO_VENCIDO:
        return material
    if material.estado in {ESTADO_AGOTADO, ESTADO_RETIRADO}:
        raise MaterialReferenciaError("No se puede marcar como vencido un material o patron agotado o retirado.")
    if not esta_vencido(material, today=today):
        raise MaterialReferenciaError("El material o patron de referencia no se encuentra vencido.")
    previous = material.estado
    material.estado = ESTADO_VENCIDO
    _record_event(
        user,
        material,
        "MATERIAL_REFERENCIA_VENCIDO",
        f"Material o patron de referencia marcado como vencido: {material.codigo}.",
        previous,
        material.estado,
    )
    return material


def agotar(user, material_id, motivo=None):
    _require_permission(user, PERM_GESTIONAR)
    material = _get_material(user, material_id)
    if material.estado not in OPERATIVE_STATES:
        raise MaterialReferenciaError("Solo se pueden agotar materiales o patrones disponibles o en uso.")
    previous = material.estado
    material.estado = ESTADO_AGOTADO
    material.activo = False
    if material.cantidad_disponible is not None:
        material.cantidad_disponible = Decimal("0")
    motivo = _clean(motivo) or "Agotamiento registrado."
    _record_event(
        user,
        material,
        "MATERIAL_REFERENCIA_AGOTADO",
        f"Material o patron de referencia agotado: {material.codigo}. Motivo: {motivo}",
        previous,
        material.estado,
    )
    return material


def retirar(user, material_id, motivo):
    _require_permission(user, PERM_GESTIONAR)
    material = _get_material(user, material_id)
    if material.estado not in OPERATIVE_STATES:
        raise MaterialReferenciaError("Solo se pueden retirar materiales o patrones disponibles o en uso.")
    motivo = _clean(motivo)
    if not motivo:
        raise MaterialReferenciaError("El motivo de retiro es obligatorio.")
    previous = material.estado
    material.estado = ESTADO_RETIRADO
    material.activo = False
    _record_event(
        user,
        material,
        "MATERIAL_REFERENCIA_RETIRADO",
        f"Material o patron de referencia retirado: {material.codigo}. Motivo: {motivo}",
        previous,
        material.estado,
    )
    return material


def materiales(user, estado=None, tipo=None):
    _require_permission(user, PERM_VER)
    query = MaterialReferencia.query.filter_by(empresa_id=user.empresa_id)
    if estado:
        query = query.filter(MaterialReferencia.estado == _clean(estado, upper=True))
    if tipo:
        query = query.filter(MaterialReferencia.tipo == _clean(tipo, upper=True))
    return query.order_by(MaterialReferencia.codigo.asc()).all()


def disponibles(user):
    _require_permission(user, PERM_VER)
    return (
        MaterialReferencia.query
        .filter_by(empresa_id=user.empresa_id, estado=ESTADO_DISPONIBLE)
        .order_by(MaterialReferencia.codigo.asc())
        .all()
    )


def en_uso(user):
    _require_permission(user, PERM_VER)
    return (
        MaterialReferencia.query
        .filter_by(empresa_id=user.empresa_id, estado=ESTADO_EN_USO)
        .order_by(MaterialReferencia.codigo.asc())
        .all()
    )


def vencidos(user, today=None):
    _require_permission(user, PERM_VER)
    today = today or date.today()
    return (
        MaterialReferencia.query
        .filter(
            MaterialReferencia.empresa_id == user.empresa_id,
            MaterialReferencia.fecha_caducidad.isnot(None),
            MaterialReferencia.fecha_caducidad < today,
            MaterialReferencia.estado.notin_((ESTADO_AGOTADO, ESTADO_RETIRADO)),
        )
        .order_by(MaterialReferencia.fecha_caducidad.asc(), MaterialReferencia.codigo.asc())
        .all()
    )


def proximos_a_vencer(user, dias, today=None):
    _require_permission(user, PERM_VER)
    today = today or date.today()
    end_date = date.fromordinal(today.toordinal() + int(dias))
    return (
        MaterialReferencia.query
        .filter(
            MaterialReferencia.empresa_id == user.empresa_id,
            MaterialReferencia.estado.in_((ESTADO_DISPONIBLE, ESTADO_EN_USO)),
            MaterialReferencia.fecha_caducidad.isnot(None),
            MaterialReferencia.fecha_caducidad >= today,
            MaterialReferencia.fecha_caducidad <= end_date,
        )
        .order_by(MaterialReferencia.fecha_caducidad.asc(), MaterialReferencia.codigo.asc())
        .all()
    )


def vincular_evidencia_documental(user, material_id, documento_id, documento_version_id, tipo_evidencia="CERTIFICADO", observaciones=None):
    _require_permission(user, PERM_VINCULAR_EVIDENCIA)
    material = _get_material(user, material_id)
    _ensure_not_terminal(material, "vincular evidencia a")
    document = Documento.query.filter_by(id=documento_id, empresa_id=user.empresa_id).first()
    if not document:
        raise MaterialReferenciaError("El documento seleccionado no pertenece a esta empresa.")
    version = DocumentoVersion.query.filter_by(id=documento_version_id, empresa_id=user.empresa_id).first()
    if not version:
        raise MaterialReferenciaError("La version documental seleccionada no pertenece a esta empresa.")
    if version.documento_id != document.id:
        raise MaterialReferenciaError("La version documental no pertenece al documento indicado.")
    if MaterialReferenciaDocumento.query.filter_by(material_referencia_id=material.id, documento_version_id=version.id).first():
        raise MaterialReferenciaError("Esa version documental ya esta vinculada al material o patron de referencia.")
    evidence_type = _clean(tipo_evidencia, upper=True) or "CERTIFICADO"
    if evidence_type not in VALID_EVIDENCE_TYPES:
        raise MaterialReferenciaError("El tipo de evidencia documental no es valido.")
    evidence = MaterialReferenciaDocumento(
        empresa_id=user.empresa_id,
        material_referencia_id=material.id,
        documento_id=document.id,
        documento_version_id=version.id,
        tipo_evidencia=evidence_type,
        observaciones=_clean(observaciones),
        vinculado_por_id=user.id,
    )
    db.session.add(evidence)
    db.session.flush()
    _record_event(
        user,
        material,
        "EVIDENCIA_MATERIAL_REFERENCIA_VINCULADA",
        f"Evidencia vinculada a {material.codigo}: {document.codigo} v{version.version}.",
    )
    return evidence


def desvincular_evidencia_documental(user, evidencia_id, motivo=None):
    _require_permission(user, PERM_DESVINCULAR_EVIDENCIA)
    evidence = _require_same_company(
        user,
        MaterialReferenciaDocumento.query.filter_by(id=evidencia_id, empresa_id=user.empresa_id).first(),
        "La evidencia no pertenece a esta empresa.",
    )
    material = evidence.material_referencia
    _ensure_not_terminal(material, "desvincular evidencia de")
    document_code = evidence.documento.codigo if evidence.documento else str(evidence.documento_id)
    version_label = evidence.documento_version.version if evidence.documento_version else str(evidence.documento_version_id)
    description = f"Evidencia desvinculada de {material.codigo}: {document_code} v{version_label}."
    description += f" Motivo: {_clean(motivo) or 'No especificado'}."
    _record_event(user, material, "EVIDENCIA_MATERIAL_REFERENCIA_DESVINCULADA", description)
    db.session.delete(evidence)
    return True
