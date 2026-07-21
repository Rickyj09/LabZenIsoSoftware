from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.documentos import Documento, DocumentoAprobacion, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Rol, Usuario, UsuarioRol


DEMO_DOCUMENTS = (
    ("DEMO-BOR-001", "Procedimiento en elaboración demo", "PROCEDIMIENTO"),
    ("DEMO-REV-001", "Instructivo pendiente de revisión demo", "INSTRUCTIVO"),
    ("DEMO-VIG-001", "Política vigente demo", "POLITICA"),
    ("DEMO-RECH-001", "Formato rechazado demo", "FORMATO"),
    ("DEMO-ACT-001", "Procedimiento vigente en actualización demo", "PROCEDIMIENTO"),
    ("DEMO-OBS-001", "Manual obsoleto demo", "MANUAL"),
    ("DEMO-REG-001", "Registro de capacitación demo", "REGISTRO"),
)

DEMO_USERS = (
    ("calidad_demo", "Calidad", "Demo", "calidad_demo@labzen.local", "CALIDAD"),
    ("revisor_documental", "Revisor", "Documental", "revisor.documental@labzen.test", "REVISOR_DOCUMENTAL"),
    ("tecnico_demo", "Técnico", "Demo", "tecnico_demo@labzen.local", "TECNICO"),
    ("consulta_demo", "Consulta", "Demo", "consulta_demo@labzen.local", "CONSULTA"),
)


def _now():
    return datetime.now(timezone.utc)


def _get_or_create_empresa(empresa_id):
    empresa = db.session.get(Empresa, empresa_id)
    if empresa:
        return empresa
    empresa = Empresa(
        id=empresa_id,
        nombre="Empresa Demo LabZen",
        ruc="DEMO",
        email="demo@labzen.local",
        estado="activo",
    )
    db.session.add(empresa)
    db.session.flush()
    return empresa


def _assign_role(user, role_name):
    role = Rol.query.filter_by(nombre=role_name).first()
    if not role:
        return False
    exists = UsuarioRol.query.filter_by(usuario_id=user.id, rol_id=role.id).first()
    if not exists:
        db.session.add(UsuarioRol(usuario_id=user.id, rol_id=role.id))
    return True


def _get_or_create_demo_users(empresa_id):
    users = {}
    for username, name, surname, email, role_name in DEMO_USERS:
        user = Usuario.query.filter_by(empresa_id=empresa_id, username=username).first()
        if not user:
            user = Usuario(
                empresa_id=empresa_id,
                nombre=name,
                apellido=surname,
                email=email,
                username=username,
                password_hash=generate_password_hash("Prueba1234"),
                cargo=f"Usuario demo {role_name.lower()}",
                activo=True,
            )
            db.session.add(user)
            db.session.flush()
        _assign_role(user, role_name)
        users[username] = user
    return users


def _get_or_create_document(*, empresa_id, code, title, document_type, state, author_id):
    document = Documento.query.filter_by(empresa_id=empresa_id, codigo=code).first()
    if document:
        return document, False
    document = Documento(
        empresa_id=empresa_id,
        codigo=code,
        titulo=title,
        tipo_documento=document_type,
        proceso="Demo módulo documental",
        estado=state,
        version_actual="1",
        elaborado_por_id=author_id,
    )
    db.session.add(document)
    db.session.flush()
    return document, True


def _get_or_create_version(*, document, version, state, author_id, changes, **metadata):
    version_doc = DocumentoVersion.query.filter_by(documento_id=document.id, version=version).first()
    if version_doc:
        return version_doc, False
    version_doc = DocumentoVersion(
        empresa_id=document.empresa_id,
        documento_id=document.id,
        version=version,
        estado=state,
        elaborado_por_id=author_id,
        cambios=changes,
        contenido="Documento demo creado para presentación funcional del módulo documental.",
        **metadata,
    )
    db.session.add(version_doc)
    db.session.flush()
    return version_doc, True


def _event_exists(version_doc, action):
    return DocumentoAprobacion.query.filter_by(
        empresa_id=version_doc.empresa_id,
        documento_version_id=version_doc.id,
        accion=action,
    ).first()


def _add_event(document, version_doc, user, action, previous_state, new_state, comment):
    if _event_exists(version_doc, action):
        return False
    db.session.add(DocumentoAprobacion(
        empresa_id=document.empresa_id,
        documento_id=document.id,
        documento_version_id=version_doc.id,
        usuario_id=user.id,
        accion=action,
        fecha_accion=_now(),
        estado_anterior=previous_state,
        estado_nuevo=new_state,
        comentario=comment,
    ))
    return True


