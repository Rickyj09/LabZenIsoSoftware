import re
from datetime import datetime, timezone

from app.extensions import db
from app.models.documentos import (
    DISTRIBUCION_TIPO_EXTERNO,
    DISTRIBUCION_TIPO_INTERNO,
    ENTREGA_PENDIENTE,
    DocumentoDistribucionDestinatario,
    DocumentoDistribucionEntrega,
)
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission


class DocumentDistributionError(ValueError):
    pass


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MANAGE_DISTRIBUTION_PERMISSION = "documentos.distribucion.gestionar"
RETRY_DISTRIBUTION_PERMISSION = "documentos.distribucion.reintentar"


def _now():
    return datetime.now(timezone.utc)


def normalize_email(email):
    normalized = (email or "").strip().lower()
    if not normalized or not EMAIL_RE.fullmatch(normalized):
        raise DocumentDistributionError("Debes indicar un correo electronico valido.")
    return normalized


class DocumentDistributionService:
    def add_internal_recipient(self, *, documento, usuario_destino_id, usuario_actor):
        self._require_manage(documento, usuario_actor)
        user = Usuario.query.filter_by(
            id=usuario_destino_id,
            empresa_id=documento.empresa_id,
            activo=True,
        ).first()
        if not user:
            raise DocumentDistributionError("El usuario interno no pertenece a la empresa del documento.")
        return self._upsert_recipient(
            documento=documento,
            usuario_actor=usuario_actor,
            usuario=user,
            nombre=f"{user.nombre} {user.apellido}".strip(),
            email=user.email,
            tipo=DISTRIBUCION_TIPO_INTERNO,
        )

    def add_external_recipient(self, *, documento, nombre, email, usuario_actor, grupo=None):
        self._require_manage(documento, usuario_actor)
        if not (nombre or "").strip():
            raise DocumentDistributionError("Debes indicar el nombre del destinatario externo.")
        return self._upsert_recipient(
            documento=documento,
            usuario_actor=usuario_actor,
            usuario=None,
            nombre=nombre,
            email=email,
            tipo=DISTRIBUCION_TIPO_EXTERNO,
            grupo=grupo,
        )

    def deactivate_recipient(self, *, destinatario, usuario_actor, motivo=None):
        self._require_manage(destinatario.documento, usuario_actor)
        destinatario.activo = False
        destinatario.desactivado_por_id = usuario_actor.id
        destinatario.desactivado_en = _now()
        destinatario.motivo_desactivacion = (motivo or "").strip() or None
        destinatario.actualizado_por_id = usuario_actor.id
        db.session.commit()
        return destinatario

    def reactivate_recipient(self, *, destinatario, usuario_actor):
        self._require_manage(destinatario.documento, usuario_actor)
        email = normalize_email(destinatario.email)
        exists = DocumentoDistribucionDestinatario.query.filter_by(
            empresa_id=destinatario.empresa_id,
            documento_id=destinatario.documento_id,
            email=email,
            activo=True,
        ).filter(DocumentoDistribucionDestinatario.id != destinatario.id).first()
        if exists:
            raise DocumentDistributionError("Ya existe un destinatario activo con ese correo.")
        destinatario.activo = True
        destinatario.desactivado_por_id = None
        destinatario.desactivado_en = None
        destinatario.motivo_desactivacion = None
        destinatario.actualizado_por_id = usuario_actor.id
        db.session.commit()
        return destinatario

    def active_recipients(self, documento):
        return (
            DocumentoDistribucionDestinatario.query
            .filter_by(empresa_id=documento.empresa_id, documento_id=documento.id, activo=True)
            .order_by(DocumentoDistribucionDestinatario.tipo.asc(), DocumentoDistribucionDestinatario.nombre.asc())
            .all()
        )

    def enqueue_publication_deliveries(self, *, publicacion):
        created = []
        for destinatario in self.active_recipients(publicacion.documento):
            email = normalize_email(destinatario.email)
            existing = DocumentoDistribucionEntrega.query.filter_by(
                empresa_id=publicacion.empresa_id,
                publicacion_id=publicacion.id,
                email_snapshot=email,
            ).first()
            if existing:
                continue
            entrega = DocumentoDistribucionEntrega(
                empresa_id=publicacion.empresa_id,
                publicacion_id=publicacion.id,
                destinatario_original_id=destinatario.id,
                usuario_id=destinatario.usuario_id,
                nombre_snapshot=destinatario.nombre,
                email_snapshot=email,
                tipo_snapshot=destinatario.tipo,
                estado_envio=ENTREGA_PENDIENTE,
                intentos=0,
                metadata_json={},
            )
            db.session.add(entrega)
            created.append(entrega)
        db.session.flush()
        return created

    def _upsert_recipient(self, *, documento, usuario_actor, usuario, nombre, email, tipo, grupo=None):
        email = normalize_email(email)
        existing = DocumentoDistribucionDestinatario.query.filter_by(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            email=email,
            activo=True,
        ).first()
        if existing:
            raise DocumentDistributionError("Ya existe un destinatario activo con ese correo.")
        recipient = DocumentoDistribucionDestinatario(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            usuario_id=usuario.id if usuario else None,
            nombre=(nombre or "").strip(),
            email=email,
            tipo=tipo,
            activo=True,
            grupo=(grupo or "").strip() or None,
            creado_por_id=usuario_actor.id,
            actualizado_por_id=usuario_actor.id,
        )
        db.session.add(recipient)
        db.session.commit()
        return recipient

    def _require_manage(self, documento, usuario_actor):
        if usuario_actor.empresa_id != documento.empresa_id:
            raise DocumentDistributionError("No puedes gestionar destinatarios de otra empresa.")
        if not user_has_permission(usuario_actor, MANAGE_DISTRIBUTION_PERMISSION):
            raise DocumentDistributionError("No tienes permiso para gestionar la lista de distribucion.")
