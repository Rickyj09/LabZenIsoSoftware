import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from app.extensions import db
from app.models.documentos import (
    ARTEFACTO_PDF_APROBADO,
    ARTEFACTO_PDF_FIRMADO_FINAL,
    CLASIFICACION_CONTROL_FORMATO,
    CLASIFICACION_CONTROL_INTERNO,
    DOCUMENTO_VIGOR_EXTERNO,
    DOCUMENTO_VIGOR_FORMATO,
    DOCUMENTO_VIGOR_INTERNO,
    ESTADO_APROBADO,
    ESTADO_OBSOLETO,
    ESTADO_VIGENTE,
    FIRMA_PROCESO_COMPLETADO,
    PUBLICACION_ACTIVA,
    PUBLICACION_OBSOLETA,
    Documento,
    DocumentoAprobacion,
    DocumentoFirmaProceso,
    DocumentoPublicacion,
    DocumentoSnapshot,
    DocumentoVersion,
    DocumentoVigorCatalogo,
)
from app.models.seguridad import Usuario
from app.services.document_current_catalog_sync_service import (
    DocumentCurrentCatalogSyncError,
    DocumentCurrentCatalogSyncService,
)
from app.services.document_publication_service import DocumentPublicationError, DocumentPublicationService


_fixture_path = Path(__file__).with_name("test_document_publication.py")
_spec = importlib.util.spec_from_file_location("_document_publication_fixture", _fixture_path)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


