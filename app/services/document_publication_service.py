import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from flask import current_app, has_request_context, url_for

from app.extensions import db
from app.models.documentos import (
    ARTEFACTO_DISPONIBLE,
    ARTEFACTO_PDF_APROBADO,
    ARTEFACTO_PDF_APROBADO_CON_QR,
    ESTADO_APROBADO,
    ESTADO_OBSOLETO,
    ESTADO_VIGENTE,
    FIRMA_PROCESO_COMPLETADO,
    PUBLICACION_ACCESO_AUTENTICADO,
    PUBLICACION_ACTIVA,
    PUBLICACION_OBSOLETA,
    PUBLICACION_PREPARADA,
    PUBLICACION_REVOCADA,
    Documento,
    DocumentoAprobacion,
    DocumentoArtefacto,
    DocumentoFirmaProceso,
    DocumentoPublicacion,
    DocumentoVersion,
)
from app.security.permissions import user_has_permission
from app.services.document_distribution_service import DocumentDistributionService
from app.services.document_pdf_service import DocumentPdfService, PDF_MIME
from app.services.document_qr_service import DocumentQrService
from app.services.storage_service import (
    resolve_document_path,
    store_publication_qr_copy,
    store_qr_pdf_artifact_copy,
)


class DocumentPublicationError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedPublication:
    publicacion: DocumentoPublicacion
    qr_storage_key: str
    qr_sha256: str
    artifact: DocumentoArtefacto


PUBLISH_PERMISSION = "documentos.publicar_vigente"
REVOKE_PERMISSION = "documentos.publicaciones.revocar"


def _now():
    return datetime.now(timezone.utc)


