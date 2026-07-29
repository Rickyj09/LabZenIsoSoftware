import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app, has_request_context, url_for

from app.extensions import db
from app.models.documentos import (
    ENTREGA_ENVIADO,
    ENTREGA_FALLIDO,
    ENTREGA_OMITIDO,
    ENTREGA_PENDIENTE,
    ENTREGA_PROCESANDO,
    DocumentoDistribucionEntrega,
)


class DocumentEmailError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


class DocumentEmailService:
    def __init__(self, app=None):
        self.app = app or current_app

    def process_pending(self, *, limite=50, solo_fallidos=False, max_intentos=3, publicacion_id=None):
        states = [ENTREGA_FALLIDO] if solo_fallidos else [ENTREGA_PENDIENTE, ENTREGA_FALLIDO]
        query = DocumentoDistribucionEntrega.query.filter(
            DocumentoDistribucionEntrega.estado_envio.in_(states),
            DocumentoDistribucionEntrega.intentos < int(max_intentos),
        )
        if publicacion_id:
            query = query.filter(DocumentoDistribucionEntrega.publicacion_id == int(publicacion_id))
        entregas = query.order_by(DocumentoDistribucionEntrega.id.asc()).limit(int(limite)).all()
        results = {"procesadas": 0, "enviadas": 0, "fallidas": 0}
        for entrega in entregas:
            results["procesadas"] += 1
            try:
                self.send_delivery(entrega)
                results["enviadas"] += 1
            except Exception:
                results["fallidas"] += 1
        return results

    def send_delivery(self, entrega):
        if entrega.estado_envio == ENTREGA_ENVIADO:
            return entrega
        entrega.estado_envio = ENTREGA_PROCESANDO
        entrega.intentos = int(entrega.intentos or 0) + 1
        entrega.ultimo_intento_en = _now()
        db.session.commit()
        try:
            if not self.app.config.get("DOCUMENT_DISTRIBUTION_EMAIL_ENABLED"):
                entrega.estado_envio = ENTREGA_OMITIDO
                entrega.ultimo_error = "Envio omitido: DOCUMENT_DISTRIBUTION_EMAIL_ENABLED=false."
                entrega.metadata_json = {
                    **(entrega.metadata_json or {}),
                    "email_disabled": True,
                    "omitted_reason": "DOCUMENT_DISTRIBUTION_EMAIL_ENABLED=false",
                }
                db.session.commit()
                return entrega
            message = self._build_message(entrega)
            self._send_smtp(message)
            entrega.estado_envio = ENTREGA_ENVIADO
            entrega.enviado_en = _now()
            entrega.message_id = message["Message-ID"]
            entrega.ultimo_error = None
            entrega.metadata_json = {
                **(entrega.metadata_json or {}),
                "email_disabled": False,
            }
            db.session.commit()
            return entrega
        except Exception as exc:
            db.session.rollback()
            entrega = DocumentoDistribucionEntrega.query.get(entrega.id)
            entrega.estado_envio = ENTREGA_FALLIDO
            entrega.ultimo_error = self._sanitize_error(exc)
            entrega.ultimo_intento_en = _now()
            db.session.commit()
            raise

    def _build_message(self, entrega):
        publicacion = entrega.publicacion
        documento = publicacion.documento
        version = publicacion.documento_version
        url = self._publication_url(publicacion)
        sender = self.app.config.get("MAIL_DEFAULT_SENDER") or "no-reply@labzeniso.local"
        subject = f"Documento vigente: {documento.codigo} - version {version.version}"
        body = "\n".join([
            f"Hola {entrega.nombre_snapshot},",
            "",
            "Se ha publicado una nueva version vigente de un documento controlado.",
            "",
            f"Codigo: {documento.codigo}",
            f"Titulo: {documento.titulo}",
            f"Version: {version.version}",
            f"Proceso: {documento.proceso or 'No especificado'}",
            f"Fecha de vigencia: {publicacion.vigente_desde}",
            f"Resumen de cambios: {version.cambios or 'No especificado'}",
            f"Elaborador: {getattr(version.elaborado_por, 'nombre', '')} {getattr(version.elaborado_por, 'apellido', '')}".strip(),
            f"Revisor: {getattr(version.revisado_por, 'nombre', '')} {getattr(version.revisado_por, 'apellido', '')}".strip(),
            f"Aprobador: {getattr(version.aprobado_por, 'nombre', '')} {getattr(version.aprobado_por, 'apellido', '')}".strip(),
            "",
            f"Consultar documento vigente: {url}",
            "",
            "No uses copias obsoletas. Consulta siempre la version vigente desde el enlace controlado.",
            "",
            f"Empresa: {getattr(documento.empresa, 'nombre', '') or 'LabZenISO'}",
            "LabZenISO Software",
        ])
        message = EmailMessage()
        message["From"] = sender
        message["To"] = entrega.email_snapshot
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain="labzeniso.local")
        message.set_content(body)
        return message

    def _publication_url(self, publicacion):
        base = (self.app.config.get("DOCUMENT_PUBLICATION_BASE_URL") or "").strip().rstrip("/")
        path = (
            url_for("documentacion_publicaciones.ver_publicacion", public_id=publicacion.public_id)
            if has_request_context()
            else f"/documentos/publicados/{publicacion.public_id}"
        )
        return f"{base}{path}" if base else path

    def _send_smtp(self, message):
        server = (self.app.config.get("MAIL_SERVER") or "").strip()
        if not server:
            raise DocumentEmailError("MAIL_SERVER no esta configurado.")
        port = int(self.app.config.get("MAIL_PORT") or 587)
        timeout = int(self.app.config.get("MAIL_TIMEOUT") or 20)
        username = self.app.config.get("MAIL_USERNAME") or None
        password = self.app.config.get("MAIL_PASSWORD") or None
        use_ssl = bool(self.app.config.get("MAIL_USE_SSL"))
        use_tls = bool(self.app.config.get("MAIL_USE_TLS"))
        client_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with client_class(server, port, timeout=timeout) as smtp:
            if use_tls and not use_ssl:
                smtp.starttls()
            if username:
                smtp.login(username, password or "")
            smtp.send_message(message)

    def _sanitize_error(self, exc):
        message = str(exc)
        password = self.app.config.get("MAIL_PASSWORD") or None
        if password:
            message = message.replace(str(password), "<secret>")
        return message[:1000]
