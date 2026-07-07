import tempfile
import unittest

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import Documento, DocumentoAprobacion, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_dashboard_service import get_document_dashboard_stats


class DocumentDashboardTest(unittest.TestCase):
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
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="quality@dash", username="quality", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Técnico", apellido="Uno", email="tech@dash", username="tech", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@dash", username="consulta", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Calidad", apellido="Dos", email="quality2@dash", username="quality2", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, suffix in enumerate(("ver", "aprobar", "rechazar", "ver_pendientes"), start=1):
            permission = Permiso(id=1000 + offset, codigo=f"documentos.{suffix}", nombre=suffix, modulo="documentos")
            db.session.add(permission)
            permissions[suffix] = permission
        quality_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        technical_role = Rol(id=2002, nombre="TECNICO", es_sistema=True)
        consultation_role = Rol(id=2003, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([quality_role, technical_role, consultation_role])
        db.session.flush()
        link_id = 3000
        for suffix in ("ver", "aprobar", "rechazar", "ver_pendientes"):
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=quality_role.id, permiso_id=permissions[suffix].id))
        for role in (technical_role, consultation_role):
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=role.id, permiso_id=permissions["ver"].id))
        db.session.add_all([
            UsuarioRol(id=4001, usuario_id=201, rol_id=quality_role.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=technical_role.id),
            UsuarioRol(id=4003, usuario_id=203, rol_id=consultation_role.id),
            UsuarioRol(id=4004, usuario_id=204, rol_id=quality_role.id),
        ])

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def add_document(self, document_id, code, state, version_state, *, company_id=101, document_type="PROCEDIMIENTO"):
        document = Documento(
            id=document_id,
            empresa_id=company_id,
            codigo=code,
            titulo=f"{code} título",
            tipo_documento=document_type,
            estado=state,
            version_actual="1",
            elaborado_por_id=202 if company_id == 101 else 204,
        )
        version = DocumentoVersion(
            id=document_id + 1000,
            empresa_id=company_id,
            documento_id=document_id,
            version="1",
            estado=version_state,
            elaborado_por_id=202 if company_id == 101 else 204,
        )
        db.session.add_all([document, version])
        db.session.commit()
        return document, version

    def test_dashboard_loads_for_authorized_user(self):
        response = self.login(201).get("/documentacion/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Dashboard documental", response.get_data(as_text=True))

    def test_core_documental_views_load_for_authorized_user(self):
        client = self.login(201)

        for path in (
            "/documentacion/dashboard",
            "/documentacion/pendientes",
            "/documentacion/",
            "/documentacion/archivo",
            "/documentacion/registros",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

    def test_dashboard_filters_by_company_id(self):
        self.add_document(301, "EMP1-DOC", "BORRADOR", "BORRADOR", company_id=101)
        self.add_document(302, "EMP2-DOC", "BORRADOR", "BORRADOR", company_id=102)

        response = self.login(201).get("/documentacion/dashboard")
        body = response.get_data(as_text=True)

        self.assertIn("EMP1-DOC", body)
        self.assertNotIn("EMP2-DOC", body)

    def test_dashboard_counts_document_states(self):
        self.add_document(303, "DOC-BOR", "BORRADOR", "BORRADOR")
        self.add_document(304, "DOC-REV", "EN_REVISION", "EN_REVISION")
        self.add_document(305, "DOC-RECH", "RECHAZADO", "RECHAZADO")
        self.add_document(306, "DOC-OBS", "OBSOLETO", "OBSOLETO")
        approved, version = self.add_document(307, "DOC-APR", "APROBADO", "APROBADO")
        approved.version_vigente_id = version.id
        db.session.commit()

        stats = get_document_dashboard_stats(db.session.get(Usuario, 201))

        self.assertEqual(stats["technical_status"]["BORRADOR"], 1)
        self.assertEqual(stats["technical_status"]["EN_REVISION"], 1)
        self.assertEqual(stats["technical_status"]["RECHAZADO"], 1)
        self.assertEqual(stats["technical_status"]["OBSOLETO"], 1)
        self.assertEqual(stats["technical_status"]["APROBADO"], 1)

    def test_dashboard_calculates_current_and_in_update(self):
        current, current_version = self.add_document(308, "DOC-VIG", "APROBADO", "APROBADO")
        current.version_vigente_id = current_version.id
        updating, updating_v1 = self.add_document(309, "DOC-ACT", "APROBADO", "APROBADO")
        updating.version_vigente_id = updating_v1.id
        db.session.add(DocumentoVersion(
            id=4091,
            empresa_id=101,
            documento_id=updating.id,
            version="2",
            estado="BORRADOR",
            elaborado_por_id=202,
        ))
        db.session.commit()

        stats = get_document_dashboard_stats(db.session.get(Usuario, 201))

        self.assertEqual(stats["flow_status"]["VIGENTE"], 1)
        self.assertEqual(stats["flow_status"]["EN_ACTUALIZACION"], 1)

    def test_dashboard_pending_visible_only_to_authorized_reviewers(self):
        self.add_document(310, "DOC-PEND", "EN_REVISION", "EN_REVISION")

        quality_body = self.login(201).get("/documentacion/dashboard").get_data(as_text=True)

        self.assertIn("DOC-PEND", quality_body)
        self.assertEqual(get_document_dashboard_stats(db.session.get(Usuario, 202))["pending_count"], 0)
        self.assertEqual(get_document_dashboard_stats(db.session.get(Usuario, 203))["pending_count"], 0)

    def test_dashboard_shows_recent_documents(self):
        self.add_document(311, "DOC-RECENT", "BORRADOR", "BORRADOR")

        response = self.login(201).get("/documentacion/dashboard")

        self.assertIn("DOC-RECENT", response.get_data(as_text=True))

    def test_dashboard_counts_documents_without_file(self):
        self.add_document(312, "DOC-SIN-ARCHIVO", "BORRADOR", "BORRADOR")

        stats = get_document_dashboard_stats(db.session.get(Usuario, 201))
        response = self.login(201).get("/documentacion/dashboard")

        self.assertEqual(stats["documents_without_file_count"], 1)
        self.assertIn("sin archivo asociado", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
