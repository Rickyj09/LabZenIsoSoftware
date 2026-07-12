import tempfile
import unittest

from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_versioning_service import (
    DocumentVersioningError,
    approve_version,
    create_draft_version,
    create_initial_version,
    send_to_review,
)


class DocumentVersioningTest(unittest.TestCase):
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
        self.next_version_id = 1001

        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(
                id=201,
                empresa_id=101,
                nombre="Usuario",
                apellido="Uno",
                email="uno@versiones.test",
                username="versiones-uno",
                password_hash="test",
                activo=True,
            ),
            Usuario(
                id=202,
                empresa_id=102,
                nombre="Usuario",
                apellido="Dos",
                email="dos@versiones.test",
                username="versiones-dos",
                password_hash="test",
                activo=True,
            ),
        ])
        edit_role = Rol(id=401, nombre="TEST_EDITOR", es_sistema=False)
        edit_permission = Permiso(
            id=402,
            codigo="documentos.editar",
            nombre="Editar documentos",
            modulo="documentos",
        )
        db.session.add_all([edit_role, edit_permission])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=403, rol_id=edit_role.id, permiso_id=edit_permission.id),
            UsuarioRol(id=404, usuario_id=201, rol_id=edit_role.id),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def make_document(self, document_id, empresa_id=101, estado="EN_ELABORACION"):
        document = Documento(
            id=document_id,
            empresa_id=empresa_id,
            codigo=f"DOC-{document_id}",
            titulo=f"Documento {document_id}",
            tipo_documento="PROCEDIMIENTO",
            estado=estado,
            version_actual="1",
            elaborado_por_id=201 if empresa_id == 101 else 202,
        )
        db.session.add(document)
        db.session.flush()
        return document

    def assign_version_id(self, version_doc):
        version_doc.id = self.next_version_id
        self.next_version_id += 1
        return version_doc

    def initial(self, document, version="1", user_id=201):
        version_doc = create_initial_version(
            documento=document,
            version=version,
            cambios="Versión inicial",
            contenido="Contenido",
            user_id=user_id,
        )
        self.assign_version_id(version_doc)
        db.session.flush()
        return version_doc

    @staticmethod
    def login(app, user_id):
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def approve_initial(self, document):
        version_doc = self.initial(document)
        send_to_review(documento=document, version_doc=version_doc, user_id=201)
        approve_version(documento=document, version_doc=version_doc, user_id=201)
        db.session.flush()
        return version_doc

    def test_new_document_and_initial_version_have_no_current_approved_version(self):
        document = self.make_document(301)
        version_doc = self.initial(document)

        self.assertEqual(document.estado, "EN_ELABORACION")
        self.assertEqual(version_doc.estado, "EN_ELABORACION")
        self.assertIsNone(document.version_vigente_id)

    def test_new_draft_does_not_replace_current_approved_version(self):
        document = self.make_document(302)
        current = self.approve_initial(document)

        draft = create_draft_version(
            documento=document,
            version="2",
            cambios="Nueva revisión",
            contenido="En elaboración",
            user_id=201,
        )
        self.assign_version_id(draft)
        db.session.flush()

        self.assertEqual(draft.estado, "EN_ELABORACION")
        self.assertEqual(document.version_vigente_id, current.id)
        self.assertEqual(document.version_actual, "1")
        self.assertEqual(document.estado, "APROBADO")

    def test_approval_updates_current_and_substitutes_previous_version(self):
        document = self.make_document(303)
        previous = self.approve_initial(document)
        draft = create_draft_version(
            documento=document,
            version="2.0",
            cambios="Cambio controlado",
            contenido="Contenido dos",
            user_id=201,
        )
        self.assign_version_id(draft)
        db.session.flush()
        send_to_review(documento=document, version_doc=draft, user_id=201)

        replaced = approve_version(documento=document, version_doc=draft, user_id=201)
        db.session.flush()

        self.assertEqual(replaced.id, previous.id)
        self.assertEqual(previous.estado, "SUSTITUIDO")
        self.assertIsNotNone(previous.fecha_obsolescencia)
        self.assertEqual(document.version_vigente_id, draft.id)
        self.assertEqual(document.version_actual, "2.0")
        self.assertEqual(draft.estado, "APROBADO")

    def test_cannot_approve_draft_directly(self):
        document = self.make_document(304)
        draft = self.initial(document)

        with self.assertRaises(DocumentVersioningError):
            approve_version(documento=document, version_doc=draft, user_id=201)

    def test_service_rejects_duplicate_version_number(self):
        document = self.make_document(305)
        self.approve_initial(document)

        with self.assertRaises(DocumentVersioningError):
            create_draft_version(
                documento=document,
                version="1",
                cambios="Duplicada",
                contenido=None,
                user_id=201,
            )

    def test_only_one_active_preparation_is_allowed(self):
        document = self.make_document(313)
        self.approve_initial(document)
        first_draft = create_draft_version(
            documento=document,
            version="2",
            cambios="Primera preparación",
            contenido=None,
            user_id=201,
        )
        self.assign_version_id(first_draft)
        db.session.flush()

        with self.assertRaises(DocumentVersioningError):
            create_draft_version(
                documento=document,
                version="3",
                cambios="Segunda preparación",
                contenido=None,
                user_id=201,
            )

    def test_database_constraint_rejects_duplicate_version_number(self):
        document = self.make_document(306)
        self.initial(document)
        db.session.add(DocumentoVersion(
            id=self.next_version_id,
            empresa_id=101,
            documento_id=document.id,
            version="1",
            estado="EN_ELABORACION",
        ))

        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_different_documents_can_use_same_version_number(self):
        first = self.make_document(307)
        second = self.make_document(308)

        self.initial(first, version="1")
        self.initial(second, version="1")
        db.session.commit()

        self.assertEqual(DocumentoVersion.query.filter_by(version="1").count(), 2)

    def test_approved_document_cannot_be_edited_directly(self):
        document = self.make_document(309, estado="APROBADO")
        db.session.commit()

        response = self.login(self.app, 201).post(
            f"/documentacion/{document.id}/editar",
            data={"codigo": "CAMBIO", "titulo": "Alterado", "tipo_documento": "MANUAL"},
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(document.codigo, "DOC-309")

    def test_document_in_review_cannot_be_edited_directly(self):
        document = self.make_document(310, estado="EN_REVISION")
        db.session.commit()

        response = self.login(self.app, 201).post(
            f"/documentacion/{document.id}/editar",
            data={"codigo": "CAMBIO", "titulo": "Alterado", "tipo_documento": "MANUAL"},
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(document.codigo, "DOC-310")

    def test_approval_rejects_version_from_another_company(self):
        document_one = self.make_document(311, empresa_id=101)
        document_two = self.make_document(312, empresa_id=102)
        other_version = self.initial(document_two, user_id=202)
        other_version.estado = "EN_REVISION"
        db.session.flush()

        with self.assertRaises(DocumentVersioningError):
            approve_version(
                documento=document_one,
                version_doc=other_version,
                user_id=201,
            )


if __name__ == "__main__":
    unittest.main()
