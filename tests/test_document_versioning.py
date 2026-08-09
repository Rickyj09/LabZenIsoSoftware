import tempfile
import unittest
import zipfile
from io import BytesIO

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import (
    CLASIFICACION_CONTROL_FORMATO,
    CLASIFICACION_CONTROL_INTERNO,
    Documento,
    DocumentoAprobacion,
    DocumentoVigorCatalogo,
    DocumentoVersion,
)
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
        self.next_id = 70000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)

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
            Usuario(
                id=203,
                empresa_id=101,
                nombre="Revisor",
                apellido="Uno",
                email="revisor@versiones.test",
                username="versiones-revisor",
                password_hash="test",
                activo=True,
            ),
            Usuario(
                id=204,
                empresa_id=101,
                nombre="Aprobador",
                apellido="Uno",
                email="aprobador@versiones.test",
                username="versiones-aprobador",
                password_hash="test",
                activo=True,
            ),
            Usuario(
                id=205,
                empresa_id=101,
                nombre="Inactivo",
                apellido="Uno",
                email="inactivo@versiones.test",
                username="versiones-inactivo",
                password_hash="test",
                activo=False,
            ),
            Usuario(
                id=206,
                empresa_id=102,
                nombre="Revisor",
                apellido="Dos",
                email="revisor2@versiones.test",
                username="versiones-revisor2",
                password_hash="test",
                activo=True,
            ),
            Usuario(
                id=207,
                empresa_id=102,
                nombre="Aprobador",
                apellido="Dos",
                email="aprobador2@versiones.test",
                username="versiones-aprobador2",
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
        create_permission = Permiso(
            id=405,
            codigo="documentos.crear",
            nombre="Crear documentos",
            modulo="documentos",
        )
        view_permission = Permiso(
            id=408,
            codigo="documentos.ver",
            nombre="Ver documentos",
            modulo="documentos",
        )
        db.session.add_all([edit_role, edit_permission, create_permission, view_permission])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=403, rol_id=edit_role.id, permiso_id=edit_permission.id),
            RolPermiso(id=406, rol_id=edit_role.id, permiso_id=create_permission.id),
            RolPermiso(id=409, rol_id=edit_role.id, permiso_id=view_permission.id),
            UsuarioRol(id=404, usuario_id=201, rol_id=edit_role.id),
        ])
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
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

    def initial(self, document, version="1", user_id=201, revisado_por_id=None, aprobado_por_id=None):
        if revisado_por_id is None:
            revisado_por_id = 203 if document.empresa_id == 101 else 206
        if aprobado_por_id is None:
            aprobado_por_id = 204 if document.empresa_id == 101 else 207
        version_doc = create_initial_version(
            documento=document,
            version=version,
            cambios="Versión inicial",
            contenido="Contenido",
            user_id=user_id,
            revisado_por_id=revisado_por_id,
            aprobado_por_id=aprobado_por_id,
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

    @staticmethod
    def minimal_docx(text="Documento"):
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

    def post_new_document(self, **overrides):
        data = {
            "codigo": "TEST-GT.PR.SOD.PEECE-CIERRE",
            "titulo": "Documento de prueba cierre",
            "tipo_documento": "PROCEDIMIENTO",
            "clasificacion_control": CLASIFICACION_CONTROL_INTERNO,
            "proceso": "Gestion tecnica",
            "version": "1",
            "contenido": "Contenido",
            "cambios": "Version inicial",
            "elaborado_por_id": "201",
            "revisado_por_id": "203",
            "aprobado_por_id": "204",
            "archivo": (self.minimal_docx(), "principal.docx"),
        }
        data.update(overrides)
        return self.login(self.app, 201).post("/documentacion/nuevo", data=data, content_type="multipart/form-data")

    def approve_initial(self, document):
        version_doc = self.initial(document)
        send_to_review(documento=document, version_doc=version_doc, user_id=201)
        version_doc.estado = "EN_APROBACION"
        document.estado = "EN_APROBACION"
        approve_version(documento=document, version_doc=version_doc, user_id=201)
        db.session.flush()
        return version_doc

    def test_new_document_and_initial_version_have_no_current_approved_version(self):
        document = self.make_document(301)
        version_doc = self.initial(document)

        self.assertEqual(document.estado, "EN_ELABORACION")
        self.assertEqual(version_doc.estado, "EN_ELABORACION")
        self.assertIsNone(document.version_vigente_id)
        self.assertEqual(version_doc.elaborado_por_id, 201)
        self.assertEqual(version_doc.revisado_por_id, 203)
        self.assertEqual(version_doc.aprobado_por_id, 204)

    def test_post_new_document_stores_selected_responsibles_on_initial_version(self):
        response = self.post_new_document()

        self.assertEqual(response.status_code, 302)
        document = Documento.query.filter_by(codigo="TEST-GT.PR.SOD.PEECE-CIERRE").one()
        version_doc = DocumentoVersion.query.filter_by(documento_id=document.id, version="1").one()
        self.assertEqual(document.elaborado_por_id, 201)
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_INTERNO)
        self.assertEqual(version_doc.elaborado_por_id, 201)
        self.assertEqual(version_doc.revisado_por_id, 203)
        self.assertEqual(version_doc.aprobado_por_id, 204)

    def test_post_new_document_without_reviewer_is_rejected(self):
        response = self.post_new_document(revisado_por_id="")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Debe seleccionar un revisor.", response.get_data(as_text=True))
        self.assertEqual(Documento.query.filter_by(codigo="TEST-GT.PR.SOD.PEECE-CIERRE").count(), 0)

    def test_post_new_document_without_approver_is_rejected(self):
        response = self.post_new_document(aprobado_por_id="")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Debe seleccionar un aprobador.", response.get_data(as_text=True))
        self.assertEqual(Documento.query.filter_by(codigo="TEST-GT.PR.SOD.PEECE-CIERRE").count(), 0)

    def test_post_new_document_stores_format_control_classification(self):
        response = self.post_new_document(
            codigo="FORM-CTRL",
            titulo="Formato controlado",
            tipo_documento="FORMATO",
            clasificacion_control=CLASIFICACION_CONTROL_FORMATO,
        )

        self.assertEqual(response.status_code, 302)
        document = Documento.query.filter_by(codigo="FORM-CTRL").one()
        self.assertEqual(document.tipo_documento, "FORMATO")
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_FORMATO)

    def test_post_new_document_rejects_empty_control_classification(self):
        response = self.post_new_document(clasificacion_control="")

        self.assertEqual(response.status_code, 200)
        self.assertIn("La clasificacion de control es obligatoria.", response.get_data(as_text=True))
        self.assertEqual(Documento.query.filter_by(codigo="TEST-GT.PR.SOD.PEECE-CIERRE").count(), 0)

    def test_post_new_document_rejects_external_control_classification(self):
        response = self.post_new_document(clasificacion_control="EXTERNO")

        self.assertEqual(response.status_code, 200)
        self.assertIn("La clasificacion de control seleccionada no es valida.", response.get_data(as_text=True))
        self.assertEqual(Documento.query.filter_by(codigo="TEST-GT.PR.SOD.PEECE-CIERRE").count(), 0)

    def test_post_new_document_rejects_unknown_control_classification(self):
        response = self.post_new_document(clasificacion_control="INVALIDO")

        self.assertEqual(response.status_code, 200)
        self.assertIn("La clasificacion de control seleccionada no es valida.", response.get_data(as_text=True))
        self.assertEqual(Documento.query.filter_by(codigo="TEST-GT.PR.SOD.PEECE-CIERRE").count(), 0)

    def test_post_new_document_rejects_unknown_document_type(self):
        response = self.post_new_document(tipo_documento="MANIPULADO")

        self.assertEqual(response.status_code, 200)
        self.assertIn("El tipo de documento seleccionado no es valido.", response.get_data(as_text=True))
        self.assertEqual(Documento.query.filter_by(codigo="TEST-GT.PR.SOD.PEECE-CIERRE").count(), 0)

    def test_initial_version_rejects_cross_tenant_reviewer(self):
        document = self.make_document(314)

        with self.assertRaises(DocumentVersioningError):
            self.initial(document, revisado_por_id=202)

    def test_initial_version_rejects_cross_tenant_approver(self):
        document = self.make_document(315)

        with self.assertRaises(DocumentVersioningError):
            self.initial(document, aprobado_por_id=202)

    def test_initial_version_rejects_inactive_responsible(self):
        document = self.make_document(316)

        with self.assertRaises(DocumentVersioningError):
            self.initial(document, revisado_por_id=205)

    def test_initial_version_rejects_same_author_and_reviewer(self):
        document = self.make_document(317)

        with self.assertRaisesRegex(DocumentVersioningError, "El elaborador y el revisor deben ser diferentes."):
            self.initial(document, revisado_por_id=201)

    def test_initial_version_rejects_same_reviewer_and_approver(self):
        document = self.make_document(318)

        with self.assertRaisesRegex(DocumentVersioningError, "El revisor y el aprobador deben ser diferentes."):
            self.initial(document, revisado_por_id=203, aprobado_por_id=203)

    def test_new_draft_does_not_replace_current_approved_version(self):
        document = self.make_document(302)
        current = self.approve_initial(document)

        draft = create_draft_version(
            documento=document,
            version="2",
            cambios="Nueva revisión",
            contenido="En elaboración",
            user_id=201,
            revisado_por_id=203,
            aprobado_por_id=204,
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
            revisado_por_id=203,
            aprobado_por_id=204,
        )
        self.assign_version_id(draft)
        db.session.flush()
        send_to_review(documento=document, version_doc=draft, user_id=201)
        draft.estado = "EN_APROBACION"
        document.estado = "EN_APROBACION"

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
                revisado_por_id=203,
                aprobado_por_id=204,
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
            revisado_por_id=203,
            aprobado_por_id=204,
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
                revisado_por_id=203,
                aprobado_por_id=204,
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

    def test_draft_version_preserves_document_control_classification(self):
        document = self.make_document(320)
        document.clasificacion_control = CLASIFICACION_CONTROL_INTERNO
        self.approve_initial(document)
        db.session.commit()

        draft = create_draft_version(
            documento=document,
            version="2",
            cambios="Nueva version",
            contenido="Contenido",
            user_id=201,
            revisado_por_id=203,
            aprobado_por_id=204,
        )
        self.assign_version_id(draft)
        db.session.flush()

        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_INTERNO)
        self.assertEqual(draft.documento.clasificacion_control, CLASIFICACION_CONTROL_INTERNO)

    def test_historical_document_can_receive_initial_control_classification(self):
        document = self.make_document(321, estado="APROBADO")
        version = self.initial(document)
        version.estado = "APROBADO"
        db.session.commit()

        response = self.login(self.app, 201).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={"clasificacion_control": CLASIFICACION_CONTROL_INTERNO},
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_INTERNO)
        self.assertEqual(document.estado, "APROBADO")
        self.assertEqual(DocumentoVersion.query.filter_by(documento_id=document.id).count(), 1)
        event = DocumentoAprobacion.query.filter_by(documento_id=document.id, accion="CLASIFICAR_CONTROL").one()
        self.assertEqual(event.documento_version_id, version.id)

    def test_historical_classification_does_not_publish_or_sync_catalog(self):
        document = self.make_document(322, estado="APROBADO")
        self.initial(document).estado = "APROBADO"
        db.session.commit()

        self.login(self.app, 201).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={"clasificacion_control": CLASIFICACION_CONTROL_FORMATO},
        )

        self.assertEqual(document.estado, "APROBADO")
        self.assertIsNone(document.version_vigente_id)

    def test_user_without_edit_permission_cannot_classify(self):
        document = self.make_document(323, estado="APROBADO")
        self.initial(document).estado = "APROBADO"
        db.session.commit()

        response = self.login(self.app, 203).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={"clasificacion_control": CLASIFICACION_CONTROL_INTERNO},
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(document.clasificacion_control)

    def test_user_from_other_company_cannot_classify_document(self):
        document = self.make_document(324, estado="APROBADO")
        self.initial(document).estado = "APROBADO"
        db.session.add(UsuarioRol(id=407, usuario_id=202, rol_id=401))
        db.session.commit()

        response = self.login(self.app, 202).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={"clasificacion_control": CLASIFICACION_CONTROL_INTERNO},
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 404)
        self.assertIsNone(document.clasificacion_control)

    def test_vigente_document_with_classification_cannot_change_it(self):
        document = self.make_document(325, estado="VIGENTE")
        document.clasificacion_control = CLASIFICACION_CONTROL_INTERNO
        self.initial(document).estado = "VIGENTE"
        db.session.commit()

        response = self.login(self.app, 201).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={"clasificacion_control": CLASIFICACION_CONTROL_FORMATO},
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_INTERNO)

    def test_unpublished_draft_document_can_change_control_classification(self):
        document = self.make_document(326, estado="EN_ELABORACION")
        document.clasificacion_control = CLASIFICACION_CONTROL_INTERNO
        self.initial(document)
        db.session.commit()

        response = self.login(self.app, 201).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={"clasificacion_control": CLASIFICACION_CONTROL_FORMATO},
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_FORMATO)

    def test_detail_shows_pending_control_classification(self):
        document = self.make_document(327, estado="APROBADO")
        self.initial(document).estado = "APROBADO"
        db.session.commit()

        response = self.login(self.app, 201).get(f"/documentacion/{document.id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pendiente de clasificar", response.get_data(as_text=True))

    def test_control_classification_pending_view_lists_only_unclassified_company_documents(self):
        pending = self.make_document(328)
        self.initial(pending, version="7")
        internal = self.make_document(329)
        internal.clasificacion_control = CLASIFICACION_CONTROL_INTERNO
        form = self.make_document(330)
        form.clasificacion_control = CLASIFICACION_CONTROL_FORMATO
        other_company = self.make_document(331, empresa_id=102)
        self.initial(other_company, user_id=202)
        db.session.commit()

        response = self.login(self.app, 201).get("/documentacion/clasificacion/pendientes")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("DOC-328", html)
        self.assertIn("Ultima 7", html)
        self.assertIn("Pendiente", html)
        self.assertNotIn("DOC-329", html)
        self.assertNotIn("DOC-330", html)
        self.assertNotIn("DOC-331", html)

    def test_control_classification_pending_view_requires_edit_permission(self):
        response = self.login(self.app, 203).get("/documentacion/clasificacion/pendientes")

        self.assertEqual(response.status_code, 403)

    def test_classifying_internal_from_pending_view_removes_document_without_workflow_changes(self):
        document = self.make_document(332, estado="APROBADO")
        version = self.initial(document)
        version.estado = "APROBADO"
        db.session.commit()
        version_count = DocumentoVersion.query.filter_by(documento_id=document.id).count()
        original_state = document.estado

        response = self.login(self.app, 201).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={
                "clasificacion_control": CLASIFICACION_CONTROL_INTERNO,
                "return_to": "clasificacion_pendientes",
            },
            follow_redirects=True,
        )
        db.session.refresh(document)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_INTERNO)
        self.assertEqual(document.estado, original_state)
        self.assertEqual(DocumentoVersion.query.filter_by(documento_id=document.id).count(), version_count)
        self.assertNotIn("DOC-332", html)
        event = DocumentoAprobacion.query.filter_by(documento_id=document.id, accion="CLASIFICAR_CONTROL").one()
        self.assertEqual(event.documento_version_id, version.id)
        self.assertEqual(
            DocumentoVigorCatalogo.query.filter(
                db.or_(
                    DocumentoVigorCatalogo.documento_id == document.id,
                    DocumentoVigorCatalogo.documento_version_id == version.id,
                )
            ).count(),
            0,
        )

    def test_classifying_format_from_pending_view_is_allowed(self):
        document = self.make_document(333)
        self.initial(document)
        db.session.commit()

        response = self.login(self.app, 201).post(
            f"/documentacion/{document.id}/clasificacion-control",
            data={
                "clasificacion_control": CLASIFICACION_CONTROL_FORMATO,
                "return_to": "clasificacion_pendientes",
            },
        )
        db.session.refresh(document)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/documentacion/clasificacion/pendientes", response.location)
        self.assertEqual(document.clasificacion_control, CLASIFICACION_CONTROL_FORMATO)

    def test_pending_classification_rejects_external_invalid_and_empty_values(self):
        invalid_values = ["", "EXTERNO", "INVALIDO"]

        for index, value in enumerate(invalid_values, start=334):
            with self.subTest(value=value):
                document = self.make_document(index)
                self.initial(document)
                db.session.commit()

                response = self.login(self.app, 201).post(
                    f"/documentacion/{document.id}/clasificacion-control",
                    data={
                        "clasificacion_control": value,
                        "return_to": "clasificacion_pendientes",
                    },
                )
                db.session.refresh(document)

                self.assertEqual(response.status_code, 302)
                self.assertIn("/documentacion/clasificacion/pendientes", response.location)
                self.assertIsNone(document.clasificacion_control)
                self.assertEqual(
                    DocumentoAprobacion.query.filter_by(
                        documento_id=document.id,
                        accion="CLASIFICAR_CONTROL",
                    ).count(),
                    0,
                )

    def test_approval_rejects_version_from_another_company(self):
        document_one = self.make_document(311, empresa_id=101)
        document_two = self.make_document(312, empresa_id=102)
        other_version = self.initial(document_two, user_id=202)
        other_version.estado = "EN_APROBACION"
        db.session.flush()

        with self.assertRaises(DocumentVersioningError):
            approve_version(
                documento=document_one,
                version_doc=other_version,
                user_id=201,
            )


if __name__ == "__main__":
    unittest.main()
