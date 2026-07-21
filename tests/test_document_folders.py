import tempfile
import unittest
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.auditoria import AuditoriaLog
from app.models.base import BaseModel
from app.models.documentos import (
    ARTEFACTO_DISPONIBLE,
    ARTEFACTO_PDF_APROBADO,
    CarpetaDocumental,
    Documento,
    DocumentoArtefacto,
    DocumentoFirmaProceso,
    DocumentoSnapshot,
    DocumentoVersion,
    ESTADO_APROBADO,
    ESTADO_EN_ELABORACION,
    FIRMA_PROCESO_EN_FIRMA,
)
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_explorer_service import DocumentExplorerService
from app.services.document_folder_service import DocumentFolderError, DocumentFolderService


class DocumentFoldersTest(unittest.TestCase):
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
        self.next_id = 70000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        self.seed_security()
        self.seed_documents()
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def seed_security(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@folders", username="admin", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@folders", username="consulta", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@folders", username="admin2", password_hash="x", activo=True),
        ])
        permission_codes = [
            "documentos.ver",
            "documentos.descargar",
            "documentos.ver_historial",
            "documentos.carpetas.crear",
            "documentos.carpetas.editar",
            "documentos.carpetas.eliminar",
            "documentos.carpetas.mover_documentos",
        ]
        permissions = {}
        for offset, code in enumerate(permission_codes, start=1):
            permission = Permiso(id=1000 + offset, codigo=code, nombre=code, modulo="documentos")
            db.session.add(permission)
            permissions[code] = permission
        admin_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        viewer_role = Rol(id=2002, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([admin_role, viewer_role])
        db.session.flush()
        link_id = 3000
        for permission in permissions.values():
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=admin_role.id, permiso_id=permission.id))
        for code in ("documentos.ver", "documentos.descargar"):
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=viewer_role.id, permiso_id=permissions[code].id))
        db.session.add_all([
            UsuarioRol(id=4001, usuario_id=201, rol_id=admin_role.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=viewer_role.id),
            UsuarioRol(id=4003, usuario_id=203, rol_id=admin_role.id),
        ])

    def seed_documents(self):
        approved = Documento(
            id=501,
            empresa_id=101,
            codigo="DOC-APROBADO",
            titulo="Procedimiento aprobado",
            tipo_documento="PROCEDIMIENTO",
            proceso="Ensayos",
            estado=ESTADO_APROBADO,
            version_actual="1",
            elaborado_por_id=201,
        )
        version = DocumentoVersion(
            id=1501,
            empresa_id=101,
            documento_id=501,
            version="1",
            estado=ESTADO_APROBADO,
            archivo_nombre_original="principal.docx",
            archivo_nombre_guardado="principal.docx",
            archivo_storage_path="documentos/101/principal.docx",
            archivo_sha256="a" * 64,
            elaborado_por_id=201,
        )
        draft = Documento(
            id=502,
            empresa_id=101,
            codigo="DOC-BORRADOR",
            titulo="Instructivo en elaboracion",
            tipo_documento="INSTRUCTIVO",
            proceso="Calidad",
            estado=ESTADO_EN_ELABORACION,
            version_actual="1",
            elaborado_por_id=201,
        )
        draft_version = DocumentoVersion(
            id=1502,
            empresa_id=101,
            documento_id=502,
            version="1",
            estado=ESTADO_EN_ELABORACION,
            archivo_nombre_original="borrador.docx",
            archivo_sha256="b" * 64,
            elaborado_por_id=201,
        )
        other = Documento(
            id=601,
            empresa_id=102,
            codigo="OTRA-EMPRESA",
            titulo="Documento otra empresa",
            tipo_documento="PROCEDIMIENTO",
            proceso="Otro",
            estado=ESTADO_APROBADO,
            version_actual="1",
            elaborado_por_id=203,
        )
        snapshot = DocumentoSnapshot(
            id=2501,
            empresa_id=101,
            public_id="snap-folder",
            documento_id=501,
            documento_version_id=1501,
            secuencia=1,
            ciclo_revision=1,
            tipo="APROBADO",
            estado="DISPONIBLE",
            storage_path="snapshots/principal.docx",
            archivo_nombre_interno="principal.docx",
            archivo_nombre_original="principal.docx",
            archivo_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            archivo_size=100,
            archivo_sha256="c" * 64,
            hash_origen="a" * 64,
            creado_por_id=201,
            creado_en=datetime.now(timezone.utc),
            inmutable=True,
        )
        artifact = DocumentoArtefacto(
            id=3501,
            empresa_id=101,
            public_id="pdf-folder",
            documento_id=501,
            documento_version_id=1501,
            source_snapshot_id=2501,
            tipo=ARTEFACTO_PDF_APROBADO,
            estado=ARTEFACTO_DISPONIBLE,
            storage_path="pdf/aprobado.pdf",
            archivo_nombre_interno="aprobado.pdf",
            archivo_nombre_visible="aprobado.pdf",
            archivo_mime="application/pdf",
            archivo_size=100,
            archivo_sha256="d" * 64,
            source_snapshot_sha256="c" * 64,
            page_count=1,
            provider="onlyoffice",
            creado_por_id=201,
            creado_en=datetime.now(timezone.utc),
            disponible_en=datetime.now(timezone.utc),
            inmutable=True,
        )
        signature = DocumentoFirmaProceso(
            id=4501,
            empresa_id=101,
            public_id="firma-folder",
            documento_id=501,
            documento_version_id=1501,
            pdf_origen_id=3501,
            provider="external_controlled",
            estado=FIRMA_PROCESO_EN_FIRMA,
            solicitado_por_id=201,
            solicitado_en=datetime.now(timezone.utc),
        )
        db.session.add_all([approved, version, draft, draft_version, other, snapshot, artifact, signature])

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def test_create_root_subfolder_breadcrumb_and_listing(self):
        service = DocumentFolderService()
        root = service.create_folder(user=Usuario.query.get(201), nombre="Procedimientos", descripcion="Docs controlados")
        child = service.create_folder(user=Usuario.query.get(201), nombre="Tecnicos", parent_id=root.id)
        db.session.commit()

        breadcrumb = DocumentExplorerService().breadcrumb(folder=child)
        self.assertEqual([item.nombre for item in breadcrumb], ["Procedimientos", "Tecnicos"])

        response = self.login(201).get(f"/documentacion/explorador/carpetas/{root.id}")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Tecnicos", body)
        self.assertIn("Docs controlados", body)

    def test_uncategorized_documents_are_visible(self):
        response = self.login(201).get("/documentacion/explorador/sin-clasificar")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("DOC-APROBADO", body)
        self.assertIn("DOC-BORRADOR", body)

    def test_assign_move_and_remove_document_without_touching_workflow_artifacts(self):
        service = DocumentFolderService()
        user = Usuario.query.get(201)
        folder_a = service.create_folder(user=user, nombre="A")
        folder_b = service.create_folder(user=user, nombre="B")
        db.session.commit()
        document = Documento.query.get(501)
        before = {
            "estado": document.estado,
            "versiones": DocumentoVersion.query.filter_by(documento_id=501).count(),
            "sha": DocumentoVersion.query.get(1501).archivo_sha256,
            "snapshot_sha": DocumentoSnapshot.query.get(2501).archivo_sha256,
            "artifact_sha": DocumentoArtefacto.query.get(3501).archivo_sha256,
            "signatures": DocumentoFirmaProceso.query.filter_by(documento_id=501).count(),
        }

        service.assign_document(user=user, document_id=501, folder_id=folder_a.id)
        service.assign_document(user=user, document_id=501, folder_id=folder_b.id)
        service.assign_document(user=user, document_id=501, folder_id=None)
        db.session.commit()
        document = Documento.query.get(501)

        self.assertIsNone(document.carpeta_id)
        self.assertEqual(document.estado, before["estado"])
        self.assertEqual(DocumentoVersion.query.filter_by(documento_id=501).count(), before["versiones"])
        self.assertEqual(DocumentoVersion.query.get(1501).archivo_sha256, before["sha"])
        self.assertEqual(DocumentoSnapshot.query.get(2501).archivo_sha256, before["snapshot_sha"])
        self.assertEqual(DocumentoArtefacto.query.get(3501).archivo_sha256, before["artifact_sha"])
        self.assertEqual(DocumentoFirmaProceso.query.filter_by(documento_id=501).count(), before["signatures"])
        self.assertGreaterEqual(AuditoriaLog.query.filter_by(registro_id=501).count(), 3)

    def test_rename_move_and_cycle_guards(self):
        service = DocumentFolderService()
        user = Usuario.query.get(201)
        parent = service.create_folder(user=user, nombre="Padre")
        child = service.create_folder(user=user, nombre="Hijo", parent_id=parent.id)
        db.session.commit()

        service.update_folder(user=user, folder_id=child.id, nombre="Hijo renombrado", descripcion="Nueva")
        service.move_folder(user=user, folder_id=child.id, parent_id=None)
        db.session.commit()

        self.assertEqual(CarpetaDocumental.query.get(child.id).nombre, "Hijo renombrado")
        self.assertIsNone(CarpetaDocumental.query.get(child.id).padre_id)
        with self.assertRaises(DocumentFolderError):
            service.move_folder(user=user, folder_id=parent.id, parent_id=parent.id)
        service.move_folder(user=user, folder_id=child.id, parent_id=parent.id)
        db.session.flush()
        with self.assertRaises(DocumentFolderError):
            service.move_folder(user=user, folder_id=parent.id, parent_id=child.id)

    def test_delete_rules_for_documents_subfolders_and_empty_folder(self):
        service = DocumentFolderService()
        user = Usuario.query.get(201)
        folder = service.create_folder(user=user, nombre="Con documento")
        child_parent = service.create_folder(user=user, nombre="Con hijo")
        empty = service.create_folder(user=user, nombre="Vacia")
        child = service.create_folder(user=user, nombre="Hijo", parent_id=child_parent.id)
        db.session.flush()
        service.assign_document(user=user, document_id=501, folder_id=folder.id)
        db.session.commit()

        with self.assertRaisesRegex(DocumentFolderError, "contiene documentos"):
            service.deactivate_folder(user=user, folder_id=folder.id)
        with self.assertRaisesRegex(DocumentFolderError, "contiene documentos"):
            service.deactivate_folder(user=user, folder_id=child_parent.id)
        service.deactivate_folder(user=user, folder_id=empty.id)
        db.session.commit()

        self.assertFalse(CarpetaDocumental.query.get(empty.id).activa)
        self.assertTrue(CarpetaDocumental.query.get(child.id).activa)

    def test_permissions_are_enforced_for_folder_and_document_moves(self):
        viewer = Usuario.query.get(202)
        admin = Usuario.query.get(201)
        folder = DocumentFolderService().create_folder(user=admin, nombre="Privada")
        db.session.commit()

        with self.assertRaises(DocumentFolderError):
            DocumentFolderService().create_folder(user=viewer, nombre="No")
        with self.assertRaises(DocumentFolderError):
            DocumentFolderService().assign_document(user=viewer, document_id=501, folder_id=folder.id)

        response = self.login(202).post("/documentacion/explorador/carpetas", data={"nombre": "No"})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(CarpetaDocumental.query.filter_by(nombre="No").first())

    def test_cross_tenant_guards(self):
        service = DocumentFolderService()
        folder = service.create_folder(user=Usuario.query.get(201), nombre="Empresa uno")
        other_user = Usuario.query.get(203)
        db.session.commit()

        self.assertEqual(self.login(203).get(f"/documentacion/explorador/carpetas/{folder.id}").status_code, 404)
        with self.assertRaises(DocumentFolderError):
            service.assign_document(user=other_user, document_id=501, folder_id=folder.id)
        with self.assertRaises(DocumentFolderError):
            service.assign_document(user=Usuario.query.get(201), document_id=601, folder_id=folder.id)
        with self.assertRaises(DocumentFolderError):
            service.move_folder(user=other_user, folder_id=folder.id, parent_id=None)

    def test_search_and_filters_are_scoped_to_active_folder(self):
        service = DocumentFolderService()
        user = Usuario.query.get(201)
        folder = service.create_folder(user=user, nombre="Calidad")
        other = service.create_folder(user=user, nombre="Ensayos")
        db.session.flush()
        service.assign_document(user=user, document_id=502, folder_id=folder.id)
        service.assign_document(user=user, document_id=501, folder_id=other.id)
        db.session.commit()

        client = self.login(201)
        response = client.get(f"/documentacion/explorador/carpetas/{folder.id}?q=Instructivo&estado=EN_ELABORACION&tipo=INSTRUCTIVO&proceso=Calidad")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("DOC-BORRADOR", body)
        self.assertNotIn("DOC-APROBADO", body)

    def test_current_document_views_still_respond(self):
        client = self.login(201)

        self.assertEqual(client.get("/documentacion/").status_code, 200)
        self.assertEqual(client.get("/documentacion/501").status_code, 200)
        self.assertEqual(client.get("/documentacion/explorador").status_code, 200)
        self.assertEqual(client.get("/documentacion/explorador/carpetas/999999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
