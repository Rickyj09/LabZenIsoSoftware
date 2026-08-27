import re
from datetime import date, datetime, timezone

from app.extensions import db
from app.models.documentos import DocumentoVersion
from app.models.seguridad import Usuario


ACTIVE_PREPARATION_STATES = ("EN_ELABORACION", "EN_ACTUALIZACION", "EN_REVISION", "EN_APROBACION")
VERSION_NUMBER_PATTERN = re.compile(r"^\d+(?:\.\d+){0,3}$")


class DocumentVersioningError(ValueError):
    pass


def _normalize_user_id(value):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DocumentVersioningError("Debe seleccionar un responsable valido.") from exc


def validate_document_responsibles(*, empresa_id, elaborado_por_id, revisado_por_id, aprobado_por_id):
    if not revisado_por_id:
        raise DocumentVersioningError("Debe seleccionar un revisor.")
    if not aprobado_por_id:
        raise DocumentVersioningError("Debe seleccionar un aprobador.")

    elaborado_por_id = _normalize_user_id(elaborado_por_id)
    revisado_por_id = _normalize_user_id(revisado_por_id)
    aprobado_por_id = _normalize_user_id(aprobado_por_id)

    if elaborado_por_id == revisado_por_id:
        raise DocumentVersioningError("El elaborador y el revisor deben ser diferentes.")
    users = {
        user.id: user
        for user in Usuario.query.filter(
            Usuario.id.in_([elaborado_por_id, revisado_por_id, aprobado_por_id]),
            Usuario.empresa_id == empresa_id,
            Usuario.activo.is_(True),
        ).all()
    }
    for user_id in (elaborado_por_id, revisado_por_id, aprobado_por_id):
        if user_id not in users:
            raise DocumentVersioningError("Los responsables deben pertenecer a la empresa del documento y estar activos.")

    return {
        "elaborado_por_id": elaborado_por_id,
        "revisado_por_id": revisado_por_id,
        "aprobado_por_id": aprobado_por_id,
    }


def validate_version_number(version: str) -> str:
    normalized = (version or "").strip()
    if not normalized or len(normalized) > 20 or not VERSION_NUMBER_PATTERN.fullmatch(normalized):
        raise DocumentVersioningError(
            "La versión debe ser numérica y puede contener hasta tres segmentos, por ejemplo 1, 1.1 o 2.0."
        )
    return normalized


def get_current_version(documento):
    version_doc = documento.version_vigente
    if not version_doc:
        return None
    if (
        version_doc.documento_id != documento.id
        or version_doc.empresa_id != documento.empresa_id
        or version_doc.estado not in ("APROBADO", "VIGENTE")
    ):
        return None
    return version_doc


def get_preparation_version(documento):
    return (
        DocumentoVersion.query
        .filter(
            DocumentoVersion.documento_id == documento.id,
            DocumentoVersion.empresa_id == documento.empresa_id,
            DocumentoVersion.estado.in_(ACTIVE_PREPARATION_STATES),
        )
        .order_by(DocumentoVersion.id.desc())
        .first()
    )


def create_initial_version(
    *,
    documento,
    version,
    cambios,
    contenido,
    user_id=None,
    elaborado_por_id=None,
    revisado_por_id=None,
    aprobado_por_id=None,
):
    version = validate_version_number(version)
    if documento.versiones:
        raise DocumentVersioningError("El documento ya tiene una versión inicial.")

    responsables = validate_document_responsibles(
        empresa_id=documento.empresa_id,
        elaborado_por_id=elaborado_por_id if elaborado_por_id is not None else user_id,
        revisado_por_id=revisado_por_id,
        aprobado_por_id=aprobado_por_id,
    )

    version_doc = DocumentoVersion(
        empresa_id=documento.empresa_id,
        documento_id=documento.id,
        version=version,
        archivo_url=None,
        contenido=contenido or None,
        fecha_version=date.today(),
        cambios=cambios or "Versión inicial del documento",
        elaborado_por_id=responsables["elaborado_por_id"],
        revisado_por_id=responsables["revisado_por_id"],
        aprobado_por_id=responsables["aprobado_por_id"],
        estado="EN_ELABORACION",
    )
    db.session.add(version_doc)
    return version_doc


