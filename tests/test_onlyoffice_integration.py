import tempfile
import unittest
import subprocess
import zipfile
import re
import os
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.error import URLError

import jwt
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app, redact_sensitive_request_tokens
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import (
    Documento,
    DocumentoArtefacto,
    DocumentoConversion,
    DocumentoEdicion,
    DocumentoEdicionEvento,
    DocumentoSnapshot,
    DocumentoVersion,
)
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.onlyoffice_health_service import OnlyOfficeHealthService
from app.services.onlyoffice_jwt_service import (
    generate_onlyoffice_callback_token,
    generate_onlyoffice_document_token,
    generate_onlyoffice_ping_token,
)
from app.services.onlyoffice_document_edit_service import (
    OnlyOfficeDocumentEditService,
    OnlyOfficeEditConflictError,
    OnlyOfficeEditSessionService,
)
from app.services.document_pdf_service import (
    ConversionProviderResult,
    DocumentPdfError,
    DocumentPdfService,
    conversion_key_for_snapshot,
)
from app.services.document_workflow_service import (
    approve_version as workflow_approve_version,
    reject_version as workflow_reject_version,
    return_to_draft as workflow_return_to_draft,
    send_for_review as workflow_send_for_review,
)
from app.services.storage_service import apply_stored_file_metadata, store_document_file
from app.services.storage_service import file_digest_and_size, resolve_document_path
from werkzeug.datastructures import FileStorage


class FakeHttpResponse:
    def __init__(self, status_code=200, body=b"", url="http://localhost:8082/result.docx"):
        self.status_code = status_code
        self.body = body
        self.url = url
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status_code

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class ElementByIdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements_by_id = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.elements_by_id.setdefault(element_id, []).append({
                "tag": tag,
                "attrs": attributes,
            })


class OnlyOfficeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DOCUMENT_STORAGE_ROOT": self.temp_directory.name,
            "DOCUMENT_LEGACY_STORAGE_ROOT": self.temp_directory.name,
            "ONLYOFFICE_ENABLED": True,
            "ONLYOFFICE_PUBLIC_URL": "http://localhost:8082",
            "ONLYOFFICE_INTERNAL_URL": "http://localhost:8082",
            "ONLYOFFICE_CALLBACK_BASE_URL": "http://host.docker.internal:5000",
            "ONLYOFFICE_JWT_SECRET": "unit-test-onlyoffice-secret",
            "ONLYOFFICE_VERIFY_SSL": False,
            "ONLYOFFICE_REQUEST_TIMEOUT_SECONDS": 3,
            "ONLYOFFICE_ALLOWED_HOSTS": ["localhost", "127.0.0.1", "host.docker.internal"],
            "ONLYOFFICE_HEALTHCHECK_PATH": "/healthcheck",
            "ONLYOFFICE_PING_TOKEN_TTL_SECONDS": 120,
            "ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS": 300,
            "ONLYOFFICE_EDIT_ENABLED": True,
            "ONLYOFFICE_EDIT_LOCK_TTL_SECONDS": 300,
            "ONLYOFFICE_EDIT_HEARTBEAT_SECONDS": 30,
            "ONLYOFFICE_FORCE_SAVE_DEBOUNCE_SECONDS": 45,
            "ONLYOFFICE_CALLBACK_TOKEN_TTL_SECONDS": 3600,
            "ONLYOFFICE_CALLBACK_DOWNLOAD_MAX_BYTES": 25 * 1024 * 1024,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.next_id = 9000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        self._seed_security()
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def _seed_security(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Usuario(
                id=201,
                empresa_id=101,
                nombre="Calidad",
                apellido="Uno",
                email="quality@onlyoffice",
                username="quality-onlyoffice",
                password_hash="x",
                activo=True,
            ),
            Usuario(
                id=202,
                empresa_id=101,
                nombre="Consulta",
                apellido="Uno",
                email="consulta@onlyoffice",
                username="consulta-onlyoffice",
                password_hash="x",
                activo=True,
            ),
            Usuario(
                id=204,
                empresa_id=101,
                nombre="Calidad",
                apellido="Alterna",
                email="quality-alt@onlyoffice",
                username="quality-alt-onlyoffice",
                password_hash="x",
                activo=True,
            ),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(
                id=203,
                empresa_id=102,
                nombre="Calidad",
                apellido="Dos",
                email="quality2@onlyoffice",
                username="quality2-onlyoffice",
                password_hash="x",
                activo=True,
            ),
        ])
        view_permission = Permiso(id=1001, codigo="documentos.ver", nombre="Ver documentos", modulo="documentos")
        edit_permission = Permiso(id=1003, codigo="documentos.editar", nombre="Editar documentos", modulo="documentos")
        review_permission = Permiso(
            id=1004,
            codigo="documentos.enviar_revision",
            nombre="Enviar a revisiÃ³n",
            modulo="documentos",
        )
        history_permission = Permiso(
            id=1002,
            codigo="documentos.ver_historial",
            nombre="Ver historial documental",
            modulo="documentos",
        )
        quality_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        consultation_role = Rol(id=2002, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([
            view_permission,
            history_permission,
            edit_permission,
            review_permission,
            quality_role,
            consultation_role,
        ])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=quality_role.id, permiso_id=view_permission.id),
            RolPermiso(id=3002, rol_id=quality_role.id, permiso_id=history_permission.id),
            RolPermiso(id=3003, rol_id=quality_role.id, permiso_id=edit_permission.id),
            RolPermiso(id=3004, rol_id=quality_role.id, permiso_id=review_permission.id),
            UsuarioRol(id=4001, usuario_id=201, rol_id=quality_role.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=consultation_role.id),
            UsuarioRol(id=4003, usuario_id=203, rol_id=quality_role.id),
            UsuarioRol(id=4004, usuario_id=204, rol_id=quality_role.id),
        ])

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def parse_elements_by_id(self, html):
        parser = ElementByIdParser()
        parser.feed(html)
        return parser.elements_by_id

    def assert_single_element_with_id(self, elements_by_id, element_id):
        self.assertIn(element_id, elements_by_id)
        self.assertEqual(len(elements_by_id[element_id]), 1)
        return elements_by_id[element_id][0]

    def minimal_docx(self, text="LabZenISO"):
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
                  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
                  <Default Extension="xml" ContentType="application/xml"/>
                  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
                </Types>""",
            )
            archive.writestr(
                "word/document.xml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
                </w:document>""",
            )
        return stream.getvalue()

    def minimal_pdf(self, text="LabZenISO"):
        body = (
            b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >> endobj\n"
            b"4 0 obj << /Length 44 >> stream\nBT /F1 12 Tf 72 120 Td ("
            + text.encode("ascii", "ignore")
            + b") Tj ET\nendstream endobj\n"
            b"xref\n0 5\n0000000000 65535 f \n"
            b"trailer << /Root 1 0 R /Size 5 >>\nstartxref\n0\n%%EOF\n"
        )
        return body

    class FakeConversionProvider:
        provider_name = "onlyoffice"

        def __init__(self, pdf_path):
            self.pdf_path = pdf_path
            self.requests = []

        def request_conversion(self, *, conversion, source_url, source_token):
            self.requests.append({
                "conversion_key": conversion.conversion_key,
                "source_url": source_url,
                "source_token_present": bool(source_token),
            })
            return ConversionProviderResult(
                end_convert=True,
                percent=100,
                file_url="http://localhost:8082/cache/result.pdf",
                file_type="pdf",
                raw_fingerprint="fake",
            )

        def download_result(self, file_url):
            return self.pdf_path

    def add_document_with_file(
        self,
        *,
        document_id=501,
        version_id=1501,
        company_id=101,
        filename="procedimiento.docx",
        content=b"minimal non confidential docx bytes",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        document = Documento(
            id=document_id,
            empresa_id=company_id,
            codigo=f"DOC-{document_id}",
            titulo=f"Documento {document_id}",
            tipo_documento="PROCEDIMIENTO",
            estado="EN_ELABORACION",
            version_actual="1",
            elaborado_por_id=201 if company_id == 101 else 203,
        )
        version = DocumentoVersion(
            id=version_id,
            empresa_id=company_id,
            documento_id=document_id,
            version="1",
            estado="EN_ELABORACION",
            elaborado_por_id=201 if company_id == 101 else 203,
        )
        db.session.add_all([document, version])
        db.session.flush()
        stored = store_document_file(
            FileStorage(stream=BytesIO(content), filename=filename, content_type=mime),
            documento=document,
            version=version.version,
        )
        apply_stored_file_metadata(version, stored)
        db.session.commit()
        return document, version

    def replace_working_docx(self, version, text):
        path = resolve_document_path(version.archivo_storage_path)
        path.write_bytes(self.minimal_docx(text))
        sha256, size = file_digest_and_size(path)
        version.archivo_sha256 = sha256
        version.archivo_size = size
        db.session.commit()
        return sha256

    def approve_document_with_snapshot(self, *, document_id=501, version_id=1501):
        document, version = self.add_document_with_file(
            document_id=document_id,
            version_id=version_id,
            content=self.minimal_docx("aprobado"),
        )
        user = db.session.get(Usuario, 201)
        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            comentario="Listo",
            resumen_cambios="Cambio controlado",
            hojas_modificadas="No aplica",
        )
        db.session.commit()
        workflow_approve_version(
            documento=document,
            version_doc=version,
            usuario=user,
            comentario="Aprobado",
        )
        db.session.commit()
        return document, version, user, DocumentoSnapshot.query.filter_by(
            documento_version_id=version.id,
            tipo="APROBADO",
        ).one()

    def test_pdf_conversion_accepts_only_approved_snapshot_source(self):
        document, version = self.add_document_with_file(content=self.minimal_docx("revision"))
        user = db.session.get(Usuario, 201)
        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            comentario="Listo",
            resumen_cambios="Cambio controlado",
            hojas_modificadas="No aplica",
        )
        db.session.commit()
        review_snapshot = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="ENVIO_REVISION").one()

        with self.assertRaises(DocumentPdfError):
            DocumentPdfService()._validate_approved_snapshot(review_snapshot)

        document, version, _user, approved_snapshot = self.approve_document_with_snapshot(
            document_id=502,
            version_id=1502,
        )
        self.assertEqual(approved_snapshot.tipo, "APROBADO")
        self.assertEqual(approved_snapshot.workflow_evento.accion, "APROBAR")
        DocumentPdfService()._validate_approved_snapshot(approved_snapshot)

    def test_conversion_key_is_stable_and_bound_to_snapshot_hash(self):
        _document, _version, _user, snapshot = self.approve_document_with_snapshot()
        first = conversion_key_for_snapshot(snapshot)
        second = conversion_key_for_snapshot(snapshot)
        self.assertEqual(first, second)
        snapshot.archivo_sha256 = "0" * 64
        self.assertNotEqual(first, conversion_key_for_snapshot(snapshot))
        db.session.rollback()

    def test_approved_snapshot_generates_private_immutable_pdf_once(self):
        self.app.config["ONLYOFFICE_CONVERSION_ENABLED"] = True
        document, version, user, snapshot = self.approve_document_with_snapshot()
        fd, temp_name = tempfile.mkstemp(prefix="test-pdf-", suffix=".pdf")
        os.close(fd)
        pdf_path = Path(temp_name)
        pdf_path.write_bytes(self.minimal_pdf())
        provider = self.FakeConversionProvider(pdf_path)
        service = DocumentPdfService(provider=provider)

        artifact = service.ensure_conversion_for_approved_version(
            documento=document,
            version_doc=version,
            usuario=user,
            start=True,
        )

        self.assertEqual(artifact.estado, "DISPONIBLE")
        self.assertTrue(artifact.inmutable)
        self.assertEqual(artifact.tipo, "PDF_APROBADO")
        self.assertEqual(artifact.source_snapshot_id, snapshot.id)
        self.assertEqual(artifact.source_snapshot_sha256, snapshot.archivo_sha256)
        self.assertEqual(artifact.archivo_mime, "application/pdf")
        self.assertEqual(artifact.page_count, 1)
        self.assertIn("/pdf/", f"/{artifact.storage_path}")
        self.assertTrue(resolve_document_path(artifact.storage_path).is_file())
        self.assertEqual(DocumentoArtefacto.query.count(), 1)
        self.assertEqual(DocumentoConversion.query.count(), 1)
        self.assertEqual(Documento.query.count(), 1)
        self.assertEqual(DocumentoVersion.query.count(), 1)

        same = service.ensure_conversion_for_approved_version(
            documento=document,
            version_doc=version,
            usuario=user,
            start=True,
        )
        self.assertEqual(same.id, artifact.id)
        self.assertEqual(DocumentoArtefacto.query.count(), 1)
        self.assertEqual(DocumentoConversion.query.count(), 1)

    def test_pdf_validation_rejects_active_content(self):
        fd, temp_name = tempfile.mkstemp(prefix="test-active-pdf-", suffix=".pdf")
        os.close(fd)
        path = Path(temp_name)
        try:
            path.write_bytes(self.minimal_pdf() + b"\n/JavaScript")
            with self.assertRaises(DocumentPdfError):
                DocumentPdfService().validate_pdf_file(path)
        finally:
            path.unlink(missing_ok=True)

    def test_pdf_validation_counts_pages_with_flexible_type_spacing(self):
        fd, temp_name = tempfile.mkstemp(prefix="test-flex-pdf-", suffix=".pdf")
        os.close(fd)
        path = Path(temp_name)
        try:
            data = self.minimal_pdf().replace(b"/Type /Page ", b"/Type\n/Page ")
            path.write_bytes(data)
            result = DocumentPdfService().validate_pdf_file(path)
            self.assertEqual(result.page_count, 1)
        finally:
            path.unlink(missing_ok=True)

    def test_workflow_send_for_review_creates_immutable_snapshot_without_new_version(self):
        document, version = self.add_document_with_file(content=self.minimal_docx("ciclo uno"))
        user = db.session.get(Usuario, 201)
        document_count = Documento.query.count()
        version_count = DocumentoVersion.query.count()

        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            comentario="Listo para revision",
            resumen_cambios="Se actualizo el procedimiento",
            hojas_modificadas="Seccion 1",
        )
        db.session.commit()

        snapshot = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="ENVIO_REVISION").one()
        self.assertEqual(snapshot.estado, "DISPONIBLE")
        self.assertTrue(snapshot.inmutable)
        self.assertEqual(snapshot.ciclo_revision, 1)
        self.assertEqual(snapshot.secuencia, 1)
        self.assertEqual(snapshot.archivo_sha256, version.archivo_sha256)
        self.assertIn("/snapshots/", f"/{snapshot.storage_path}")
        self.assertTrue(resolve_document_path(snapshot.storage_path).is_file())
        self.assertEqual(Documento.query.count(), document_count)
        self.assertEqual(DocumentoVersion.query.count(), version_count)

    def test_reject_return_to_draft_and_resend_keeps_previous_snapshots(self):
        document, version = self.add_document_with_file(content=self.minimal_docx("ciclo uno"))
        user = db.session.get(Usuario, 201)

        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            resumen_cambios="Primer ciclo",
            hojas_modificadas="No aplica",
        )
        workflow_reject_version(documento=document, version_doc=version, usuario=user, comentario="Corregir")
        db.session.commit()

        first_review = DocumentoSnapshot.query.filter_by(
            documento_version_id=version.id,
            tipo="ENVIO_REVISION",
            ciclo_revision=1,
        ).one()
        rejected = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="RECHAZADO").one()
        self.assertIsNone(rejected.storage_path)
        self.assertEqual(rejected.snapshot_origen_id, first_review.id)

        self.replace_working_docx(version, "cambio descartable")
        workflow_return_to_draft(documento=document, version_doc=version, usuario=user, comentario="Devolver")
        db.session.commit()
        self.assertEqual(db.session.get(DocumentoVersion, version.id).archivo_sha256, first_review.archivo_sha256)

        self.replace_working_docx(version, "ciclo dos")
        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            resumen_cambios="Segundo ciclo",
            hojas_modificadas="Seccion 2",
        )
        db.session.commit()

        reviews = (
            DocumentoSnapshot.query
            .filter_by(documento_version_id=version.id, tipo="ENVIO_REVISION")
            .order_by(DocumentoSnapshot.ciclo_revision.asc())
            .all()
        )
        self.assertEqual([snapshot.ciclo_revision for snapshot in reviews], [1, 2])
        self.assertEqual([snapshot.secuencia for snapshot in reviews], [1, 3])
        self.assertNotEqual(reviews[0].archivo_sha256, reviews[1].archivo_sha256)
        self.assertTrue(resolve_document_path(reviews[0].storage_path).is_file())

    def test_approve_version_creates_approved_snapshot_and_uses_review_hash(self):
        document, version = self.add_document_with_file(content=self.minimal_docx("aprobado"))
        user = db.session.get(Usuario, 201)

        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            resumen_cambios="Listo",
            hojas_modificadas="No aplica",
        )
        review = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="ENVIO_REVISION").one()
        workflow_approve_version(documento=document, version_doc=version, usuario=user, comentario="Aprobado")
        db.session.commit()

        approved = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="APROBADO").one()
        self.assertEqual(approved.snapshot_origen_id, review.id)
        self.assertEqual(approved.archivo_sha256, review.archivo_sha256)
        self.assertEqual(db.session.get(DocumentoVersion, version.id).estado, "APROBADO")
        self.assertEqual(db.session.get(Documento, document.id).version_vigente_id, version.id)

    def test_workflow_snapshots_are_linked_to_audit_events(self):
        document, version = self.add_document_with_file(content=self.minimal_docx("eventos"))
        user = db.session.get(Usuario, 201)

        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            resumen_cambios="Revision con evento",
            hojas_modificadas="No aplica",
        )
        db.session.commit()
        review = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="ENVIO_REVISION").one()
        self.assertIsNotNone(review.workflow_evento_id)
        self.assertEqual(review.workflow_evento.accion, "ENVIAR_REVISION")

        workflow_reject_version(documento=document, version_doc=version, usuario=user, comentario="Corregir")
        db.session.commit()
        rejected = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="RECHAZADO").one()
        self.assertIsNotNone(rejected.workflow_evento_id)
        self.assertEqual(rejected.workflow_evento.accion, "RECHAZAR")

        workflow_return_to_draft(documento=document, version_doc=version, usuario=user, comentario="Devolver")
        self.replace_working_docx(version, "eventos ciclo dos")
        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            resumen_cambios="Segundo envio con evento",
            hojas_modificadas="No aplica",
        )
        workflow_approve_version(documento=document, version_doc=version, usuario=user, comentario="Aprobar")
        db.session.commit()
        approved = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="APROBADO").one()
        self.assertIsNotNone(approved.workflow_evento_id)
        self.assertEqual(approved.workflow_evento.accion, "APROBAR")

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_onlyoffice_viewer_uses_review_snapshot_in_read_only_mode(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(content=self.minimal_docx("snapshot oficial"))
        user = db.session.get(Usuario, 201)
        workflow_send_for_review(
            documento=document,
            version_doc=version,
            usuario=user,
            resumen_cambios="Revision",
            hojas_modificadas="No aplica",
        )
        db.session.commit()
        snapshot = DocumentoSnapshot.query.filter_by(documento_version_id=version.id, tipo="ENVIO_REVISION").one()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('"mode": "view"', body)
        self.assertIn('"edit": false', body)
        self.assertIn('"download": false', body)
        self.assertIn('"print": false', body)
        token_match = re.search(r"archivo\?token=([^\"&]+)", body)
        self.assertIsNotNone(token_match)
        payload = jwt.decode(
            token_match.group(1),
            self.app.config["ONLYOFFICE_JWT_SECRET"],
            algorithms=["HS256"],
            audience="labzeniso-onlyoffice-document-view",
            issuer=self.app.config["ONLYOFFICE_PING_JWT_ISSUER"],
        )
        self.assertEqual(payload["snapshot_public_id"], snapshot.public_id)
        self.assertEqual(payload["archivo_sha256"], snapshot.archivo_sha256)
        self.assertNotIn("callbackUrl", body)

    def test_onlyoffice_disabled_does_not_break_app_startup(self):
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "ONLYOFFICE_ENABLED": False,
            "ONLYOFFICE_JWT_SECRET": "",
        })

        self.assertFalse(app.config["ONLYOFFICE_ENABLED"])

    def test_health_check_disabled_returns_controlled_result(self):
        self.app.config["ONLYOFFICE_ENABLED"] = False

        result = OnlyOfficeHealthService(self.app).check()

        self.assertFalse(result.enabled)
        self.assertFalse(result.available)

    def test_onlyoffice_enabled_requires_jwt_secret(self):
        with self.assertRaises(RuntimeError):
            create_app({
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "SQLALCHEMY_ENGINE_OPTIONS": {},
                "ONLYOFFICE_ENABLED": True,
                "ONLYOFFICE_JWT_SECRET": "",
            })

    def test_onlyoffice_urls_are_loaded_from_config(self):
        self.assertEqual(self.app.config["ONLYOFFICE_PUBLIC_URL"], "http://localhost:8082")
        self.assertEqual(self.app.config["ONLYOFFICE_INTERNAL_URL"], "http://localhost:8082")
        self.assertEqual(self.app.config["ONLYOFFICE_CALLBACK_BASE_URL"], "http://host.docker.internal:5000")

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_health_check_success_returns_available(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)

        result = OnlyOfficeHealthService(self.app).check()

        self.assertTrue(result.available)
        self.assertEqual(result.status_code, 200)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_health_check_timeout_returns_controlled_result(self, urlopen_mock):
        urlopen_mock.side_effect = TimeoutError()

        result = OnlyOfficeHealthService(self.app).check()

        self.assertFalse(result.available)
        self.assertIn("Timeout", result.message)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_health_check_connection_refused_returns_controlled_result(self, urlopen_mock):
        urlopen_mock.side_effect = URLError(ConnectionRefusedError("connection refused"))

        result = OnlyOfficeHealthService(self.app).check()

        self.assertFalse(result.available)
        self.assertIn("No se pudo conectar", result.message)

    def test_admin_diagnostic_requires_login(self):
        response = self.app.test_client().get("/documentacion/integraciones/onlyoffice/")

        self.assertIn(response.status_code, (302, 401))

    def test_admin_diagnostic_requires_permission(self):
        response = self.login(202).get("/documentacion/integraciones/onlyoffice/")

        self.assertEqual(response.status_code, 403)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_admin_diagnostic_does_not_expose_secret(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)

        response = self.login(201).get("/documentacion/integraciones/onlyoffice/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("unit-test-onlyoffice-secret", body)

    def test_ping_rejects_missing_jwt(self):
        response = self.app.test_client().post("/documentacion/integraciones/onlyoffice/ping", json={})

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("unit-test-onlyoffice-secret", response.get_data(as_text=True))

    def test_ping_is_disabled_when_integration_is_disabled(self):
        self.app.config["ONLYOFFICE_ENABLED"] = False

        response = self.app.test_client().post("/documentacion/integraciones/onlyoffice/ping", json={})

        self.assertEqual(response.status_code, 404)

    def test_ping_rejects_invalid_jwt(self):
        response = self.app.test_client().post(
            "/documentacion/integraciones/onlyoffice/ping",
            headers={"Authorization": "Bearer invalid-token"},
            json={},
        )

        self.assertEqual(response.status_code, 401)

    def test_ping_rejects_expired_jwt(self):
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "iss": self.app.config["ONLYOFFICE_PING_JWT_ISSUER"],
                "aud": self.app.config["ONLYOFFICE_PING_JWT_AUDIENCE"],
                "iat": now - timedelta(minutes=5),
                "nbf": now - timedelta(minutes=5),
                "exp": now - timedelta(minutes=1),
                "scope": "onlyoffice:ping",
            },
            self.app.config["ONLYOFFICE_JWT_SECRET"],
            algorithm="HS256",
        )

        response = self.app.test_client().post(
            "/documentacion/integraciones/onlyoffice/ping",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("vencido", response.get_data(as_text=True))

    def test_ping_accepts_valid_jwt(self):
        token = generate_onlyoffice_ping_token()

        response = self.app.test_client().post(
            "/documentacion/integraciones/onlyoffice/ping",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_ping_does_not_modify_database_or_create_documents(self):
        token = generate_onlyoffice_ping_token()
        before_documents = Documento.query.count()
        before_versions = DocumentoVersion.query.count()

        response = self.app.test_client().post(
            "/documentacion/integraciones/onlyoffice/ping",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Documento.query.count(), before_documents)
        self.assertEqual(DocumentoVersion.query.count(), before_versions)

    def test_secret_is_not_returned_in_health_json(self):
        with patch("app.services.onlyoffice_health_service.urlopen", return_value=FakeHttpResponse(200)):
            response = self.login(201).get("/documentacion/integraciones/onlyoffice/health")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("unit-test-onlyoffice-secret", response.get_data(as_text=True))

    def test_client_docx_is_ignored_by_git(self):
        result = subprocess.run(
            [
                "git",
                "check-ignore",
                "-v",
                "docs/cliente/PEE CONDUCTICIDAD ELEC ANHIDRO v1.docx",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("docs/cliente/*.docx", result.stdout)

    def test_document_token_ttl_is_loaded_from_config(self):
        self.assertEqual(self.app.config["ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS"], 300)

    def test_invalid_document_token_ttl_raises_controlled_error(self):
        with self.assertRaises(RuntimeError):
            create_app({
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "SQLALCHEMY_ENGINE_OPTIONS": {},
                "ONLYOFFICE_ENABLED": True,
                "ONLYOFFICE_JWT_SECRET": "valid-secret",
                "ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS": 0,
            })

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_authorized_user_can_open_docx_viewer(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Modo lectura", body)
        self.assertIn("ONLYOFFICE", body)
        self.assertNotIn("unit-test-onlyoffice-secret", body)
        self.assertNotIn(version.archivo_storage_path, body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_error_is_hidden_initially_and_loading_is_visible(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)
        elements = self.parse_elements_by_id(body)
        loading = self.assert_single_element_with_id(elements, "onlyoffice-loading")
        ready = self.assert_single_element_with_id(elements, "onlyoffice-ready")
        error = self.assert_single_element_with_id(elements, "onlyoffice-error")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("hidden", loading["attrs"])
        self.assertIn("hidden", ready["attrs"])
        self.assertIn("hidden", error["attrs"])
        self.assertIn("Cargando ONLYOFFICE", body)
        self.assertIn("Documento disponible en modo lectura.", body)
        self.assertIn("No se pudo cargar ONLYOFFICE", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_status_ids_are_unique(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        elements = self.parse_elements_by_id(response.get_data(as_text=True))

        self.assertEqual(response.status_code, 200)
        self.assert_single_element_with_id(elements, "onlyoffice-loading")
        self.assert_single_element_with_id(elements, "onlyoffice-ready")
        self.assert_single_element_with_id(elements, "onlyoffice-error")

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_has_single_state_machine_for_loading_ready_and_error(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body.count("function setViewerState(state, message)"), 1)
        self.assertIn("const VIEWER_STATE = Object.freeze", body)
        self.assertIn("LOADING", body)
        self.assertIn("READY", body)
        self.assertIn("ERROR", body)
        self.assertIn('setOnlyOfficeElementVisible("onlyoffice-loading", state === VIEWER_STATE.LOADING)', body)
        self.assertIn('setOnlyOfficeElementVisible("onlyoffice-ready", state === VIEWER_STATE.READY)', body)
        self.assertIn('setOnlyOfficeElementVisible("onlyoffice-error", state === VIEWER_STATE.ERROR)', body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_state_changes_use_hidden_and_display(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("element.hidden = !isVisible", body)
        self.assertIn('element.style.display = isVisible ? "" : "none"', body)
        self.assertIn('element.classList.toggle("d-none", !isVisible)', body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_uses_app_ready_and_document_ready_to_set_ready(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("onAppReady: markOnlyOfficeReady", body)
        self.assertIn("onDocumentReady: markOnlyOfficeReady", body)
        self.assertIn("function markOnlyOfficeReady()", body)
        self.assertIn("setViewerState(VIEWER_STATE.READY)", body)
        self.assertIn("editorReady = true", body)
        self.assertIn("clearOnlyOfficeLoadTimeout();", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_real_api_or_initialization_failure_shows_error(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("window.labzenOnlyOfficeApiLoadFailed = true", body)
        self.assertIn("if (window.labzenOnlyOfficeApiLoadFailed)", body)
        self.assertIn("if (!window.DocsAPI || !window.DocsAPI.DocEditor)", body)
        self.assertIn("catch (error)", body)
        self.assertIn("showOnlyOfficeFatalError();", body)
        self.assertIn("setViewerState(", body)
        self.assertIn("VIEWER_STATE.ERROR", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_successful_initialization_does_not_show_error(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('new window.DocsAPI.DocEditor("onlyoffice-editor", onlyOfficeConfig)', body)
        self.assertIn("function showOnlyOfficeFatalError(message)", body)
        self.assertIn("if (editorReady)", body)
        self.assertIn("return;", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_timeout_is_controlled_and_cannot_fire_after_ready(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("const ONLYOFFICE_LOAD_TIMEOUT_MS = 30000", body)
        self.assertIn("onlyOfficeLoadTimeout = window.setTimeout", body)
        self.assertIn("if (!editorReady)", body)
        self.assertIn("showOnlyOfficeFatalError();", body)
        self.assertIn("function clearOnlyOfficeLoadTimeout()", body)
        self.assertIn("window.clearTimeout(onlyOfficeLoadTimeout)", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_ignores_non_fatal_onlyoffice_errors(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("function isOnlyOfficeFatalError(event)", body)
        self.assertIn("event.fatal === true", body)
        self.assertIn("ONLYOFFICE_FATAL_ERROR_CODES.has(code)", body)
        self.assertIn("if (!editorReady && isOnlyOfficeFatalError(event))", body)
        self.assertIn("logOnlyOfficeError(event)", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_user_without_view_permission_gets_403(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(202).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")

        self.assertEqual(response.status_code, 403)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_other_company_cannot_open_viewer(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(company_id=101)

        response = self.login(203).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")

        self.assertEqual(response.status_code, 404)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_non_docx_file_is_rejected_by_viewer(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(filename="procedimiento.pdf", mime="application/pdf")

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")

        self.assertEqual(response.status_code, 422)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_missing_private_file_returns_404(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()
        version.archivo_storage_path = "empresa_101/documento_501/v1/no-existe.docx"
        db.session.commit()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")

        self.assertEqual(response.status_code, 404)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_does_not_duplicate_or_modify_document_state(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()
        before_documents = Documento.query.count()
        before_versions = DocumentoVersion.query.count()
        before_state = document.estado
        before_hash = version.archivo_sha256

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Documento.query.count(), before_documents)
        self.assertEqual(DocumentoVersion.query.count(), before_versions)
        self.assertEqual(db.session.get(Documento, document.id).estado, before_state)
        self.assertEqual(db.session.get(DocumentoVersion, version.id).archivo_sha256, before_hash)

    def test_document_file_rejects_missing_invalid_and_expired_token(self):
        document, version = self.add_document_with_file()

        missing = self.app.test_client().get(f"/documentacion/integraciones/onlyoffice/versiones/{version.id}/archivo")
        invalid = self.app.test_client().get(
            f"/documentacion/integraciones/onlyoffice/versiones/{version.id}/archivo?token=invalid"
        )
        now = datetime.now(timezone.utc)
        expired_token = jwt.encode(
            {
                "iss": self.app.config["ONLYOFFICE_PING_JWT_ISSUER"],
                "aud": "labzeniso-onlyoffice-document-view",
                "iat": now - timedelta(minutes=5),
                "nbf": now - timedelta(minutes=5),
                "exp": now - timedelta(minutes=1),
                "scope": "onlyoffice:document:view",
                "empresa_id": document.empresa_id,
                "documento_id": document.id,
                "version_id": version.id,
                "archivo_sha256": version.archivo_sha256,
            },
            self.app.config["ONLYOFFICE_JWT_SECRET"],
            algorithm="HS256",
        )
        expired = self.app.test_client().get(
            f"/documentacion/integraciones/onlyoffice/versiones/{version.id}/archivo?token={expired_token}"
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(expired.status_code, 401)

    def test_valid_document_token_delivers_docx_without_session_cookie(self):
        document, version = self.add_document_with_file(content=b"docx content")
        token = generate_onlyoffice_document_token(
            empresa_id=document.empresa_id,
            documento_id=document.id,
            version_id=version.id,
            archivo_sha256=version.archivo_sha256,
        )

        response = self.app.test_client().get(
            f"/documentacion/integraciones/onlyoffice/versiones/{version.id}/archivo?token={token}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"docx content")
        self.assertIn("officedocument.wordprocessingml.document", response.headers["Content-Type"])

    def test_document_token_rejects_wrong_scope_company_document_version_and_hash(self):
        document, version = self.add_document_with_file()
        now = datetime.now(timezone.utc)

        def make_token(**overrides):
            payload = {
                "iss": self.app.config["ONLYOFFICE_PING_JWT_ISSUER"],
                "aud": "labzeniso-onlyoffice-document-view",
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(minutes=5),
                "scope": "onlyoffice:document:view",
                "empresa_id": document.empresa_id,
                "documento_id": document.id,
                "version_id": version.id,
                "archivo_sha256": version.archivo_sha256,
            }
            payload.update(overrides)
            return jwt.encode(payload, self.app.config["ONLYOFFICE_JWT_SECRET"], algorithm="HS256")

        cases = [
            make_token(scope="onlyoffice:ping"),
            make_token(empresa_id=999),
            make_token(documento_id=999),
            make_token(version_id=999),
            make_token(archivo_sha256="0" * 64),
        ]

        for token in cases:
            response = self.app.test_client().get(
                f"/documentacion/integraciones/onlyoffice/versiones/{version.id}/archivo?token={token}"
            )
            self.assertIn(response.status_code, (401, 404))

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_onlyoffice_config_is_read_only_signed_and_uses_callback_base_url(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('"mode": "view"', body)
        self.assertIn('"edit": false', body)
        self.assertIn('"download": false', body)
        self.assertIn('"print": false', body)
        self.assertIn('"review": false', body)
        self.assertIn('"comment": false', body)
        self.assertNotIn("callbackUrl", body)
        self.assertIn("host.docker.internal", body)
        self.assertIn('"token":', body)
        self.assertNotIn(document.codigo + "_", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_detail_button_appears_only_for_docx_when_enabled(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, _version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ver en ONLYOFFICE", response.get_data(as_text=True))

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_detail_button_does_not_appear_for_incompatible_file(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, _version = self.add_document_with_file(filename="procedimiento.pdf", mime="application/pdf")

        response = self.login(201).get(f"/documentacion/{document.id}")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Ver en ONLYOFFICE", response.get_data(as_text=True))

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_viewer_csp_allows_configured_onlyoffice_origin(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file()

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/ver")

        self.assertEqual(response.status_code, 200)
        self.assertIn("http://localhost:8082", response.headers["Content-Security-Policy"])

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_edit_button_appears_for_editable_docx_only(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, _version = self.add_document_with_file(content=self.minimal_docx())

        response = self.login(201).get(f"/documentacion/{document.id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Abrir y editar", response.get_data(as_text=True))

    def test_sensitive_request_tokens_are_redacted_from_http_logs(self):
        request_line = (
            'POST /documentacion/integraciones/onlyoffice/ediciones/abc/callback?'
            'token=eyJhbGciOiJIUzI1NiJ9.payload.signature&x=1 HTTP/1.1'
        )

        redacted = redact_sensitive_request_tokens(request_line)

        self.assertIn("token=<redacted>", redacted)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9.payload.signature", redacted)
        self.assertIn("&x=1 HTTP/1.1", redacted)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_authorized_user_opens_edit_session_and_config_is_controlled(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(content=self.minimal_docx())

        response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/editar")
        body = response.get_data(as_text=True)
        edicion = DocumentoEdicion.query.filter_by(documento_version_id=version.id).one()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(edicion.estado, "ACTIVA")
        self.assertEqual(edicion.hash_inicial, version.archivo_sha256)
        self.assertIn('"mode": "edit"', body)
        self.assertIn('"edit": true', body)
        self.assertIn('"download": false', body)
        self.assertIn('"print": false', body)
        self.assertIn("callbackUrl", body)
        self.assertIn(edicion.editor_key, body)
        self.assertNotIn("unit-test-onlyoffice-secret", body)
        self.assertNotIn(version.archivo_storage_path, body)
        self.assertIn("onlyoffice-editor-frame", body)
        self.assertIn(".onlyoffice-editor-frame > iframe", body)
        self.assertIn("height: 78vh", body)
        self.assertIn('new window.DocsAPI.DocEditor("onlyoffice-editor", onlyOfficeConfig)', body)
        self.assertIn("Math.ceil((FORCE_SAVE_DEBOUNCE_SECONDS + 30) / 1.5)", body)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_edit_reuses_same_user_session_and_blocks_second_user(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(content=self.minimal_docx())

        first = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/editar")
        same_user_session = OnlyOfficeDocumentEditService().acquire_lock(
            documento=document,
            version=version,
            user=db.session.get(Usuario, 201),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(same_user_session.usuario_id, 201)
        self.assertEqual(DocumentoEdicion.query.filter_by(documento_version_id=version.id, estado="ACTIVA").count(), 1)
        with self.assertRaises(OnlyOfficeEditConflictError):
            OnlyOfficeDocumentEditService().acquire_lock(
                documento=document,
                version=version,
                user=db.session.get(Usuario, 204),
            )

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_user_without_edit_permission_gets_403(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(content=self.minimal_docx())

        response = self.login(202).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/editar")

        self.assertEqual(response.status_code, 403)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_non_editable_states_are_rejected_for_editing(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        for offset, state in enumerate(["EN_REVISION", "APROBADO", "RECHAZADO", "SUSTITUIDO", "OBSOLETO"], start=1):
            document, version = self.add_document_with_file(
                document_id=600 + offset,
                version_id=1600 + offset,
                content=self.minimal_docx(state),
            )
            version.estado = state
            db.session.commit()

            response = self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/editar")
            self.assertEqual(response.status_code, 302 if state in {"EN_REVISION", "APROBADO", "RECHAZADO", "SUSTITUIDO", "OBSOLETO"} else 409)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_heartbeat_renews_owned_session_only(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(content=self.minimal_docx())
        self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/editar")
        edicion = DocumentoEdicion.query.filter_by(documento_version_id=version.id).one()
        old_expiration = edicion.fecha_expiracion

        response = self.login(201).post(f"/documentacion/ediciones/{edicion.public_id}/heartbeat")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(db.session.get(DocumentoEdicion, edicion.id).fecha_expiracion, old_expiration)
        with self.assertRaises(LookupError):
            OnlyOfficeEditSessionService().get_owned_active_session(
                public_id=edicion.public_id,
                user=db.session.get(Usuario, 203),
            )

    @patch("app.services.onlyoffice_document_edit_service.urlopen")
    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_forcesave_command_is_backend_signed(self, health_mock, command_mock):
        health_mock.return_value = FakeHttpResponse(200)
        command_mock.return_value = FakeHttpResponse(200, body=b'{"error":0}')
        document, version = self.add_document_with_file(content=self.minimal_docx())
        self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/editar")
        edicion = DocumentoEdicion.query.filter_by(documento_version_id=version.id).one()

        response = self.login(201).post(f"/documentacion/ediciones/{edicion.public_id}/forcesave")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(command_mock.called)
        self.assertEqual(DocumentoEdicionEvento.query.filter_by(tipo="GUARDADO_FORZADO_SOLICITADO").count(), 1)

    def test_callback_requires_valid_callback_jwt(self):
        document, version = self.add_document_with_file(content=self.minimal_docx())
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-callback",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-callback",
            estado="ACTIVA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()

        missing = self.app.test_client().post(f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback", json={"status": 1})
        invalid = self.app.test_client().post(f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback?token=bad", json={"status": 1})

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)

    def test_callback_status_4_releases_without_modifying_file(self):
        document, version = self.add_document_with_file(content=self.minimal_docx())
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-close",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-close",
            estado="ACTIVA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)

        response = self.app.test_client().post(
            f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback?token={token}",
            json={"status": 4, "key": edicion.editor_key},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["error"], 0)
        self.assertEqual(db.session.get(DocumentoEdicion, edicion.id).estado, "LIBERADA")
        self.assertEqual(db.session.get(DocumentoVersion, version.id).archivo_sha256, version.archivo_sha256)

    def test_save_and_close_release_marks_session_as_liberated(self):
        document, version = self.add_document_with_file(content=self.minimal_docx())
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-save-close-release",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-save-close-release",
            estado="ACTIVA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()

        self.login(201).post(
            f"/documentacion/ediciones/{edicion.public_id}/liberar",
            data={"motivo": "Guardar y cerrar desde editor."},
        )

        saved = db.session.get(DocumentoEdicion, edicion.id)
        self.assertEqual(saved.estado, "LIBERADA")
        self.assertIsNotNone(saved.fecha_liberacion)

    def test_late_status_2_after_save_and_close_is_accepted(self):
        document, version = self.add_document_with_file(content=self.minimal_docx())
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-late-final",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-late-final",
            estado="LIBERADA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            fecha_liberacion=datetime.now(timezone.utc),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)

        response = self.app.test_client().post(
            f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback?token={token}",
            json={"status": 2, "key": edicion.editor_key},
        )

        saved = db.session.get(DocumentoEdicion, edicion.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["error"], 0)
        self.assertEqual(saved.estado, "LIBERADA")
        self.assertEqual(saved.ultimo_callback_status, 2)
        self.assertEqual(
            DocumentoEdicionEvento.query.filter_by(
                edicion_id=edicion.id,
                tipo="GUARDADO_FINAL_CONFIRMADO",
            ).count(),
            1,
        )

    @patch("app.services.onlyoffice_document_edit_service.urlopen")
    def test_callback_status_6_saves_and_keeps_session_active_without_duplication(self, urlopen_mock):
        original = self.minimal_docx("original")
        updated = self.minimal_docx("updated")
        document, version = self.add_document_with_file(content=original)
        before_documents = Documento.query.count()
        before_versions = DocumentoVersion.query.count()
        old_hash = version.archivo_sha256
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-force",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-force",
            estado="ACTIVA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)
        urlopen_mock.return_value = FakeHttpResponse(200, body=updated, url="http://localhost:8082/cache/result.docx")

        response = self.app.test_client().post(
            f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback?token={token}",
            json={"status": 6, "key": edicion.editor_key, "url": "http://localhost:8082/cache/result.docx"},
        )

        saved_version = db.session.get(DocumentoVersion, version.id)
        saved_edit = db.session.get(DocumentoEdicion, edicion.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved_edit.estado, "ACTIVA")
        self.assertNotEqual(saved_version.archivo_sha256, old_hash)
        self.assertEqual(saved_version.archivo_size, len(updated))
        self.assertEqual(Documento.query.count(), before_documents)
        self.assertEqual(DocumentoVersion.query.count(), before_versions)
        self.assertEqual(saved_version.version, "1")
        self.assertEqual(saved_version.estado, "EN_ELABORACION")

    @patch("app.services.onlyoffice_document_edit_service.urlopen")
    def test_callback_repeated_is_idempotent(self, urlopen_mock):
        document, version = self.add_document_with_file(content=self.minimal_docx("original"))
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-repeat",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-repeat",
            estado="ACTIVA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)
        urlopen_mock.return_value = FakeHttpResponse(200, body=self.minimal_docx("updated"), url="http://localhost:8082/cache/result.docx")
        url = f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback?token={token}"
        payload = {"status": 6, "key": edicion.editor_key, "url": "http://localhost:8082/cache/result.docx"}

        first = self.app.test_client().post(url, json=payload)
        second = self.app.test_client().post(url, json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(urlopen_mock.call_count, 1)
        self.assertEqual(DocumentoEdicionEvento.query.filter_by(tipo="GUARDADO_FORZADO_COMPLETADO").count(), 1)

    @patch("app.services.onlyoffice_document_edit_service.urlopen")
    def test_callback_rejects_ssrf_and_invalid_docx_without_replacing_file(self, urlopen_mock):
        document, version = self.add_document_with_file(content=self.minimal_docx("original"))
        old_hash = version.archivo_sha256
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-ssrf",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-ssrf",
            estado="ACTIVA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)

        response = self.app.test_client().post(
            f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback?token={token}",
            json={"status": 6, "key": edicion.editor_key, "url": "file:///tmp/result.docx"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.session.get(DocumentoVersion, version.id).archivo_sha256, old_hash)
        self.assertFalse(urlopen_mock.called)

    @patch("app.services.onlyoffice_document_edit_service.urlopen")
    def test_callback_restores_file_if_database_commit_fails(self, urlopen_mock):
        original = self.minimal_docx("original")
        updated = self.minimal_docx("updated-after-db-failure")
        document, version = self.add_document_with_file(content=original)
        old_hash = version.archivo_sha256
        physical_path = resolve_document_path(version.archivo_storage_path)
        edicion = DocumentoEdicion(
            empresa_id=document.empresa_id,
            public_id="public-db-fail",
            documento_id=document.id,
            documento_version_id=version.id,
            usuario_id=201,
            editor_key="editor-db-fail",
            estado="ACTIVA",
            fecha_inicio=datetime.now(timezone.utc),
            ultima_actividad=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(minutes=5),
            hash_inicial=version.archivo_sha256,
            hash_ultimo_guardado=version.archivo_sha256,
        )
        db.session.add(edicion)
        db.session.commit()
        token = generate_onlyoffice_callback_token(public_id=edicion.public_id, editor_key=edicion.editor_key)
        urlopen_mock.return_value = FakeHttpResponse(200, body=updated, url="http://localhost:8082/cache/result.docx")

        with patch("app.services.onlyoffice_document_edit_service.db.session.commit", side_effect=RuntimeError("db down")):
            response = self.app.test_client().post(
                f"/documentacion/integraciones/onlyoffice/ediciones/{edicion.public_id}/callback?token={token}",
                json={"status": 6, "key": edicion.editor_key, "url": "http://localhost:8082/cache/result.docx"},
            )

        restored_hash, _size = file_digest_and_size(physical_path)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(restored_hash, old_hash)

    @patch("app.services.onlyoffice_health_service.urlopen")
    def test_workflow_send_to_review_is_blocked_while_editing(self, urlopen_mock):
        urlopen_mock.return_value = FakeHttpResponse(200)
        document, version = self.add_document_with_file(content=self.minimal_docx())
        self.login(201).get(f"/documentacion/{document.id}/versiones/{version.id}/onlyoffice/editar")

        response = self.login(201).post(f"/documentacion/{document.id}/enviar-revision", data={"comentario": ""})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.session.get(DocumentoVersion, version.id).estado, "EN_ELABORACION")


if __name__ == "__main__":
    unittest.main()
