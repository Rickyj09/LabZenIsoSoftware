import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import (
    ARTEFACTO_DISPONIBLE,
    ARTEFACTO_PDF_APROBADO,
    ARTEFACTO_PDF_APROBADO_CON_QR,
    ARTEFACTO_PDF_FIRMADO_FINAL,
    CLASIFICACION_CONTROL_INTERNO,
    ESTADO_APROBADO,
    ESTADO_OBSOLETO,
    ESTADO_SUSTITUIDO,
    ESTADO_VIGENTE,
    FIRMA_PROCESO_COMPLETADO,
    PUBLICACION_ACCESO_TOKEN_PUBLICO,
    PUBLICACION_ACTIVA,
    PUBLICACION_OBSOLETA,
    PUBLICACION_PREPARADA,
    ENTREGA_OMITIDO,
    Documento,
    DocumentoAprobacion,
    DocumentoArtefacto,
    DocumentoDistribucionDestinatario,
    DocumentoDistribucionEntrega,
    DocumentoFirmaProceso,
    DocumentoPublicacion,
    DocumentoSnapshot,
    DocumentoVersion,
    DocumentoVigorCatalogo,
)
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_distribution_service import DocumentDistributionService
from app.services.document_pdf_service import DocumentPdfService
from app.services.document_publication_service import DocumentPublicationError, DocumentPublicationService, PUBLISH_PERMISSION
from app.services.storage_service import file_digest_and_size, resolve_document_path, store_pdf_artifact_copy, store_signed_pdf_artifact_copy


class DocumentPublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DOCUMENT_STORAGE_ROOT": self.temp_directory.name,
            "DOCUMENT_LEGACY_STORAGE_ROOT": self.temp_directory.name,
            "ONLYOFFICE_ENABLED": False,
            "ONLYOFFICE_CONVERSION_ENABLED": False,
            "ONLYOFFICE_PDF_MAX_BYTES": 5 * 1024 * 1024,
            "DOCUMENT_PUBLICATION_BASE_URL": "https://labzeniso.test",
            "DOCUMENT_DISTRIBUTION_EMAIL_ENABLED": False,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.next_id = 50000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        self.seed()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def minimal_pdf(self, text="LabZenISO"):
        stream = b"BT /F1 12 Tf 72 120 Td (" + text.encode("ascii", "ignore") + b") Tj ET\n"
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >> endobj\n",
            b"4 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"endstream endobj\n",
        ]
        pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        offsets = [0]
        for obj in objects:
            offsets.append(len(pdf))
            pdf += obj
        xref_offset = len(pdf)
        xref_entries = [b"0000000000 65535 f \n"] + [f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]]
        pdf += b"xref\n0 5\n" + b"".join(xref_entries)
        pdf += b"trailer << /Root 1 0 R /Size 5 >>\n"
        pdf += b"startxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF\n"
        return pdf

    def seed(self):
        db.session.add_all([Empresa(id=101, nombre="Empresa uno"), Empresa(id=102, nombre="Empresa dos")])
        users = [
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="calidad@pub.test", username="calidad", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Interno", apellido="Uno", email="interno@pub.test", username="interno", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=102, nombre="Otro", apellido="Dos", email="otro@pub.test", username="otro", password_hash="x", activo=True),
        ]
        permissions = [
            Permiso(id=1001, codigo="documentos.ver", nombre="Ver", modulo="documentos"),
            Permiso(id=1002, codigo="documentos.descargar", nombre="Descargar", modulo="documentos"),
            Permiso(id=1003, codigo=PUBLISH_PERMISSION, nombre="Publicar", modulo="documentos"),
            Permiso(id=1004, codigo="documentos.distribucion.gestionar", nombre="Gestionar distribucion", modulo="documentos"),
        ]
        role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        db.session.add_all([*users, *permissions, role])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=role.id, permiso_id=1001),
            RolPermiso(id=3002, rol_id=role.id, permiso_id=1002),
            RolPermiso(id=3003, rol_id=role.id, permiso_id=1003),
            RolPermiso(id=3004, rol_id=role.id, permiso_id=1004),
            UsuarioRol(id=4001, usuario_id=201, rol_id=role.id),
        ])
        document = Documento(id=501, empresa_id=101, codigo="DOC-PUB", titulo="Documento publicado", tipo_documento="PROCEDIMIENTO", clasificacion_control=CLASIFICACION_CONTROL_INTERNO, proceso="Calidad", estado=ESTADO_APROBADO, version_actual="1", elaborado_por_id=201)
        previous = DocumentoVersion(id=1500, empresa_id=101, documento_id=501, version="0", estado=ESTADO_APROBADO, elaborado_por_id=201, revisado_por_id=202, aprobado_por_id=201)
        version = DocumentoVersion(id=1501, empresa_id=101, documento_id=501, version="1", estado=ESTADO_APROBADO, cambios="Cambio controlado", elaborado_por_id=201, revisado_por_id=202, aprobado_por_id=201, fecha_aprobacion=datetime.now(timezone.utc))
        document.version_vigente_id = previous.id
        snapshot = DocumentoSnapshot(id=2501, empresa_id=101, public_id="snapshot-pub", documento_id=501, documento_version_id=1501, secuencia=1, ciclo_revision=1, tipo="APROBADO", estado="DISPONIBLE", storage_path="dummy.docx", archivo_nombre_interno="dummy.docx", archivo_nombre_original="dummy.docx", archivo_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", archivo_size=10, archivo_sha256="a" * 64, hash_origen="b" * 64, creado_por_id=201, creado_en=datetime.now(timezone.utc), inmutable=True)
        db.session.add_all([document, previous, version, snapshot])
        db.session.flush()
        self.approved_artifact = self.store_pdf_artifact(version=version, snapshot=snapshot, text="aprobado", tipo=ARTEFACTO_PDF_APROBADO)
        db.session.commit()

    def store_pdf_artifact(self, *, version, snapshot, text, tipo, source_artifact=None):
        source_path = Path(self.temp_directory.name) / f"{tipo}-{text}.pdf"
        source_path.write_bytes(self.minimal_pdf(text))
        validation = DocumentPdfService().validate_pdf_file(source_path, allow_signature_forms=True)
        if tipo == ARTEFACTO_PDF_FIRMADO_FINAL:
            stored = store_signed_pdf_artifact_copy(source_path=source_path, documento=version.documento, version_doc=version, source_artifact=source_artifact, signed_revision=3, final=True, expected_sha256=validation.sha256)
        else:
            stored = store_pdf_artifact_copy(source_path=source_path, documento=version.documento, version_doc=version, source_snapshot=snapshot, expected_sha256=validation.sha256)
        artifact = DocumentoArtefacto(
            empresa_id=version.empresa_id,
            public_id=f"{tipo}-{text}",
            documento_id=version.documento_id,
            documento_version_id=version.id,
            source_snapshot_id=snapshot.id,
            source_artifact_id=source_artifact.id if source_artifact else None,
            tipo=tipo,
            estado=ARTEFACTO_DISPONIBLE,
            storage_path=stored.storage_path,
            archivo_nombre_interno=stored.stored_name,
            archivo_nombre_visible=f"{tipo}.pdf",
            archivo_mime="application/pdf",
            archivo_size=stored.size,
            archivo_sha256=stored.sha256,
            source_snapshot_sha256=snapshot.archivo_sha256,
            source_artifact_sha256=source_artifact.archivo_sha256 if source_artifact else None,
            page_count=validation.page_count,
            signature_count=3 if tipo == ARTEFACTO_PDF_FIRMADO_FINAL else 0,
            provider="test",
            creado_por_id=201,
            creado_en=datetime.now(timezone.utc),
            disponible_en=datetime.now(timezone.utc),
            inmutable=True,
            metadata_json={},
        )
        db.session.add(artifact)
        db.session.flush()
        return artifact

    def complete_signature_process(self):
        version = db.session.get(DocumentoVersion, 1501)
        prepared = DocumentPublicationService().prepare_publication_for_signature(
            documento=db.session.get(Documento, 501),
            version_doc=version,
            usuario=db.session.get(Usuario, 201),
        )
        final = self.store_pdf_artifact(version=version, snapshot=db.session.get(DocumentoSnapshot, 2501), text="firmado-final", tipo=ARTEFACTO_PDF_FIRMADO_FINAL, source_artifact=prepared.artifact)
        process = DocumentoFirmaProceso(
            empresa_id=101,
            public_id="firma-completa",
            documento_id=501,
            documento_version_id=1501,
            pdf_origen_id=prepared.artifact.id,
            pdf_final_id=final.id,
            estado=FIRMA_PROCESO_COMPLETADO,
            solicitado_por_id=201,
            solicitado_en=datetime.now(timezone.utc),
            completado_en=datetime.now(timezone.utc),
        )
        db.session.add(process)
        db.session.commit()
        return process

    def test_prepare_publication_generates_qr_and_separate_pdf_without_touching_original(self):
        original_path = resolve_document_path(self.approved_artifact.storage_path)
        original_hash, _size = file_digest_and_size(original_path)
        artifact = DocumentPublicationService().prepare_publication_artifact_for_signature(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )
        publication = DocumentoPublicacion.query.filter_by(documento_version_id=1501).one()

        self.assertEqual(artifact.tipo, ARTEFACTO_PDF_APROBADO_CON_QR)
        self.assertNotEqual(artifact.archivo_sha256, self.approved_artifact.archivo_sha256)
        self.assertEqual(file_digest_and_size(original_path)[0], original_hash)
        self.assertIn("/documentos/publicados/", publication.qr_payload)
        self.assertNotIn(str(self.temp_directory.name), publication.qr_payload)
        self.assertTrue(publication.qr_storage_key.endswith(".png"))
        self.assertEqual(len(publication.qr_sha256), 64)
        self.assertEqual(publication.estado, PUBLICACION_PREPARADA)
        self.assertTrue(publication.qr_embebido)

    def test_publish_as_current_creates_distribution_snapshot_and_obsoletes_previous(self):
        self.complete_signature_process()
        distribution = DocumentDistributionService()
        distribution.add_internal_recipient(documento=db.session.get(Documento, 501), usuario_destino_id=202, usuario_actor=db.session.get(Usuario, 201))
        distribution.add_external_recipient(documento=db.session.get(Documento, 501), nombre="Externo", email="externo@pub.test", usuario_actor=db.session.get(Usuario, 201))

        publication = DocumentPublicationService().publish_as_current(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )

        self.assertEqual(publication.estado, PUBLICACION_ACTIVA)
        self.assertTrue(publication.activa)
        self.assertEqual(db.session.get(DocumentoVersion, 1501).estado, ESTADO_VIGENTE)
        self.assertEqual(db.session.get(DocumentoVersion, 1500).estado, ESTADO_OBSOLETO)
        publish_event = DocumentoAprobacion.query.filter_by(
            documento_version_id=1501,
            accion="PUBLICAR_VIGENTE",
        ).one()
        self.assertEqual(publish_event.estado_anterior, ESTADO_APROBADO)
        self.assertEqual(publish_event.estado_nuevo, ESTADO_VIGENTE)
        obsolete_event = DocumentoAprobacion.query.filter_by(
            documento_version_id=1500,
            accion="VERSION_ANTERIOR_OBSOLETA",
        ).one()
        self.assertEqual(obsolete_event.estado_anterior, ESTADO_APROBADO)
        self.assertEqual(obsolete_event.estado_nuevo, ESTADO_OBSOLETO)
        catalog_row = DocumentoVigorCatalogo.query.filter_by(documento_id=501).one()
        self.assertEqual(catalog_row.documento_version_id, 1501)
        self.assertEqual(catalog_row.documento_publicacion_id, publication.id)
        self.assertIsNotNone(catalog_row.sincronizado_en)
        self.assertEqual(DocumentoDistribucionEntrega.query.filter_by(publicacion_id=publication.id).count(), 2)
        DocumentDistributionService().enqueue_publication_deliveries(publicacion=publication)
        self.assertEqual(DocumentoDistribucionEntrega.query.filter_by(publicacion_id=publication.id).count(), 2)
        with self.assertRaisesRegex(DocumentPublicationError, "version ya esta VIGENTE"):
            DocumentPublicationService().publish_as_current(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                usuario=db.session.get(Usuario, 201),
            )
        self.assertEqual(DocumentoVigorCatalogo.query.filter_by(documento_id=501).count(), 1)
        self.assertEqual(
            DocumentoAprobacion.query.filter_by(
                documento_version_id=1501,
                accion="PUBLICAR_VIGENTE",
            ).count(),
            1,
        )

    def test_publish_as_current_obsoletes_previously_active_publication_version_even_when_replaced(self):
        previous = db.session.get(DocumentoVersion, 1500)
        version = db.session.get(DocumentoVersion, 1501)
        document = db.session.get(Documento, 501)
        now = datetime.now(timezone.utc)
        previous.estado = ESTADO_SUSTITUIDO
        document.version_vigente_id = version.id
        document.version_actual = version.version
        previous_publication = DocumentoPublicacion(
            empresa_id=101,
            documento_id=document.id,
            documento_version_id=previous.id,
            public_id="pub-prev-active",
            token="token-prev-active",
            estado=PUBLICACION_ACTIVA,
            activa=True,
            qr_payload="https://labzeniso.test/documentos/publicados/pub-prev-active",
            qr_embebido=True,
            pdf_publicado_id=None,
            vigente_desde=now,
        )
        db.session.add(previous_publication)
        db.session.flush()
        catalog_row = DocumentoVigorCatalogo(
            empresa_id=101,
            tipo_listado="INTERNO",
            clave_importacion="INTERNO::DOCUMENTO:501#1",
            identidad_estable="DOCUMENTO:501#1",
            ordinal_identidad=1,
            codigo=document.codigo,
            titulo=document.titulo,
            revision=previous.version,
            fecha_vigencia=now.date(),
            acceso_documento=previous_publication.qr_payload,
            medio="PDF",
            seccion=document.proceso,
            activo=True,
            documento_id=document.id,
            documento_version_id=previous.id,
            documento_publicacion_id=previous_publication.id,
            fuente_archivo="PUBLICACION_AUTOMATICA",
            fuente_hoja="publish_as_current",
            fuente_fila=1,
            importado_por_id=201,
            importado_en=now,
            actualizado_por_id=201,
            actualizado_en=now,
            sincronizado_por_id=201,
            sincronizado_en=now,
        )
        db.session.add(catalog_row)
        db.session.commit()
        first_row_id = catalog_row.id
        self.complete_signature_process()

        publication = DocumentPublicationService().publish_as_current(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )

        self.assertEqual(db.session.get(DocumentoVersion, 1500).estado, ESTADO_OBSOLETO)
        self.assertEqual(db.session.get(DocumentoVersion, 1501).estado, ESTADO_VIGENTE)
        obsolete_event = DocumentoAprobacion.query.filter_by(
            documento_version_id=1500,
            accion="VERSION_ANTERIOR_OBSOLETA",
        ).one()
        self.assertEqual(obsolete_event.estado_anterior, ESTADO_SUSTITUIDO)
        self.assertEqual(obsolete_event.estado_nuevo, ESTADO_OBSOLETO)
        self.assertEqual(db.session.get(DocumentoPublicacion, previous_publication.id).estado, PUBLICACION_OBSOLETA)
        self.assertFalse(db.session.get(DocumentoPublicacion, previous_publication.id).activa)
        row = DocumentoVigorCatalogo.query.filter_by(identidad_estable="DOCUMENTO:501#1").one()
        self.assertEqual(row.id, first_row_id)
        self.assertEqual(row.documento_version_id, version.id)
        self.assertEqual(row.documento_publicacion_id, publication.id)
        self.assertEqual(DocumentoVigorCatalogo.query.filter_by(documento_id=501).count(), 1)
        self.assertEqual(DocumentoVigorCatalogo.query.filter_by(identidad_estable="DOCUMENTO:501#1").count(), 1)
        with self.assertRaisesRegex(DocumentPublicationError, "version ya esta VIGENTE"):
            DocumentPublicationService().publish_as_current(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                usuario=db.session.get(Usuario, 201),
            )
        self.assertEqual(
            DocumentoAprobacion.query.filter_by(
                documento_version_id=1500,
                accion="VERSION_ANTERIOR_OBSOLETA",
            ).count(),
            1,
        )
        self.assertEqual(DocumentoVigorCatalogo.query.filter_by(documento_id=501).count(), 1)

    def test_publish_as_current_requires_completed_signature_process(self):
        DocumentPublicationService().prepare_publication_for_signature(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )

        with self.assertRaisesRegex(DocumentPublicationError, "proceso de firmas debe estar COMPLETADO"):
            DocumentPublicationService().publish_as_current(
                documento=db.session.get(Documento, 501),
                version_doc=db.session.get(DocumentoVersion, 1501),
                usuario=db.session.get(Usuario, 201),
            )

        self.assertEqual(db.session.get(Documento, 501).estado, ESTADO_APROBADO)
        self.assertEqual(db.session.get(DocumentoVersion, 1501).estado, ESTADO_APROBADO)
        self.assertEqual(DocumentoPublicacion.query.filter_by(estado=PUBLICACION_ACTIVA, activa=True).count(), 0)
        self.assertEqual(DocumentoVigorCatalogo.query.count(), 0)

    def test_email_disabled_marks_delivery_omitted_not_sent(self):
        from app.services.document_email_service import DocumentEmailService

        self.complete_signature_process()
        DocumentDistributionService().add_external_recipient(
            documento=db.session.get(Documento, 501),
            nombre="Externo",
            email="externo@pub.test",
            usuario_actor=db.session.get(Usuario, 201),
        )
        publication = DocumentPublicationService().publish_as_current(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )

        result = DocumentEmailService().process_pending(publicacion_id=publication.id)
        delivery = DocumentoDistribucionEntrega.query.filter_by(publicacion_id=publication.id).one()

        self.assertEqual(result["procesadas"], 1)
        self.assertEqual(delivery.estado_envio, ENTREGA_OMITIDO)
        self.assertIn("DOCUMENT_DISTRIBUTION_EMAIL_ENABLED=false", delivery.ultimo_error)

    def test_token_public_publication_requires_token_and_links_include_it(self):
        self.complete_signature_process()
        publication = DocumentPublicationService().publish_as_current(
            documento=db.session.get(Documento, 501),
            version_doc=db.session.get(DocumentoVersion, 1501),
            usuario=db.session.get(Usuario, 201),
        )
        publication.modo_acceso = PUBLICACION_ACCESO_TOKEN_PUBLICO
        publication.token = "public-token-501"
        db.session.commit()

        client = self.app.test_client()
        self.assertEqual(client.get(f"/documentos/publicados/{publication.public_id}").status_code, 404)
        self.assertEqual(client.get(f"/documentos/publicados/{publication.public_id}?token=public-token-501").status_code, 200)

        user = db.session.get(Usuario, 201)
        user.set_password("secret")
        db.session.commit()
        logged = self.app.test_client()
        logged.post("/auth/login", data={"username": "calidad", "password": "secret"})
        detail_html = logged.get("/documentacion/501").get_data(as_text=True)
        vigente_html = logged.get("/documentacion/documentos-vigentes").get_data(as_text=True)
        self.assertIn(f"/documentos/publicados/{publication.public_id}?token=public-token-501", detail_html)
        self.assertIn(f"/documentos/publicados/{publication.public_id}?token=public-token-501", vigente_html)

    def test_obsolete_publication_links_to_token_public_current_publication(self):
        previous = db.session.get(DocumentoVersion, 1500)
        version = db.session.get(DocumentoVersion, 1501)
        document = db.session.get(Documento, 501)
        now = datetime.now(timezone.utc)
        previous_publication = DocumentoPublicacion(
            empresa_id=101,
            documento_id=document.id,
            documento_version_id=previous.id,
            public_id="pub-obsoleta-token",
            token="old-token",
            estado=PUBLICACION_OBSOLETA,
            activa=False,
            qr_payload="https://labzeniso.test/documentos/publicados/pub-obsoleta-token",
            qr_embebido=True,
            vigente_desde=now,
        )
        db.session.add(previous_publication)
        db.session.commit()
        self.complete_signature_process()
        current = DocumentPublicationService().publish_as_current(
            documento=document,
            version_doc=version,
            usuario=db.session.get(Usuario, 201),
        )
        previous_publication.estado = PUBLICACION_OBSOLETA
        previous_publication.activa = False
        previous_publication.modo_acceso = PUBLICACION_ACCESO_TOKEN_PUBLICO
        previous_publication.token = "old-token"
        current.modo_acceso = PUBLICACION_ACCESO_TOKEN_PUBLICO
        current.token = "current-token"
        db.session.commit()

        response = self.app.test_client().get(f"/documentos/publicados/{previous_publication.public_id}?token=old-token")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/documentos/publicados/{current.public_id}?token=current-token", html)
        self.assertEqual(self.app.test_client().get(f"/documentos/publicados/{current.public_id}?token=current-token").status_code, 200)