def create_draft_version(
    *,
    documento,
    version,
    cambios,
    contenido,
    user_id=None,
    elaborado_por_id=None,
    revisado_por_id=None,
    aprobado_por_id=None,
):
    if documento.estado == "OBSOLETO":
        raise DocumentVersioningError("No se pueden crear versiones de un documento obsoleto.")
    version = validate_version_number(version)
    if not (cambios or "").strip():
        raise DocumentVersioningError("La descripción de cambios es obligatoria.")
    if get_preparation_version(documento):
        raise DocumentVersioningError(
            "Ya existe una versión en preparación. Debes completar su revisión antes de crear otra."
        )
    if DocumentoVersion.query.filter_by(documento_id=documento.id, version=version).first():
        raise DocumentVersioningError("Ya existe esa versión para este documento.")

    responsables = validate_document_responsibles(
        empresa_id=documento.empresa_id,
        elaborado_por_id=elaborado_por_id if elaborado_por_id is not None else user_id,
        revisado_por_id=revisado_por_id,
        aprobado_por_id=aprobado_por_id,
    )

    version_doc = DocumentoVersion(
        empresa_id=documento.empresa_id,
        documento_id=documento.id,
        version=version,
        archivo_url=None,
        contenido=contenido or None,
        fecha_version=date.today(),
        cambios=cambios.strip(),
        elaborado_por_id=responsables["elaborado_por_id"],
        revisado_por_id=responsables["revisado_por_id"],
        aprobado_por_id=responsables["aprobado_por_id"],
        estado="EN_ELABORACION",
    )
    db.session.add(version_doc)
    return version_doc


def send_to_review(*, documento, version_doc, user_id):
    if documento.estado == "OBSOLETO":
        raise DocumentVersioningError("No se puede revisar un documento obsoleto.")
    if version_doc.estado != "EN_ELABORACION":
        raise DocumentVersioningError("Solo una versión en elaboración puede enviarse a revisión.")
    if version_doc.id != getattr(get_preparation_version(documento), "id", None):
        raise DocumentVersioningError("La versión seleccionada no es la versión activa en preparación.")

    validate_document_responsibles(
        empresa_id=documento.empresa_id,
        elaborado_por_id=version_doc.elaborado_por_id,
        revisado_por_id=version_doc.revisado_por_id,
        aprobado_por_id=version_doc.aprobado_por_id,
    )

    version_doc.estado = "EN_REVISION"
    version_doc.fecha_envio_revision = datetime.now(timezone.utc)
    if not documento.version_vigente_id:
        documento.estado = "EN_REVISION"
    return version_doc


def approve_version(*, documento, version_doc, user_id):
    if documento.estado == "OBSOLETO":
        raise DocumentVersioningError("No se puede aprobar un documento obsoleto.")
    if version_doc.empresa_id != documento.empresa_id or version_doc.documento_id != documento.id:
        raise DocumentVersioningError("La versión no pertenece al documento o empresa indicados.")
    if version_doc.estado != "EN_APROBACION":
        raise DocumentVersioningError("Solo una version con conformidad de revision puede aprobarse.")
    if version_doc.id != getattr(get_preparation_version(documento), "id", None):
        raise DocumentVersioningError("No se puede aprobar una versión histórica.")

    previous = get_current_version(documento)
    if previous and previous.id != version_doc.id:
        previous.estado = "SUSTITUIDO"
        previous.fecha_obsolescencia = datetime.now(timezone.utc)

    version_doc.estado = "APROBADO"
    version_doc.aprobado_por_id = user_id
    version_doc.fecha_aprobacion = datetime.now(timezone.utc)
    documento.version_vigente_id = version_doc.id
    documento.version_vigente = version_doc
    documento.version_actual = version_doc.version
    documento.estado = "APROBADO"
    return previous


def can_edit_document(documento) -> bool:
    return documento.estado == "EN_ELABORACION"
