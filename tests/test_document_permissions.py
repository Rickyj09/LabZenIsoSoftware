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
from app.security.permissions import user_has_permission


DOCUMENT_PERMISSIONS = {
    "ver",
    "crear",
    "editar",
    "enviar_revision",
    "aprobar",
    "rechazar",
    "devolver_borrador",
    "obsoletar",
    "descargar",
    "ver_historial",
    "ver_pendientes",
}

ROLE_MATRIX = {
    "CALIDAD": DOCUMENT_PERMISSIONS,
    "TECNICO": {"ver", "crear", "editar", "enviar_revision", "descargar", "ver_historial"},
    "CONSULTA": {"ver", "descargar"},
}


class DocumentPermissionTest(unittest.TestCase):
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
        self.next_event_id = 9001
        self.next_document_id = 7001
        self.next_version_id = 8001
        self.next_snapshot_id = 10001

        def assign_event_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, DocumentoAprobacion) and item.id is None:
                    item.id = self.next_event_id
                    self.next_event_id += 1
                elif isinstance(item, DocumentoVersion) and item.id is None:
                    item.id = self.next_version_id
                    self.next_version_id += 1
                elif isinstance(item, Documento) and item.id is None:
                    item.id = self.next_document_id
                    self.next_document_id += 1
                elif isinstance(item, DocumentoSnapshot) and item.id is None:
                    item.id = self.next_snapshot_id
                    self.next_snapshot_id += 1

        self.assign_event_ids = assign_event_ids
        event.listen(Session, "before_flush", self.assign_event_ids)
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="calidad@test", username="calidad", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Técnico", apellido="Uno", email="tecnico@test", username="tecnico", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@test", username="consulta", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Calidad", apellido="Dos", email="calidad2@test", username="calidad2", password_hash="x", activo=True),
        ])
        db.session.flush()
        self._create_security_matrix()
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_event_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def _create_security_matrix(self):
        permission_ids = {}
        for offset, suffix in enumerate(sorted(DOCUMENT_PERMISSIONS), start=1):
            permission = Permiso(
                id=1000 + offset,
                codigo=f"documentos.{suffix}",
                nombre=suffix,
                modulo="documentos",
            )
            db.session.add(permission)
            permission_ids[suffix] = permission.id

        role_users = {"CALIDAD": [201, 204], "TECNICO": [202], "CONSULTA": [203]}
        link_id = 3000
        for offset, (role_name, permissions) in enumerate(ROLE_MATRIX.items(), start=1):
            role = Rol(id=2000 + offset, nombre=role_name, es_sistema=True)
            db.session.add(role)
            db.session.flush()
            for suffix in permissions:
                link_id += 1
                db.session.add(RolPermiso(
                    id=link_id,
                    rol_id=role.id,
                    permiso_id=permission_ids[suffix],
                ))
            for user_id in role_users[role_name]:
                link_id += 1
                db.session.add(UsuarioRol(id=link_id, usuario_id=user_id, rol_id=role.id))

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def minimal_docx(self, text="Permisos"):
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
        stream.seek(0)
        return stream

    def add_document(self, document_id, state="EN_ELABORACION", version_state="EN_ELABORACION"):
        document = Documento(
            id=document_id,
            empresa_id=101,
            codigo=f"DOC-{document_id}",
            titulo=f"Documento {document_id}",
            tipo_documento="PROCEDIMIENTO",
            estado=state,
            version_actual="1",
            elaborado_por_id=202,
        )
        version = DocumentoVersion(
            id=document_id + 1000,
            empresa_id=101,
            documento_id=document_id,
            version="1",
            estado=version_state,
            elaborado_por_id=202,
        )
        db.session.add_all([document, version])
        db.session.commit()
        return document, version

    def test_role_matrix_grants_and_denies_expected_permissions(self):
        quality = db.session.get(Usuario, 201)
        technician = db.session.get(Usuario, 202)
        consultation = db.session.get(Usuario, 203)

        self.assertTrue(user_has_permission(quality, "documentos.aprobar"))
        self.assertTrue(user_has_permission(technician, "documentos.crear"))
        self.assertTrue(user_has_permission(technician, "documentos.enviar_revision"))
        self.assertFalse(user_has_permission(technician, "documentos.aprobar"))
        self.assertFalse(user_has_permission(technician, "documentos.rechazar"))
        self.assertFalse(user_has_permission(technician, "documentos.obsoletar"))
        self.assertTrue(user_has_permission(consultation, "documentos.ver"))
        self.assertFalse(user_has_permission(consultation, "documentos.crear"))

    def test_technician_can_open_create_and_edit_forms(self):
        document, _ = self.add_document(301)
        client = self.login(202)

        self.assertEqual(client.get("/documentacion/nuevo").status_code, 200)
        self.assertEqual(client.get(f"/documentacion/{document.id}/editar").status_code, 200)

    def test_technician_can_create_and_send_document_to_review(self):
        client = self.login(202)
        creation = client.post("/documentacion/nuevo", data={
            "codigo": "DOC-TECNICO",
            "titulo": "Documento técnico",
            "tipo_documento": "PROCEDIMIENTO",
            "version": "1",
            "archivo": (self.minimal_docx("Documento tecnico"), "documento-tecnico.docx"),
            "cambios": "Versión inicial",
        })
        document = Documento.query.filter_by(codigo="DOC-TECNICO").one()
        version = DocumentoVersion.query.filter_by(documento_id=document.id).one()

        self.assertEqual(creation.status_code, 302)
        submission = client.post(
            f"/documentacion/{document.id}/enviar-revision",
            data={"comentario": "Lista para revisión"},
        )
        db.session.refresh(version)
        self.assertEqual(submission.status_code, 302)
        self.assertEqual(version.estado, "EN_REVISION")

    def test_consultation_cannot_create_or_edit(self):
        document, _ = self.add_document(302)
        client = self.login(203)

        self.assertEqual(client.get("/documentacion/").status_code, 200)
        self.assertEqual(client.get("/documentacion/nuevo").status_code, 403)
        self.assertEqual(client.get(f"/documentacion/{document.id}/editar").status_code, 403)

    def test_technician_direct_posts_to_restricted_actions_return_403(self):
        review_document, review = self.add_document(303, "EN_REVISION", "EN_REVISION")
        approved_document, approved = self.add_document(304, "APROBADO", "APROBADO")
        approved_document.version_vigente_id = approved.id
        db.session.commit()
        client = self.login(202)

        self.assertEqual(client.post(f"/documentacion/{review_document.id}/aprobar-version/{review.id}").status_code, 403)
        self.assertEqual(client.post(f"/documentacion/{review_document.id}/rechazar-version/{review.id}", data={"comentario": "No"}).status_code, 403)
        self.assertEqual(client.post(f"/documentacion/{approved_document.id}/obsoletar", data={"motivo": "No"}).status_code, 403)

    def test_quality_can_reach_approval_rejection_and_obsolescence_actions(self):
        review_document, review = self.add_document(305, "EN_REVISION", "EN_REVISION")
        client = self.login(201)
        approval = client.post(
            f"/documentacion/{review_document.id}/aprobar-version/{review.id}",
            data={"comentario": "Conforme"},
        )
        self.assertEqual(approval.status_code, 302)

        reject_document, reject_version = self.add_document(306, "EN_REVISION", "EN_REVISION")
        rejection = client.post(
            f"/documentacion/{reject_document.id}/rechazar-version/{reject_version.id}",
            data={"comentario": "Corregir"},
        )
        self.assertEqual(rejection.status_code, 302)

        obsolete_document, obsolete_version = self.add_document(307, "APROBADO", "APROBADO")
        obsolete_document.version_vigente_id = obsolete_version.id
        db.session.commit()
        obsolescence = client.post(
            f"/documentacion/{obsolete_document.id}/obsoletar",
            data={"motivo": "Reemplazado"},
        )
        self.assertEqual(obsolescence.status_code, 302)

    def test_buttons_are_hidden_for_consultation_user(self):
        document, _ = self.add_document(308)
        response = self.login(203).get(f"/documentacion/{document.id}")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Enviar a revisión", body)
        self.assertNotIn("Aprobar", body)
        self.assertNotIn("Marcar obsoleto", body)
        self.assertNotIn("Historial de versiones", body)


if __name__ == "__main__":
    unittest.main()
