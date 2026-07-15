import tempfile
import unittest
import subprocess
from io import BytesIO
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.error import URLError

import jwt
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import Documento, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.onlyoffice_health_service import OnlyOfficeHealthService
from app.services.onlyoffice_jwt_service import (
    generate_onlyoffice_document_token,
    generate_onlyoffice_ping_token,
)
from app.services.storage_service import apply_stored_file_metadata, store_document_file
from werkzeug.datastructures import FileStorage


class FakeHttpResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status_code


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
        history_permission = Permiso(
            id=1002,
            codigo="documentos.ver_historial",
            nombre="Ver historial documental",
            modulo="documentos",
        )
        quality_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        consultation_role = Rol(id=2002, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([view_permission, history_permission, quality_role, consultation_role])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=quality_role.id, permiso_id=view_permission.id),
            RolPermiso(id=3002, rol_id=quality_role.id, permiso_id=history_permission.id),
            UsuarioRol(id=4001, usuario_id=201, rol_id=quality_role.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=consultation_role.id),
            UsuarioRol(id=4003, usuario_id=203, rol_id=quality_role.id),
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


if __name__ == "__main__":
    unittest.main()
