import tempfile
import unittest
import subprocess
from datetime import datetime, timedelta, timezone
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
from app.services.onlyoffice_jwt_service import generate_onlyoffice_ping_token


class FakeHttpResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status_code


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
        ])
        permission = Permiso(
            id=1001,
            codigo="documentos.ver_historial",
            nombre="Ver historial documental",
            modulo="documentos",
        )
        quality_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        consultation_role = Rol(id=2002, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([permission, quality_role, consultation_role])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=quality_role.id, permiso_id=permission.id),
            UsuarioRol(id=4001, usuario_id=201, rol_id=quality_role.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=consultation_role.id),
        ])

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

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


if __name__ == "__main__":
    unittest.main()
