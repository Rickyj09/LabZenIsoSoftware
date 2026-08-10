import tempfile
import unittest
import zipfile
from io import BytesIO

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.documentos import Documento, DocumentoAprobacion, DocumentoSnapshot, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_pending_service import (
    count_pending_documents_for_user,
    get_pending_documents_for_user,
    user_has_document_pending_alert,
)
from app.services.document_workflow_service import (
    approve_version,
    mark_review_conformity,
    request_review_corrections,
)
from app.services.document_workflow_service import send_for_review
from app.services.storage_service import apply_stored_file_metadata, store_document_file
from werkzeug.datastructures import FileStorage


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
        self.next_snapshot_id = 9001

        def assign_event_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, DocumentoAprobacion) and item.id is None:
                    item.id = self.next_event_id
                    self.next_event_id += 1
                elif isinstance(item, DocumentoSnapshot) and item.id is None:
                    item.id = self.next_snapshot_id
                    self.next_snapshot_id += 1

        self.assign_event_ids = assign_event_ids
        event.listen(Session, "before_flush", self.assign_event_ids)

        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="quality@pending", username="quality", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Técnico", apellido="Uno", email="tech@pending", username="tech", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=102, nombre="Calidad", apellido="Dos", email="quality2@pending", username="quality2", password_hash="x", activo=True),
            Usuario(id=205, empresa_id=101, nombre="Calidad", apellido="Alterna", email="quality-alt@pending", username="quality-alt", password_hash="x", activo=True),
            Usuario(id=206, empresa_id=101, nombre="Revisor", apellido="Documental", email="reviewer@pending", username="reviewer", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, suffix in enumerate(("ver", "aprobar", "rechazar", "ver_pendientes", "revisar", "ver_historial", "descargar"), start=1):
            permission = Permiso(id=1000 + offset, codigo=f"documentos.{suffix}", nombre=suffix, modulo="documentos")
            permissions[suffix] = permission
            db.session.add(permission)
        quality_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        technical_role = Rol(id=2002, nombre="TECNICO", es_sistema=True)
        reviewer_role = Rol(id=2003, nombre="REVISOR_DOCUMENTAL", es_sistema=True)
        db.session.add_all([quality_role, technical_role, reviewer_role])
        db.session.flush()
        link_id = 3000
        for permission in permissions.values():
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=quality_role.id, permiso_id=permission.id))
        link_id += 1
        db.session.add(RolPermiso(id=link_id, rol_id=technical_role.id, permiso_id=permissions["ver"].id))
        for suffix in ("ver", "descargar", "ver_historial", "ver_pendientes", "revisar"):
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=reviewer_role.id, permiso_id=permissions[suffix].id))
        db.session.add_all([
            UsuarioRol(id=4001, usuario_id=201, rol_id=quality_role.id),
            UsuarioRol(id=4002, usuario_id=203, rol_id=quality_role.id),
            UsuarioRol(id=4003, usuario_id=202, rol_id=technical_role.id),
            UsuarioRol(id=4004, usuario_id=205, rol_id=quality_role.id),
            UsuarioRol(id=4005, usuario_id=206, rol_id=reviewer_role.id),
        ])
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_event_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def add_version(self, item_id, state, *, company_id=101, assigned_to=None, author_id=None, approver_id=None):
        default_author_id = 202 if company_id == 101 else 203
        author_id = author_id or default_author_id
        reviewer_id = assigned_to if state == "EN_REVISION" else None
        if state == "EN_REVISION" and reviewer_id is None:
            reviewer_id = 201 if company_id == 101 else 203
        approval_user_id = approver_id if state == "EN_APROBACION" else None
        if state == "EN_APROBACION" and approval_user_id is None:
            approval_user_id = 201 if company_id == 101 else 203
        document = Documento(
            id=item_id,
            empresa_id=company_id,
            codigo=f"DOC-{item_id}",
            titulo=f"Documento {item_id}",
            tipo_documento="PROCEDIMIENTO",
            estado=state,
            version_actual="1",
            elaborado_por_id=author_id,
        )
        version = DocumentoVersion(
            id=item_id + 1000,
            empresa_id=company_id,
            documento_id=item_id,
            version="1",
            estado=state,
            elaborado_por_id=author_id,
            revisado_por_id=reviewer_id,
            aprobado_por_id=approval_user_id,
        )
        db.session.add_all([document, version])
        db.session.commit()
        return document, version

    def minimal_docx(self, text="Pendiente"):
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

    def add_review_version_with_snapshot(self, item_id):
        document, version = self.add_version(item_id, "EN_ELABORACION")
        stored = store_document_file(
            FileStorage(
                stream=BytesIO(self.minimal_docx(f"DOC-{item_id}")),
                filename=f"DOC-{item_id}.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            documento=document,
            version=version.version,
        )
        apply_stored_file_metadata(version, stored)
        version.revisado_por_id = 201
        version.aprobado_por_id = 205
        send_for_review(
            documento=document,
            version_doc=version,
            usuario=db.session.get(Usuario, 202),
            resumen_cambios="Listo",
            hojas_modificadas="No aplica",
        )
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

    def test_documental_reviewer_can_access_assigned_review_pending(self):
        _, expected = self.add_version(312, "EN_REVISION", assigned_to=206)
        self.add_version(313, "EN_REVISION", assigned_to=201)
        reviewer = db.session.get(Usuario, 206)

        pending = get_pending_documents_for_user(reviewer)
        response = self.login(206).get("/documentacion/pendientes")
        body = response.get_data(as_text=True)

        self.assertEqual([item.id for item in pending], [expected.id])
        self.assertEqual(count_pending_documents_for_user(reviewer), 1)
        self.assertEqual(response.status_code, 200)
        self.assertIn("DOC-312", body)
        self.assertNotIn("DOC-313", body)
        self.assertIn("1 pendiente(s)", body)

    def test_documental_reviewer_sidebar_badge_reflects_assigned_pending(self):
        self.add_version(314, "EN_REVISION", assigned_to=206)

        response = self.login(206).get("/documentacion/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Mis pendientes", body)
        self.assertIn("Tiene 1 documento(s) pendiente(s)", body)
        self.assertIn('<span class="badge bg-danger ms-1">1</span>', body)

    def test_user_with_view_only_does_not_see_pending_link(self):
        self.add_version(315, "EN_REVISION", assigned_to=201)

        response = self.login(202).get("/documentacion/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Mis pendientes", body)
        self.assertEqual(self.login(202).get("/documentacion/pendientes").status_code, 403)

    def test_documental_reviewer_can_open_detail_for_assigned_pending(self):
        document, _ = self.add_version(316, "EN_REVISION", assigned_to=206)

        response = self.login(206).get(f"/documentacion/{document.id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("DOC-316", response.get_data(as_text=True))

    def test_empty_pending_page_has_friendly_message(self):
        response = self.login(201).get("/documentacion/pendientes")

        self.assertEqual(response.status_code, 200)
        self.assertIn("No tiene documentos pendientes", response.get_data(as_text=True))

    def test_alert_disappears_after_approval(self):
        document, version = self.add_review_version_with_snapshot(310)
        quality = db.session.get(Usuario, 201)
        self.assertEqual(count_pending_documents_for_user(quality), 1)

        mark_review_conformity(
            documento=document,
            version_doc=version,
            usuario=quality,
            comentario="Conforme",
        )
        version.aprobado_por_id = 205
        db.session.commit()
        approver = db.session.get(Usuario, 205)
        self.assertEqual(count_pending_documents_for_user(quality), 0)
        self.assertEqual(count_pending_documents_for_user(approver), 1)
        approve_version(documento=document, version_doc=version, usuario=approver)
        db.session.commit()

        self.assertEqual(count_pending_documents_for_user(approver), 0)

    def test_alert_disappears_after_rejection(self):
        document, version = self.add_review_version_with_snapshot(311)
        quality = db.session.get(Usuario, 201)
        self.assertEqual(count_pending_documents_for_user(quality), 1)

        request_review_corrections(
            documento=document,
            version_doc=version,
            usuario=quality,
            comentario="Debe corregirse",
        )
        db.session.commit()

        self.assertEqual(count_pending_documents_for_user(quality), 0)


if __name__ == "__main__":
    unittest.main()
