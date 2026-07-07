import tempfile
import unittest

from werkzeug.security import generate_password_hash
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import Documento, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Rol, Usuario, UsuarioRol
from app.services.document_dashboard_service import get_documents_in_update_count
from app.services.document_demo_seed_service import DEMO_DOCUMENTS, seed_demo_documents


class DocumentDemoSeedTest(unittest.TestCase):
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
        self.next_id = 10000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        db.session.add_all([
            Empresa(id=1, nombre="Empresa demo"),
            Rol(id=2001, nombre="CALIDAD", es_sistema=True),
            Rol(id=2002, nombre="TECNICO", es_sistema=True),
            Rol(id=2003, nombre="CONSULTA", es_sistema=True),
        ])
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def test_seed_demo_is_idempotent_and_creates_expected_documents(self):
        first = seed_demo_documents(empresa_id=1)
        first_count = Documento.query.filter(Documento.codigo.like("DEMO-%")).count()
        second = seed_demo_documents(empresa_id=1)
        second_count = Documento.query.filter(Documento.codigo.like("DEMO-%")).count()

        self.assertEqual(first_count, len(DEMO_DOCUMENTS))
        self.assertEqual(second_count, len(DEMO_DOCUMENTS))
        self.assertTrue(first["created_documents"])
        self.assertFalse(second["created_documents"])

    def test_seed_demo_creates_current_review_obsolete_and_update_documents(self):
        seed_demo_documents(empresa_id=1)

        current = Documento.query.filter_by(codigo="DEMO-VIG-001").one()
        review = Documento.query.filter_by(codigo="DEMO-REV-001").one()
        obsolete = Documento.query.filter_by(codigo="DEMO-OBS-001").one()
        updating = Documento.query.filter_by(codigo="DEMO-ACT-001").one()

        self.assertIsNotNone(current.version_vigente_id)
        self.assertEqual(review.estado, "EN_REVISION")
        self.assertEqual(obsolete.estado, "OBSOLETO")
        self.assertEqual(
            DocumentoVersion.query.filter_by(documento_id=updating.id).count(),
            2,
        )
        self.assertEqual(get_documents_in_update_count(type("User", (), {"empresa_id": 1})()), 1)

    def test_seed_demo_cli_command(self):
        result = self.app.test_cli_runner().invoke(args=["documentos", "seed-demo", "--empresa-id", "1"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("DEMO-BOR-001", result.output)
        self.assertEqual(Documento.query.filter_by(codigo="DEMO-BOR-001").count(), 1)

    def test_seed_demo_creates_demo_users_and_respects_roles(self):
        seed_demo_documents(empresa_id=1)

        quality = Usuario.query.filter_by(empresa_id=1, username="calidad_demo").one()
        technician = Usuario.query.filter_by(empresa_id=1, username="tecnico_demo").one()
        consultation = Usuario.query.filter_by(empresa_id=1, username="consulta_demo").one()

        self.assertEqual(Rol.query.filter(Rol.nombre.in_(("CALIDAD", "TECNICO", "CONSULTA"))).count(), 3)
        self.assertEqual(UsuarioRol.query.filter_by(usuario_id=quality.id).count(), 1)
        self.assertEqual(UsuarioRol.query.filter_by(usuario_id=technician.id).count(), 1)
        self.assertEqual(UsuarioRol.query.filter_by(usuario_id=consultation.id).count(), 1)

    def test_seed_demo_does_not_modify_existing_demo_user_password(self):
        original_hash = generate_password_hash("ClaveExistente123")
        existing = Usuario(
            empresa_id=1,
            nombre="Técnico",
            apellido="Existente",
            email="tecnico_existente@labzen.local",
            username="tecnico_demo",
            password_hash=original_hash,
            cargo="Cargo existente",
            activo=True,
        )
        db.session.add(existing)
        db.session.commit()

        seed_demo_documents(empresa_id=1)
        db.session.refresh(existing)

        self.assertEqual(existing.password_hash, original_hash)
        self.assertEqual(existing.email, "tecnico_existente@labzen.local")
        self.assertEqual(existing.cargo, "Cargo existente")
        self.assertEqual(Usuario.query.filter_by(empresa_id=1, username="tecnico_demo").count(), 1)


if __name__ == "__main__":
    unittest.main()
