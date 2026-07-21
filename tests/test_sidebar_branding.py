import tempfile
import unittest

from app import create_app
from app.extensions import db
from app.models.empresa import Empresa
from app.models.seguridad import Usuario


class SidebarBrandingTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DOCUMENT_STORAGE_ROOT": self.temp_directory.name,
            "DOCUMENT_LEGACY_STORAGE_ROOT": self.temp_directory.name,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.seed_data()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def seed_data(self):
        long_name = "Laboratorio de Ensayos Fisicoquimicos y Metrologia Especializada del Austro"
        db.session.add_all([
            Empresa(id=101, nombre="Laboratorio Andino"),
            Empresa(id=102, nombre="Laboratorio Pacifico"),
            Empresa(id=103, nombre=long_name),
            Usuario(id=201, empresa_id=101, nombre="Ana", apellido="Uno", email="ana@lab", username="ana", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=102, nombre="Bea", apellido="Dos", email="bea@lab", username="bea", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=999, nombre="Sin", apellido="Empresa", email="sin@lab", username="sinempresa", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=103, nombre="Largo", apellido="Nombre", email="largo@lab", username="largo", password_hash="x", activo=True),
        ])

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def test_sidebar_shows_current_laboratory_name_and_branding(self):
        response = self.login(201).get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("LabZenISO", body)
        self.assertIn("Software", body)
        self.assertIn("LIMS + SGC ISO 17025", body)
        self.assertIn("Laboratorio Andino", body)

    def test_sidebar_laboratory_name_changes_by_company(self):
        body = self.login(202).get("/").get_data(as_text=True)

        self.assertIn("Laboratorio Pacifico", body)
        self.assertNotIn("Laboratorio Andino", body)

    def test_sidebar_uses_safe_fallback_without_company(self):
        response = self.login(203).get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Laboratorio no configurado", body)

    def test_sidebar_renders_long_laboratory_name(self):
        response = self.login(204).get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Laboratorio de Ensayos Fisicoquimicos", body)
        self.assertIn("sidebar-laboratory-name", body)


if __name__ == "__main__":
    unittest.main()
