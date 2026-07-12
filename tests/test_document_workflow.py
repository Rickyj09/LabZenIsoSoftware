import tempfile
import unittest

from app import create_app
from app.extensions import db
from app.models.documentos import Documento, DocumentoAprobacion
from app.models.empresa import Empresa
from app.models.seguridad import Usuario
from app.services.document_versioning_service import create_draft_version, create_initial_version
from app.services.document_workflow_service import (
    DocumentWorkflowError,
    approve_version,
    obsolete_document,
    reject_version,
    return_to_draft,
    send_for_review,
)


class DocumentWorkflowTest(unittest.TestCase):
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
        self.next_event_id = 5001

        self.company = Empresa(id=101, nombre="Empresa uno")
        self.other_company = Empresa(id=102, nombre="Empresa dos")
        self.user = Usuario(
            id=201,
            empresa_id=101,
            nombre="Usuario",
            apellido="Uno",
            email="uno@workflow.test",
            username="workflow-uno",
            password_hash="test",
            activo=True,
        )
        self.other_user = Usuario(
            id=202,
            empresa_id=102,
            nombre="Usuario",
            apellido="Dos",
            email="dos@workflow.test",
            username="workflow-dos",
            password_hash="test",
            activo=True,
        )
        db.session.add_all([self.company, self.other_company, self.user, self.other_user])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def make_document(self, document_id=301, empresa_id=101):
        document = Documento(
            id=document_id,
            empresa_id=empresa_id,
            codigo=f"DOC-{document_id}",
            titulo=f"Documento {document_id}",
            tipo_documento="PROCEDIMIENTO",
            estado="EN_ELABORACION",
            version_actual="1",
            elaborado_por_id=201 if empresa_id == 101 else 202,
        )
        db.session.add(document)
        db.session.flush()
        return document

    def assign_version_id(self, version_doc):
        version_doc.id = self.next_version_id
        self.next_version_id += 1
        db.session.flush()
        return version_doc

    def assign_event_ids(self):
        for item in list(db.session.new):
            if isinstance(item, DocumentoAprobacion) and item.id is None:
                item.id = self.next_event_id
                self.next_event_id += 1
        db.session.flush()

    def initial(self, document, version="1", user_id=201):
        return self.assign_version_id(create_initial_version(
            documento=document,
            version=version,
            cambios="Versión inicial",
            contenido="Contenido",
            user_id=user_id,
        ))

    def send(self, document, version_doc, user=None, comment="Lista para revisión"):
        event = send_for_review(
            documento=document,
            version_doc=version_doc,
            usuario=user or self.user,
            comentario=comment,
            ip="127.0.0.1",
            user_agent="workflow-test",
        )
        self.assign_event_ids()
        return event

    def approve(self, document, version_doc, user=None, comment="Conforme"):
        event = approve_version(
            documento=document,
            version_doc=version_doc,
            usuario=user or self.user,
            comentario=comment,
            ip="127.0.0.1",
            user_agent="workflow-test",
        )
        self.assign_event_ids()
        return event

    def approved_initial(self, document):
        version_doc = self.initial(document)
        self.send(document, version_doc)
        self.approve(document, version_doc)
        return version_doc

    def draft(self, document, version="2"):
        return self.assign_version_id(create_draft_version(
            documento=document,
            version=version,
            cambios="Cambio controlado",
            contenido="Contenido nuevo",
            user_id=self.user.id,
        ))

    def test_send_to_review_records_metadata_and_keeps_current_version(self):
        document = self.make_document()
        current = self.approved_initial(document)
        draft = self.draft(document)

        event = self.send(document, draft)

        self.assertEqual(draft.estado, "EN_REVISION")
        self.assertEqual(document.estado, "EN_REVISION")
        self.assertEqual(document.version_vigente_id, current.id)
        self.assertIsNotNone(draft.fecha_envio_revision)
        self.assertEqual(event.accion, "ENVIAR_REVISION")
        self.assertEqual((event.estado_anterior, event.estado_nuevo), ("EN_ELABORACION", "EN_REVISION"))
        self.assertEqual((event.ip, event.user_agent), ("127.0.0.1", "workflow-test"))

    def test_approval_substitutes_previous_and_records_both_events(self):
        document = self.make_document()
        previous = self.approved_initial(document)
        draft = self.draft(document, "2.0")
        self.send(document, draft)

        self.approve(document, draft)

        self.assertEqual(previous.estado, "SUSTITUIDO")
        self.assertEqual(draft.estado, "APROBADO")
        self.assertEqual(document.estado, "APROBADO")
        self.assertEqual(document.version_vigente_id, draft.id)
        self.assertEqual(document.version_actual, "2.0")
        actions = [event.accion for event in DocumentoAprobacion.query.filter_by(documento_id=document.id).all()]
        self.assertIn("APROBAR", actions)
        self.assertIn("SUSTITUIR_VERSION", actions)

    def test_rejection_requires_comment_and_preserves_approved_current(self):
        document = self.make_document()
        current = self.approved_initial(document)
        draft = self.draft(document)
        self.send(document, draft)

        with self.assertRaises(DocumentWorkflowError):
            reject_version(documento=document, version_doc=draft, usuario=self.user, comentario="  ")

        event = reject_version(
            documento=document,
            version_doc=draft,
            usuario=self.user,
            comentario="Falta evidencia",
        )
        self.assign_event_ids()

        self.assertEqual(draft.estado, "RECHAZADO")
        self.assertEqual(draft.comentario_rechazo, "Falta evidencia")
        self.assertEqual(document.estado, "APROBADO")
        self.assertEqual(document.version_vigente_id, current.id)
        self.assertEqual(event.accion, "RECHAZAR")

    def test_rejection_without_current_marks_document_rejected(self):
        document = self.make_document()
        draft = self.initial(document)
        self.send(document, draft)

        reject_version(
            documento=document,
            version_doc=draft,
            usuario=self.user,
            comentario="Debe corregirse",
        )
        self.assign_event_ids()

        self.assertEqual(document.estado, "RECHAZADO")
        self.assertIsNone(document.version_vigente_id)

    def test_rejected_version_returns_to_draft_with_auditable_event(self):
        document = self.make_document()
        draft = self.initial(document)
        self.send(document, draft)
        reject_version(
            documento=document,
            version_doc=draft,
            usuario=self.user,
            comentario="Corregir alcance",
        )
        self.assign_event_ids()

        event = return_to_draft(
            documento=document,
            version_doc=draft,
            usuario=self.user,
            comentario="Se corregirá el alcance",
        )
        self.assign_event_ids()

        self.assertEqual((draft.estado, document.estado), ("EN_ELABORACION", "EN_ELABORACION"))
        self.assertEqual(event.accion, "DEVOLVER_BORRADOR")
        self.assertEqual((event.estado_anterior, event.estado_nuevo), ("RECHAZADO", "EN_ELABORACION"))
        self.assertEqual(draft.comentario_rechazo, "Corregir alcance")

    def test_obsolescence_requires_reason_and_only_accepts_approved_document(self):
        draft_document = self.make_document(302)
        self.initial(draft_document)
        with self.assertRaises(DocumentWorkflowError):
            obsolete_document(
                documento=draft_document,
                usuario=self.user,
                motivo="Retiro controlado",
            )

        approved_document = self.make_document(303)
        current = self.approved_initial(approved_document)
        with self.assertRaises(DocumentWorkflowError):
            obsolete_document(documento=approved_document, usuario=self.user, motivo="")

        event = obsolete_document(
            documento=approved_document,
            usuario=self.user,
            motivo="Proceso reemplazado",
        )
        self.assign_event_ids()

        self.assertEqual((approved_document.estado, current.estado), ("OBSOLETO", "OBSOLETO"))
        self.assertIsNone(approved_document.version_vigente_id)
        self.assertEqual(current.motivo_obsolescencia, "Proceso reemplazado")
        self.assertEqual(event.accion, "OBSOLETAR")

    def test_invalid_transitions_are_rejected(self):
        document = self.make_document()
        draft = self.initial(document)

        with self.assertRaises(DocumentWorkflowError):
            approve_version(documento=document, version_doc=draft, usuario=self.user)
        with self.assertRaises(DocumentWorkflowError):
            reject_version(
                documento=document,
                version_doc=draft,
                usuario=self.user,
                comentario="No corresponde",
            )
        with self.assertRaises(DocumentWorkflowError):
            return_to_draft(
                documento=document,
                version_doc=draft,
                usuario=self.user,
                comentario="No corresponde",
            )

    def test_cross_tenant_transition_is_rejected(self):
        document = self.make_document()
        draft = self.initial(document)

        with self.assertRaises(DocumentWorkflowError):
            send_for_review(
                documento=document,
                version_doc=draft,
                usuario=self.other_user,
            )


if __name__ == "__main__":
    unittest.main()