class DocumentPublicationService:
    def __init__(self, app=None):
        self.app = app or current_app
        self.pdf_service = DocumentPdfService(app=self.app)
        self.qr_service = DocumentQrService(app=self.app)

    def latest_publication_for_document(self, documento):
        return (
            DocumentoPublicacion.query
            .filter_by(empresa_id=documento.empresa_id, documento_id=documento.id)
            .order_by(DocumentoPublicacion.vigente_desde.desc().nullslast(), DocumentoPublicacion.id.desc())
            .first()
        )

    def active_publication_for_document(self, documento):
        return DocumentoPublicacion.query.filter_by(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            estado=PUBLICACION_ACTIVA,
            activa=True,
        ).first()

    def publication_for_version(self, version_doc):
        return (
            DocumentoPublicacion.query
            .filter_by(empresa_id=version_doc.empresa_id, documento_version_id=version_doc.id)
            .order_by(DocumentoPublicacion.id.desc())
            .first()
        )

    def prepare_publication_for_signature(self, *, documento, version_doc, usuario):
        self._validate_same_company(documento, version_doc, usuario)
        existing_process = self._latest_signature_process(version_doc)
        publicacion = self.publication_for_version(version_doc)
        if existing_process:
            artifact = existing_process.pdf_origen
            if artifact and artifact.tipo == ARTEFACTO_PDF_APROBADO_CON_QR and publicacion and publicacion.qr_storage_key:
                return PreparedPublication(
                    publicacion=publicacion,
                    qr_storage_key=publicacion.qr_storage_key,
                    qr_sha256=publicacion.qr_sha256,
                    artifact=artifact,
                )
            raise DocumentPublicationError(
                "Ya existe un proceso de firma para esta version; no se puede regenerar el QR ni cambiar el PDF origen."
            )

        original_pdf = self.pdf_service.available_artifact_for_version(version_doc)
        if not original_pdf:
            raise DocumentPublicationError("No existe PDF aprobado disponible para preparar QR.")
        self.pdf_service.validate_artifact_file(original_pdf)

        publicacion = self._get_or_create_prepared_publication(
            documento=documento,
            version_doc=version_doc,
            usuario=usuario,
            original_pdf=original_pdf,
        )
        if publicacion.pdf_qr_artifact and publicacion.qr_storage_key:
            return PreparedPublication(
                publicacion=publicacion,
                qr_storage_key=publicacion.qr_storage_key,
                qr_sha256=publicacion.qr_sha256,
                artifact=publicacion.pdf_qr_artifact,
            )

        publication_url = self._absolute_publication_url(publicacion)
        qr_path = pdf_qr_path = None
        try:
            qr_path, qr_sha256, _qr_size = self.qr_service.generate_qr_png(publication_url)
            stored_qr = store_publication_qr_copy(
                source_path=qr_path,
                documento=documento,
                version_doc=version_doc,
                public_id=publicacion.public_id,
            )
            publicacion.qr_payload = publication_url
            publicacion.qr_storage_key = stored_qr.storage_path
            publicacion.qr_sha256 = stored_qr.sha256

            source_path = resolve_document_path(original_pdf.storage_path)
            qr_box = self.qr_service.publication_box(tipo_documento=documento.tipo_documento)
            pdf_qr_path = self.qr_service.embed_qr_in_pdf(
                pdf_path=source_path,
                qr_png_path=qr_path,
                box=qr_box,
                tipo_documento=documento.tipo_documento,
            )
            validation = self.pdf_service.validate_pdf_file(pdf_qr_path, allow_signature_forms=True)
            stored_pdf = store_qr_pdf_artifact_copy(
                source_path=pdf_qr_path,
                documento=documento,
                version_doc=version_doc,
                source_artifact=original_pdf,
                expected_sha256=validation.sha256,
            )
            artifact = DocumentoArtefacto(
                empresa_id=documento.empresa_id,
                public_id=uuid4().hex,
                documento_id=documento.id,
                documento_version_id=version_doc.id,
                source_snapshot_id=original_pdf.source_snapshot_id,
                source_artifact_id=original_pdf.id,
                tipo=ARTEFACTO_PDF_APROBADO_CON_QR,
                estado=ARTEFACTO_DISPONIBLE,
                storage_path=stored_pdf.storage_path,
                archivo_nombre_interno=stored_pdf.stored_name,
                archivo_nombre_visible=f"{documento.codigo}_v{version_doc.version}_aprobado_con_qr.pdf",
                archivo_mime=PDF_MIME,
                archivo_size=stored_pdf.size,
                archivo_sha256=stored_pdf.sha256,
                source_snapshot_sha256=original_pdf.source_snapshot_sha256,
                source_artifact_sha256=original_pdf.archivo_sha256,
                page_count=validation.page_count,
                signature_count=0,
                provider="labzeniso-publicacion",
                provider_version="qr-v1",
                creado_por_id=usuario.id,
                creado_en=_now(),
                disponible_en=_now(),
                inmutable=True,
                metadata_json={
                    "qr_embebido": True,
                    "qr_sha256": stored_qr.sha256,
                    "pdf_aprobado_original_id": original_pdf.id,
                    "qr_page": qr_box.page_selector,
                    "qr_box": list(qr_box.normalized_box),
                },
            )
            db.session.add(artifact)
            db.session.flush()
            publicacion.pdf_qr_artifact_id = artifact.id
            publicacion.qr_embebido = True
            publicacion.metadata_json = {
                **(publicacion.metadata_json or {}),
                "pdf_qr_artifact_id": artifact.id,
                "qr_page": qr_box.page_selector,
                "qr_box": list(qr_box.normalized_box),
            }
            self._record_event(documento, version_doc, usuario, "QR_GENERADO", "QR generado localmente.")
            self._record_event(documento, version_doc, usuario, "PDF_QR_GENERADO", "PDF aprobado con QR preparado para firma.")
            db.session.commit()
            return PreparedPublication(
                publicacion=publicacion,
                qr_storage_key=publicacion.qr_storage_key,
                qr_sha256=publicacion.qr_sha256,
                artifact=artifact,
            )
        except Exception:
            db.session.rollback()
            raise
        finally:
            if qr_path:
                qr_path.unlink(missing_ok=True)
            if pdf_qr_path:
                pdf_qr_path.unlink(missing_ok=True)

    def prepare_publication_artifact_for_signature(self, *, documento, version_doc, usuario):
        return self.prepare_publication_for_signature(
            documento=documento,
            version_doc=version_doc,
            usuario=usuario,
        ).artifact

    def publish_as_current(self, *, documento, version_doc, usuario, ip=None, user_agent=None):
        self._validate_publish_conditions(documento, version_doc, usuario)
        publicacion = self.publication_for_version(version_doc)
        if publicacion and publicacion.estado == PUBLICACION_ACTIVA and publicacion.activa:
            return publicacion

        process = self._completed_signature_process(version_doc)
        final_pdf = process.pdf_final
        previous = documento.version_vigente if documento.version_vigente_id else None
        previous_publication = self.active_publication_for_document(documento)
        now = _now()
        if not publicacion or not publicacion.pdf_qr_artifact or not publicacion.qr_embebido:
            raise DocumentPublicationError("La publicacion debe estar preparada con QR embebido antes de publicarse.")
        publicacion.estado = PUBLICACION_ACTIVA
        publicacion.activa = True
        publicacion.vigente_desde = now
        publicacion.publicado_por_id = usuario.id
        publicacion.pdf_publicado_id = final_pdf.id
        publicacion.pdf_fuente_storage_key = final_pdf.storage_path
        publicacion.pdf_fuente_sha256 = final_pdf.archivo_sha256
        if not publicacion.qr_payload:
            publicacion.qr_payload = self._absolute_publication_url(publicacion)

        version_doc.estado = ESTADO_VIGENTE
        version_doc.vigente_desde = now
        version_doc.publicado_por_id = usuario.id
        documento.estado = ESTADO_VIGENTE
        documento.version_vigente_id = version_doc.id
        documento.version_actual = version_doc.version

        if previous and previous.id != version_doc.id:
            previous.estado = ESTADO_OBSOLETO
            previous.fecha_obsolescencia = now
            previous.obsoletado_por_id = usuario.id
            previous.motivo_obsolescencia = f"Sustituida por la version vigente {version_doc.version}."
            self._record_event(documento, previous, usuario, "VERSION_ANTERIOR_OBSOLETA", previous.motivo_obsolescencia, ip, user_agent)
        if previous_publication and previous_publication.id != publicacion.id:
            previous_publication.estado = PUBLICACION_OBSOLETA
            previous_publication.activa = False

        self._record_event(documento, version_doc, usuario, "PUBLICAR_VIGENTE", "Documento publicado como vigente.", ip, user_agent)
        DocumentDistributionService().enqueue_publication_deliveries(publicacion=publicacion)
        self._record_event(documento, version_doc, usuario, "DISTRIBUCION_ENCOLADA", "Distribucion documental encolada.", ip, user_agent)
        db.session.commit()
        return publicacion

    def revoke_publication(self, *, publicacion, usuario, motivo, ip=None, user_agent=None):
        if not user_has_permission(usuario, REVOKE_PERMISSION):
            raise DocumentPublicationError("No tienes permiso para revocar publicaciones.")
        if usuario.empresa_id != publicacion.empresa_id:
            raise DocumentPublicationError("No puedes revocar publicaciones de otra empresa.")
        if not (motivo or "").strip():
            raise DocumentPublicationError("El motivo de revocacion es obligatorio.")
        publicacion.estado = PUBLICACION_REVOCADA
        publicacion.activa = False
        publicacion.revocado_en = _now()
        publicacion.revocado_por_id = usuario.id
        publicacion.motivo_revocacion = motivo.strip()
        self._record_event(publicacion.documento, publicacion.documento_version, usuario, "PUBLICACION_REVOCADA", motivo, ip, user_agent)
        db.session.commit()
        return publicacion

    def _get_or_create_prepared_publication(self, *, documento, version_doc, usuario, original_pdf):
        publicacion = self.publication_for_version(version_doc)
        if publicacion:
            return publicacion
        publicacion = DocumentoPublicacion(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            public_id=uuid4().hex,
            token=secrets.token_urlsafe(32),
            modo_acceso=(self.app.config.get("DOCUMENT_PUBLICATION_DEFAULT_ACCESS") or PUBLICACION_ACCESO_AUTENTICADO),
            estado=PUBLICACION_PREPARADA,
            activa=False,
            pdf_aprobado_original_id=original_pdf.id if original_pdf else None,
            pdf_fuente_storage_key=original_pdf.storage_path if original_pdf else None,
            pdf_fuente_sha256=original_pdf.archivo_sha256 if original_pdf else None,
            qr_embebido=False,
            metadata_json={},
        )
        db.session.add(publicacion)
        db.session.flush()
        self._refresh_publication_url(publicacion)
        self._record_event(documento, version_doc, usuario, "PUBLICACION_PREPARADA", "Publicacion preparada.")
        return publicacion

    def _validate_publish_conditions(self, documento, version_doc, usuario):
        self._validate_same_company(documento, version_doc, usuario)
        if not user_has_permission(usuario, PUBLISH_PERMISSION):
            raise DocumentPublicationError("No tienes permiso para publicar documentos vigentes.")
        if version_doc.estado not in (ESTADO_APROBADO, ESTADO_VIGENTE):
            raise DocumentPublicationError("Solo una version APROBADA puede publicarse como vigente.")
        if version_doc.estado == ESTADO_VIGENTE:
            raise DocumentPublicationError("La version ya esta VIGENTE.")
        approved_pdf = self.pdf_service.available_artifact_for_version(version_doc)
        if not approved_pdf:
            raise DocumentPublicationError("No existe PDF aprobado.")
        process = self._completed_signature_process(version_doc)
        if not process.pdf_final:
            raise DocumentPublicationError("No existe PDF final firmado.")
        publicacion = self.publication_for_version(version_doc)
        if not publicacion or not publicacion.pdf_qr_artifact or not publicacion.qr_embebido:
            raise DocumentPublicationError("No existe publicacion PREPARADA con PDF_APROBADO_CON_QR.")
        if process.pdf_origen_id != publicacion.pdf_qr_artifact_id:
            raise DocumentPublicationError("El proceso de firmas no partio del PDF aprobado con QR.")
        active_same_version = DocumentoPublicacion.query.filter_by(
            empresa_id=documento.empresa_id,
            documento_version_id=version_doc.id,
            estado=PUBLICACION_ACTIVA,
            activa=True,
        ).first()
        if active_same_version:
            raise DocumentPublicationError("Ya existe una publicacion activa para esta version.")

    def _validate_same_company(self, documento, version_doc, usuario):
        if not usuario or usuario.empresa_id != documento.empresa_id or version_doc.empresa_id != documento.empresa_id:
            raise DocumentPublicationError("La version no pertenece a la empresa del usuario.")
        if version_doc.documento_id != documento.id:
            raise DocumentPublicationError("La version no pertenece al documento indicado.")

    def _latest_signature_process(self, version_doc):
        return (
            DocumentoFirmaProceso.query
            .filter_by(empresa_id=version_doc.empresa_id, documento_version_id=version_doc.id)
            .order_by(DocumentoFirmaProceso.solicitado_en.desc(), DocumentoFirmaProceso.id.desc())
            .first()
        )

    def _completed_signature_process(self, version_doc):
        process = (
            DocumentoFirmaProceso.query
            .filter_by(empresa_id=version_doc.empresa_id, documento_version_id=version_doc.id, estado=FIRMA_PROCESO_COMPLETADO)
            .order_by(DocumentoFirmaProceso.completado_en.desc(), DocumentoFirmaProceso.id.desc())
            .first()
        )
        if not process:
            raise DocumentPublicationError("El proceso de firmas debe estar COMPLETADO.")
        return process

    def _absolute_publication_url(self, publicacion):
        path = (
            url_for("documentacion_publicaciones.ver_publicacion", public_id=publicacion.public_id)
            if has_request_context()
            else f"/documentos/publicados/{publicacion.public_id}"
        )
        base = (self.app.config.get("DOCUMENT_PUBLICATION_BASE_URL") or "").strip().rstrip("/")
        warning = self._validate_publication_base_url(base)
        if not base:
            if self._environment() == "testing":
                base = "https://labzeniso.test"
            else:
                raise DocumentPublicationError("DOCUMENT_PUBLICATION_BASE_URL es obligatorio para generar el QR canonico.")
        if warning:
            publicacion.metadata_json = {
                **(publicacion.metadata_json or {}),
                "canonical_url_warning": warning,
            }
        return f"{base}{path}"

    def _refresh_publication_url(self, publicacion):
        publicacion.qr_payload = self._absolute_publication_url(publicacion)
        return publicacion.qr_payload

    def _validate_publication_base_url(self, base):
        if not base:
            return None
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DocumentPublicationError("DOCUMENT_PUBLICATION_BASE_URL debe ser una URL absoluta http(s).")
        hostname = (parsed.hostname or "").lower()
        environment = self._environment()
        allow_temporary = bool(self.app.config.get("DOCUMENT_PUBLICATION_ALLOW_TEMPORARY_URLS"))
        is_local = hostname in {"localhost", "127.0.0.1"} or hostname.startswith("127.")
        is_temporary = "trycloudflare.com" in hostname
        if environment in {"production", "prod", "beta"} and parsed.scheme != "https":
            raise DocumentPublicationError("DOCUMENT_PUBLICATION_BASE_URL debe usar HTTPS en beta/produccion.")
        if environment in {"production", "prod", "beta"} and (is_local or is_temporary) and not allow_temporary:
            raise DocumentPublicationError("DOCUMENT_PUBLICATION_BASE_URL no puede ser localhost/127/trycloudflare en beta/produccion.")
        if (is_local or is_temporary) and not allow_temporary and environment not in {"development", "testing"}:
            raise DocumentPublicationError("Las URLs temporales o locales no estan permitidas para QR canonico.")
        if (is_local or is_temporary) and environment in {"development", "testing"}:
            return "URL local/temporal permitida solo para desarrollo; no usar en beta/produccion."
        return None

    def _environment(self):
        return (self.app.config.get("APP_ENV") or self.app.config.get("ENV") or "development").strip().lower()

    def _record_event(self, documento, version_doc, usuario, accion, comentario="", ip=None, user_agent=None):
        db.session.add(DocumentoAprobacion(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            usuario_id=usuario.id,
            accion=accion,
            estado_anterior=version_doc.estado,
            estado_nuevo=version_doc.estado,
            fecha_accion=_now(),
            comentario=(comentario or "").strip() or None,
            ip=ip,
            user_agent=user_agent,
        ))