def seed_demo_documents(empresa_id=1):
    _get_or_create_empresa(empresa_id)
    users = _get_or_create_demo_users(empresa_id)
    technician = users["tecnico_demo"]
    quality = users["calidad_demo"]
    reviewer = users["revisor_documental"]
    created_documents = []

    def remember(document, was_created):
        if was_created:
            created_documents.append(document.codigo)

    draft, created = _get_or_create_document(
        empresa_id=empresa_id,
        code="DEMO-BOR-001",
        title="Procedimiento en elaboración demo",
        document_type="PROCEDIMIENTO",
        state="EN_ELABORACION",
        author_id=technician.id,
    )
    remember(draft, created)
    draft_version, _ = _get_or_create_version(
        document=draft,
        version="1",
        state="EN_ELABORACION",
        author_id=technician.id,
        changes="Versión demo en elaboración.",
    )
    _add_event(draft, draft_version, technician, "CREAR_VERSION", None, "EN_ELABORACION", "Documento demo en elaboración.")

    review, created = _get_or_create_document(
        empresa_id=empresa_id,
        code="DEMO-REV-001",
        title="Instructivo pendiente de revisión demo",
        document_type="INSTRUCTIVO",
        state="EN_REVISION",
        author_id=technician.id,
    )
    remember(review, created)
    review_version, _ = _get_or_create_version(
        document=review,
        version="1",
        state="EN_REVISION",
        author_id=technician.id,
        changes="Versión demo enviada a revisión.",
        revisado_por_id=reviewer.id,
        aprobado_por_id=quality.id,
        fecha_envio_revision=_now(),
        comentario_revision="Documento demo listo para revisión.",
    )
    _add_event(review, review_version, technician, "ENVIAR_REVISION", "EN_ELABORACION", "EN_REVISION", "Enviado a revisión demo.")

    current, created = _get_or_create_document(
        empresa_id=empresa_id,
        code="DEMO-VIG-001",
        title="Política vigente demo",
        document_type="POLITICA",
        state="APROBADO",
        author_id=technician.id,
    )
    remember(current, created)
    current_version, _ = _get_or_create_version(
        document=current,
        version="1",
        state="APROBADO",
        author_id=technician.id,
        changes="Versión demo aprobada.",
        aprobado_por_id=quality.id,
        revisado_por_id=quality.id,
        fecha_aprobacion=_now(),
        comentario_aprobacion="Aprobada para demo.",
    )
    current.version_vigente_id = current_version.id
    _add_event(current, current_version, quality, "APROBAR", "EN_REVISION", "APROBADO", "Documento vigente demo.")

    rejected, created = _get_or_create_document(
        empresa_id=empresa_id,
        code="DEMO-RECH-001",
        title="Formato rechazado demo",
        document_type="FORMATO",
        state="RECHAZADO",
        author_id=technician.id,
    )
    remember(rejected, created)
    rejected_version, _ = _get_or_create_version(
        document=rejected,
        version="1",
        state="RECHAZADO",
        author_id=technician.id,
        changes="Versión demo rechazada.",
        rechazado_por_id=quality.id,
        revisado_por_id=quality.id,
        fecha_rechazo=_now(),
        comentario_rechazo="Falta completar criterios de aceptación.",
    )
    _add_event(rejected, rejected_version, quality, "RECHAZAR", "EN_REVISION", "RECHAZADO", "Falta completar criterios de aceptación.")

    updating, created = _get_or_create_document(
        empresa_id=empresa_id,
        code="DEMO-ACT-001",
        title="Procedimiento vigente en actualización demo",
        document_type="PROCEDIMIENTO",
        state="APROBADO",
        author_id=technician.id,
    )
    remember(updating, created)
    updating_v1, _ = _get_or_create_version(
        document=updating,
        version="1",
        state="APROBADO",
        author_id=technician.id,
        changes="Versión vigente inicial.",
        aprobado_por_id=quality.id,
        revisado_por_id=quality.id,
        fecha_aprobacion=_now(),
    )
    updating.version_vigente_id = updating_v1.id
    _get_or_create_version(
        document=updating,
        version="2",
        state="EN_ELABORACION",
        author_id=technician.id,
        changes="Actualización demo en preparación.",
    )
    updating.version_actual = "2"
    _add_event(updating, updating_v1, quality, "APROBAR", "EN_REVISION", "APROBADO", "Versión 1 vigente.")

    obsolete, created = _get_or_create_document(
        empresa_id=empresa_id,
        code="DEMO-OBS-001",
        title="Manual obsoleto demo",
        document_type="MANUAL",
        state="OBSOLETO",
        author_id=technician.id,
    )
    remember(obsolete, created)
    obsolete_version, _ = _get_or_create_version(
        document=obsolete,
        version="1",
        state="OBSOLETO",
        author_id=technician.id,
        changes="Manual demo retirado.",
        obsoletado_por_id=quality.id,
        fecha_obsolescencia=_now(),
        motivo_obsolescencia="Documento reemplazado para demostración.",
    )
    _add_event(obsolete, obsolete_version, quality, "OBSOLETAR", "APROBADO", "OBSOLETO", "Documento reemplazado para demostración.")

    record, created = _get_or_create_document(
        empresa_id=empresa_id,
        code="DEMO-REG-001",
        title="Registro de capacitación demo",
        document_type="REGISTRO",
        state="APROBADO",
        author_id=technician.id,
    )
    remember(record, created)
    record_version, _ = _get_or_create_version(
        document=record,
        version="1",
        state="APROBADO",
        author_id=technician.id,
        changes="Registro demo aprobado.",
        aprobado_por_id=quality.id,
        revisado_por_id=quality.id,
        fecha_aprobacion=_now(),
    )
    record.version_vigente_id = record_version.id
    _add_event(record, record_version, quality, "APROBAR", "EN_REVISION", "APROBADO", "Registro demo aprobado.")

    db.session.commit()
    return {
        "empresa_id": empresa_id,
        "created_documents": created_documents,
        "document_codes": [code for code, _title, _type in DEMO_DOCUMENTS],
        "usernames": [username for username, _name, _surname, _email, _role in DEMO_USERS],
    }
