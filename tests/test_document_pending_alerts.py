import tempfile
import unittest

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.documentos import Documento, DocumentoAprobacion, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_pending_service import (
    count_pending_documents_for_user,
    get_pending_documents_for_user,
    user_has_document_pending_alert,
)
from app.services.document_workflow_service import approve_version, reject_version


class DocumentPendingAlertTest(unittest.TestCase):
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
        self.next_event_id = 8001

        def assign_event_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, DocumentoAprobacion) and item.id is None:
                    item.id = self.next_event_id
                    self.next_event_id += 1

        self.assign_event_ids = assign_event_ids
        event.listen(Session, "before_flush", self.assign_event_ids)

        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="quality@pending", username="quality", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Técnico", apellido="Uno", email="tech@pending", username="tech", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=102, nombre="Calidad", apellido="Dos", email="quality2@pending", username="quality2", password_hash="x", activo=True),
            Usuario(id=205, empresa_id=101, nombre="Calidad", apellido="Alterna", email="quality-alt@pending", username="quality-alt", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, suffix in enumerate(("ver", "aprobar", "rechazar", "ver_pendientes"), start=1):
            permission = Permiso(id=1000 + offset, codigo=f"documentos.{suffix}", nombre=suffix, modulo="documentos")
            permissions[suffix] = permission
            db.session.add(permission)
        quality_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        technical_role = Rol(id=2002, nombre="TECNICO", es_sistema=True)
        db.session.add_all([quality_role, technical_role])
        db.session.flush()
        link_id = 3000
        for permission in permissions.values():
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=quality_role.id, permiso_id=permission.id))
        link_id += 1
        db.session.add(RolPermiso(id=link_id, rol_id=technical_role.id, permiso_id=permissions["ver"].id))
        db.session.add_all([
            UsuarioRol(id=4001, usuario_id=201, rol_id=quality_role.id),
            UsuarioRol(id=4002, usuario_id=203, rol_id=quality_role.id),
            UsuarioRol(id=4003, usuario_id=202, rol_id=technical_role.id),
            UsuarioRol(id=4004, usuario_id=205, rol_id=quality_role.id),
        ])
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_event_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def add_version(self, item_id, state, *, company_id=101, assigned_to=None):
        document = Documento(
            id=item_id,
            empresa_id=company_id,
            codigo=f"DOC-{item_id}",
            titulo=f"Documento {item_id}",
            tipo_documento="PROCEDIMIENTO",
            estado=state,
            version_actual="1",
            elaborado_por_id=201 if company_id == 101 else 203,
        )
        version = DocumentoVersion(
            id=item_id + 1000,
            empresa_id=company_id,
            documento_id=item_id,
            version="1",
            estado=state,
            elaborado_por_id=201 if company_id == 101 else 203,
            revisado_por_id=assigned_to,
        )
        db.session.add_all([document, version])
        db.session.commit()
        return document, version

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def test_quality_sees_only_review_pending_from_own_company(self):
        _, expected = self.add_version(301, "EN_REVISION")
        self.add_version(302, "EN_ELABORACION")
        self.add_version(303, "APROBADO")
        self.add_version(304, "RECHAZADO")
        self.add_version(305, "OBSOLETO")
        self.add_version(306, "EN_REVISION", company_id=102)
        quality = db.session.get(Usuario, 201)

        pending = get_pending_documents_for_user(quality)

        self.assertEqual([item.id for item in pending], [expected.id])
        self.assertEqual(count_pending_documents_for_user(quality), 1)
        self.assertTrue(user_has_document_pending_alert(quality))

    def test_technician_has_no_approval_alert(self):
        self.add_version(307, "EN_REVISION")
        technician = db.session.get(Usuario, 202)

        self.assertEqual(count_pending_documents_for_user(technician), 0)
        self.assertEqual(get_pending_documents_for_user(technician), [])
        self.assertFalse(user_has_document_pending_alert(technician))
        self.assertEqual(self.login(202).get("/documentacion/pendientes").status_code, 403)

    def test_assigned_pending_is_visible_only_to_assigned_reviewer(self):
        self.add_version(308, "EN_REVISION", assigned_to=201)
        quality_one = db.session.get(Usuario, 201)
        quality_two = db.session.get(Usuario, 205)

        self.assertEqual(count_pending_documents_for_user(quality_one), 1)
        self.assertEqual(count_pending_documents_for_user(quality_two), 0)

    def test_pending_page_and_sidebar_show_count(self):
        self.add_version(309, "EN_REVISION")
        pending_response = self.login(201).get("/documentacion/pendientes")
        index_response = self.login(201).get("/documentacion/")

        self.assertEqual(pending_response.status_code, 200)
        self.assertIn("DOC-309", pending_response.get_data(as_text=True))
        self.assertIn("1 pendiente(s)", pending_response.get_data(as_text=True))
        self.assertIn("Tiene 1 documento(s) pendiente(s)", index_response.get_data(as_text=True))

    def test_empty_pending_page_has_friendly_message(self):
        response = self.login(201).get("/documentacion/pendientes")

        self.assertEqual(response.status_code, 200)
        self.assertIn("No tiene documentos pendientes", response.get_data(as_text=True))

    def test_alert_disappears_after_approval(self):
        document, version = self.add_version(310, "EN_REVISION")
        quality = db.session.get(Usuario, 201)
        self.assertEqual(count_pending_documents_for_user(quality), 1)

        approve_version(documento=document, version_doc=version, usuario=quality)
        db.session.commit()

        self.assertEqual(count_pending_documents_for_user(quality), 0)

    def test_alert_disappears_after_rejection(self):
        document, version = self.add_version(311, "EN_REVISION")
        quality = db.session.get(Usuario, 201)
        self.assertEqual(count_pending_documents_for_user(quality), 1)

        reject_version(
            documento=document,
            version_doc=version,
            usuario=quality,
            comentario="Debe corregirse",
        )
        db.session.commit()

        self.assertEqual(count_pending_documents_for_user(quality), 0)


if __name__ == "__main__":
    unittest.main()
