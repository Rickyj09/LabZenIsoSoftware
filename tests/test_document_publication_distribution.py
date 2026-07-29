import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from app.extensions import db
from app.models.documentos import (
    ARTEFACTO_PDF_APROBADO,
    ARTEFACTO_PDF_APROBADO_CON_QR,
    FIRMA_PROCESO_EN_FIRMA,
    Documento,
    DocumentoArtefacto,
    DocumentoFirmaProceso,
    DocumentoPublicacion,
    DocumentoVersion,
)
from app.models.seguridad import Usuario
from app.services.document_publication_service import DocumentPublicationError, DocumentPublicationService
from app.services.document_qr_service import DocumentQrService


_fixture_path = Path(__file__).with_name("test_document_publication.py")
_spec = importlib.util.spec_from_file_location("_document_publication_fixture", _fixture_path)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


class DocumentPublicationDistributionTest(_fixture.DocumentPublicationTest):
    def test_prepare_publication_for_signature_is_idempotent_and_returns_qr_artifact(self):
        service = DocumentPublicationService()
        first = service.prepare_publication_for_signature(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )
        second = service.prepare_publication_for_signature(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )

        self.assertEqual(first.artifact.id, second.artifact.id)
        self.assertEqual(first.artifact.tipo, ARTEFACTO_PDF_APROBADO_CON_QR)
        self.assertEqual(DocumentoPublicacion.query.count(), 1)
        self.assertEqual(
            DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_APROBADO_CON_QR).count(),
            1,
        )

    def test_prepare_refuses_to_regenerate_after_legacy_signature_process_started(self):
        db.session.add(DocumentoFirmaProceso(
            empresa_id=101,
            public_id="legacy-process",
            documento_id=501,
            documento_version_id=1501,
            pdf_origen_id=self.approved_artifact.id,
            estado=FIRMA_PROCESO_EN_FIRMA,
            solicitado_por_id=201,
            solicitado_en=datetime.now(timezone.utc),
        ))
        db.session.commit()

        with self.assertRaisesRegex(DocumentPublicationError, "no se puede regenerar"):
            DocumentPublicationService().prepare_publication_for_signature(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                usuario=db.session.get(Usuario, 201),
            )

    def test_publish_requires_signature_process_started_from_qr_pdf(self):
        process = self.complete_signature_process()
        process.pdf_origen_id = self.approved_artifact.id
        db.session.commit()

        with self.assertRaisesRegex(DocumentPublicationError, "no partio del PDF aprobado con QR"):
            DocumentPublicationService().publish_as_current(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                usuario=db.session.get(Usuario, 201),
            )

    def test_production_rejects_local_or_temporary_canonical_url(self):
        self.app.config.update(
            APP_ENV="production",
            DOCUMENT_PUBLICATION_BASE_URL="http://localhost:5000",
            DOCUMENT_PUBLICATION_ALLOW_TEMPORARY_URLS=False,
        )

        with self.assertRaisesRegex(DocumentPublicationError, "HTTPS"):
            DocumentPublicationService().prepare_publication_for_signature(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                usuario=db.session.get(Usuario, 201),
            )

    def test_development_local_url_is_allowed_with_visible_warning(self):
        self.app.config.update(
            APP_ENV="development",
            DOCUMENT_PUBLICATION_BASE_URL="http://localhost:5000",
            DOCUMENT_PUBLICATION_ALLOW_TEMPORARY_URLS=False,
        )

        prepared = DocumentPublicationService().prepare_publication_for_signature(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )

        self.assertIn("http://localhost:5000/documentos/publicados/", prepared.publicacion.qr_payload)
        self.assertIn("canonical_url_warning", prepared.publicacion.metadata_json)

    def test_qr_profile_override_for_procedimiento(self):
        self.app.config.update(
            DOCUMENT_PUBLICATION_QR_PROCEDIMIENTO_PAGE="last",
            DOCUMENT_PUBLICATION_QR_PROCEDIMIENTO_BOX="0.70,0.70,0.90,0.90",
        )

        box = DocumentQrService().publication_box(tipo_documento="PROCEDIMIENTO")

        self.assertEqual(box.page_selector, "last")
        self.assertEqual(box.normalized_box, (0.70, 0.70, 0.90, 0.90))

    def test_original_preview_source_was_pdf_aprobado_without_qr(self):
        original = db.session.get(DocumentoArtefacto, self.approved_artifact.id)

        self.assertEqual(original.tipo, ARTEFACTO_PDF_APROBADO)
        self.assertIsNone(DocumentoPublicacion.query.first())