class DocumentCurrentCatalogSyncTest(_fixture.DocumentPublicationTest):
    def publish_base_document(self):
        self.complete_signature_process()
        return DocumentPublicationService().publish_as_current(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )

    def create_second_version(self):
        document = db.session.get(Documento, 501)
        version = DocumentoVersion(
            id=1502,
            empresa_id=101,
            documento_id=501,
            version="2",
            estado=ESTADO_APROBADO,
            cambios="Nueva version vigente",
            elaborado_por_id=201,
            revisado_por_id=202,
            aprobado_por_id=201,
            fecha_aprobacion=datetime.now(timezone.utc),
        )
        snapshot = DocumentoSnapshot(
            id=2502,
            empresa_id=101,
            public_id="snapshot-pub-v2",
            documento_id=501,
            documento_version_id=1502,
            secuencia=1,
            ciclo_revision=1,
            tipo="APROBADO",
            estado="DISPONIBLE",
            storage_path="dummy-v2.docx",
            archivo_nombre_interno="dummy-v2.docx",
            archivo_nombre_original="dummy-v2.docx",
            archivo_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            archivo_size=10,
            archivo_sha256="c" * 64,
            hash_origen="d" * 64,
            creado_por_id=201,
            creado_en=datetime.now(timezone.utc),
            inmutable=True,
        )
        db.session.add_all([version, snapshot])
        db.session.flush()
        self.store_pdf_artifact(version=version, snapshot=snapshot, text="aprobado-v2", tipo=ARTEFACTO_PDF_APROBADO)
        db.session.commit()

        prepared = DocumentPublicationService().prepare_publication_for_signature(
            documento=document,
            version_doc=version,
            usuario=db.session.get(Usuario, 201),
        )
        final = self.store_pdf_artifact(
            version=version,
            snapshot=snapshot,
            text="firmado-final-v2",
            tipo=ARTEFACTO_PDF_FIRMADO_FINAL,
            source_artifact=prepared.artifact,
        )
        db.session.add(DocumentoFirmaProceso(
            empresa_id=101,
            public_id="firma-completa-v2",
            documento_id=501,
            documento_version_id=1502,
            pdf_origen_id=prepared.artifact.id,
            pdf_final_id=final.id,
            estado=FIRMA_PROCESO_COMPLETADO,
            solicitado_por_id=201,
            solicitado_en=datetime.now(timezone.utc),
            completado_en=datetime.now(timezone.utc),
        ))
        db.session.commit()
        return version

    def test_publish_internal_document_creates_current_catalog_entry(self):
        publication = self.publish_base_document()
        row = DocumentoVigorCatalogo.query.filter_by(documento_id=501, activo=True).one()

        self.assertEqual(row.tipo_listado, DOCUMENTO_VIGOR_INTERNO)
        self.assertEqual(row.documento_version_id, 1501)
        self.assertEqual(row.documento_publicacion_id, publication.id)
        self.assertEqual(row.revision, "1")
        self.assertEqual(row.fecha_vigencia, publication.vigente_desde.date())
        self.assertIsNotNone(row.sincronizado_en)

    def test_publish_format_document_creates_format_catalog_entry(self):
        document = db.session.get(Documento, 501)
        document.clasificacion_control = CLASIFICACION_CONTROL_FORMATO
        db.session.commit()

        self.publish_base_document()
        row = DocumentoVigorCatalogo.query.filter_by(documento_id=501, activo=True).one()

        self.assertEqual(row.tipo_listado, DOCUMENTO_VIGOR_FORMATO)
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_FORMATO)

    def test_pending_classification_does_not_sync_silently_and_rolls_back_publication(self):
        document = db.session.get(Documento, 501)
        document.clasificacion_control = None
        db.session.commit()
        self.complete_signature_process()

        with self.assertRaisesRegex(DocumentPublicationError, "clasificacion de control INTERNO o FORMATO"):
            DocumentPublicationService().publish_as_current(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                usuario=db.session.get(Usuario, 201),
            )

        db.session.expire_all()
        self.assertEqual(db.session.get(Documento, 501).version_vigente_id, 1500)
        self.assertEqual(db.session.get(DocumentoVersion, 1501).estado, ESTADO_APROBADO)
        self.assertEqual(DocumentoPublicacion.query.filter_by(estado=PUBLICACION_ACTIVA, activa=True).count(), 0)
        self.assertEqual(DocumentoVigorCatalogo.query.count(), 0)

    def test_manual_classification_is_not_overwritten(self):
        document = db.session.get(Documento, 501)
        document.clasificacion_control = CLASIFICACION_CONTROL_FORMATO
        document.tipo_documento = "PROCEDIMIENTO"
        db.session.commit()

        self.publish_base_document()

        self.assertEqual(db.session.get(Documento, 501).clasificacion_control, CLASIFICACION_CONTROL_FORMATO)
        self.assertEqual(DocumentoVigorCatalogo.query.one().tipo_listado, DOCUMENTO_VIGOR_FORMATO)

    def test_repeated_sync_is_idempotent_and_records_no_change(self):
        publication = self.publish_base_document()
        service = DocumentCurrentCatalogSyncService()
        row = service.sync_current_publication(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            publicacion=publication,
            usuario=db.session.get(Usuario, 201),
        )
        db.session.commit()

        self.assertEqual(DocumentoVigorCatalogo.query.filter_by(documento_id=501).count(), 1)
        self.assertEqual(row.documento_publicacion_id, publication.id)
        self.assertEqual(
            DocumentoAprobacion.query.filter_by(accion="CATALOGO_VIGENTE_SIN_CAMBIOS").count(),
            1,
        )

    def test_new_current_version_updates_catalog_and_keeps_publication_history(self):
        first_publication = self.publish_base_document()
        first_row_id = DocumentoVigorCatalogo.query.one().id
        second_version = self.create_second_version()

        second_publication = DocumentPublicationService().publish_as_current(
            documento=db.session.get(Documento, 501),
            version_doc=second_version,
            usuario=db.session.get(Usuario, 201),
        )
        row = DocumentoVigorCatalogo.query.filter_by(documento_id=501, activo=True).one()

        self.assertEqual(row.id, first_row_id)
        self.assertEqual(row.documento_version_id, second_version.id)
        self.assertEqual(row.documento_publicacion_id, second_publication.id)
        self.assertEqual(db.session.get(DocumentoVersion, 1501).estado, ESTADO_OBSOLETO)
        self.assertEqual(db.session.get(DocumentoVersion, 1502).estado, ESTADO_VIGENTE)
        self.assertEqual(db.session.get(DocumentoPublicacion, first_publication.id).estado, PUBLICACION_OBSOLETA)
        self.assertFalse(db.session.get(DocumentoPublicacion, first_publication.id).activa)
        self.assertEqual(DocumentoPublicacion.query.filter_by(documento_id=501).count(), 2)

    def test_external_catalog_rows_are_not_removed_or_reclassified(self):
        external = DocumentoVigorCatalogo(
            empresa_id=101,
            tipo_listado=DOCUMENTO_VIGOR_EXTERNO,
            clave_importacion="external-key",
            identidad_estable="CODIGO:EXT-001#1",
            ordinal_identidad=1,
            codigo="EXT-001",
            titulo="Documento externo existente",
            activo=True,
            documento_id=501,
            fuente_archivo="cliente.xlsx",
            fuente_hoja="DOCUMENTOS EXTERNOS",
            fuente_fila=42,
            importado_en=datetime.now(timezone.utc),
        )
        db.session.add(external)
        db.session.commit()

        self.publish_base_document()
        db.session.refresh(external)

        self.assertTrue(external.activo)
        self.assertEqual(external.tipo_listado, DOCUMENTO_VIGOR_EXTERNO)

    def test_sync_is_tenant_scoped(self):
        publication = self.publish_base_document()

        with self.assertRaisesRegex(DocumentCurrentCatalogSyncError, "usuario no pertenece"):
            DocumentCurrentCatalogSyncService().sync_current_publication(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                publicacion=publication,
                usuario=db.session.get(Usuario, 203),
            )

        self.assertEqual(DocumentoVigorCatalogo.query.filter_by(empresa_id=102).count(), 0)

    def test_sync_rejects_mismatched_document_version_and_publication_tenants(self):
        publication = self.publish_base_document()
        other_doc = Documento(
            id=601,
            empresa_id=102,
            codigo="DOC-OTRA",
            titulo="Otra empresa",
            tipo_documento="PROCEDIMIENTO",
            clasificacion_control=CLASIFICACION_CONTROL_INTERNO,
            estado=ESTADO_VIGENTE,
            version_actual="1",
            elaborado_por_id=203,
        )
        other_version = DocumentoVersion(
            id=1601,
            empresa_id=102,
            documento_id=601,
            version="1",
            estado=ESTADO_VIGENTE,
            elaborado_por_id=203,
        )
        other_doc.version_vigente_id = other_version.id
        db.session.add_all([other_doc, other_version])
        db.session.commit()

        with self.assertRaisesRegex(DocumentCurrentCatalogSyncError, "version vigente no pertenece"):
            DocumentCurrentCatalogSyncService().sync_current_publication(
                documento=db.session.get(Documento, 501),
                version_doc=other_version,
                publicacion=publication,
                usuario=db.session.get(Usuario, 201),
            )

        with self.assertRaisesRegex(DocumentCurrentCatalogSyncError, "publicacion no pertenece"):
            DocumentCurrentCatalogSyncService().sync_current_publication(
                documento=other_doc,
                version_doc=other_version,
                publicacion=publication,
                usuario=db.session.get(Usuario, 203),
            )

    def test_catalog_sync_audit_is_recorded(self):
        self.publish_base_document()
        actions = [event.accion for event in DocumentoAprobacion.query.filter_by(documento_id=501).all()]

        self.assertIn("CATALOGO_VIGENTE_ALTA", actions)
        self.assertIn("PUBLICAR_VIGENTE", actions)
        self.assertIn("DISTRIBUCION_ENCOLADA", actions)
