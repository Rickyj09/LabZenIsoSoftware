import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from flask import g
from sqlalchemy import event
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.empresa import Empresa
from app.models.organigrama import (
    Cargo,
    Personal,
    PersonalCapacitacion,
    PersonalCalificacion,
    PersonalEvaluacionCompetencia,
    PersonalEvaluacionCompetenciaEvidencia,
    PersonalExperiencia,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.personal_service import (
    PersonalError,
    add_capacitacion_participante,
    add_evaluacion_competencia_evidencia,
    create_calificacion,
    create_capacitacion,
    create_cargo,
    create_evaluacion_competencia,
    create_experiencia,
    create_personal,
    update_evaluacion_competencia,
)
from app.services.storage_service import resolve_document_path


PERSONAL_PERMISSIONS = ("personal.ver", "personal.gestionar")


class Personal4DTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DOCUMENT_STORAGE_ROOT": self.temp_directory.name,
            "DOCUMENT_LEGACY_STORAGE_ROOT": self.temp_directory.name,
            "DOCUMENT_MAX_FILE_SIZE": 1024 * 1024,
            "ONLYOFFICE_ENABLED": False,
            "ONLYOFFICE_EDIT_ENABLED": False,
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
        self._seed_security()
        self.person = self._create_person(user_id=201, cargo_code="DT", person_code="PER-001")
        self.evaluator = self._create_person(user_id=201, cargo_code="EV", person_code="PER-EVAL")
        self.other_person = self._create_person(user_id=204, cargo_code="OT", person_code="PER-OTRA")
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
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@per4d", username="admin-per4d", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@per4d", username="consulta-per4d", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin@per4d", username="sin-per4d", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@per4d", username="admin2-per4d", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, code in enumerate(PERSONAL_PERMISSIONS, start=1):
            permission = Permiso(id=1000 + offset, codigo=code, nombre=code, modulo="personal")
            db.session.add(permission)
            permissions[code] = permission
        manager = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        viewer = Rol(id=2002, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([manager, viewer])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=manager.id, permiso_id=permissions["personal.ver"].id),
            RolPermiso(id=3002, rol_id=manager.id, permiso_id=permissions["personal.gestionar"].id),
            RolPermiso(id=3003, rol_id=viewer.id, permiso_id=permissions["personal.ver"].id),
            UsuarioRol(id=4001, usuario_id=201, rol_id=manager.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=viewer.id),
            UsuarioRol(id=4003, usuario_id=204, rol_id=manager.id),
        ])

    def _create_person(self, user_id, cargo_code, person_code):
        user = self.user(user_id)
        cargo = create_cargo(user, {"codigo": cargo_code, "nombre": f"Cargo {cargo_code}", "activo": "1"})
        db.session.flush()
        return create_personal(user, {
            "codigo": person_code,
            "nombres": "Ana",
            "apellidos": cargo_code,
            "identificacion": f"ID-{person_code}",
            "cargo_id": str(cargo.id),
            "estado": "ACTIVO",
        })

    def login(self, user_id=201):
        g.pop("_login_user", None)
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def csrf_token(self, client):
        with client.session_transaction() as session:
            return session["personal_csrf"]

    def user(self, user_id=201):
        return db.session.get(Usuario, user_id)

    def evaluacion_data(self, **overrides):
        data = {
            "codigo": "EVC-001",
            "personal_id": str(self.person.id),
            "evaluador_personal_id": str(self.evaluator.id),
            "evaluador_usuario_id": "",
            "actividad": "operacion de espectrofotometro",
            "descripcion": "Demostracion en rutina de laboratorio",
            "tipo_competencia": "EQUIPO",
            "metodo_evaluacion": "DEMOSTRACION_PRACTICA",
            "criterio_evaluacion": "Cumplimiento del procedimiento y registros completos",
            "criterios": "preparacion correcta del equipo\nregistro correcto de datos",
            "descripcion_metodo": "Observacion durante una corrida analitica",
            "fecha_evaluacion": "2026-08-20",
            "resultado": "COMPETENTE",
            "conclusion": "Demostro competencia para la actividad evaluada.",
            "observaciones": "Sin hallazgos criticos",
            "evaluador_externo_nombre": "",
            "evaluador_externo_entidad": "",
            "capacitacion_id": "",
            "capacitacion_participante_id": "",
            "activo": "1",
        }
        data.update(overrides)
        return data

    def capacitacion_data(self):
        return {
            "codigo": "CAP-4D",
            "nombre": "Entrenamiento instrumental",
            "tipo": "ENTRENAMIENTO",
            "modalidad": "PRESENCIAL",
            "fecha_inicio": "2026-08-01",
            "estado": "COMPLETADA",
        }

    def calificacion_data(self):
        return {
            "tipo": "CERTIFICACION",
            "institucion": "Entidad externa",
            "titulo": "Certificado ISO",
            "fecha_inicio": "2025-01-01",
            "fecha_fin": "2025-01-02",
            "activo": "1",
        }

    def experiencia_data(self):
        return {
            "organizacion": "Laboratorio Alfa",
            "cargo_funcion": "Analista",
            "fecha_inicio": "2023-01-01",
            "experiencia_actual": "1",
            "activo": "1",
        }

    @staticmethod
    def evidence_file(name="evaluacion.pdf", content=b"evidencia evaluacion"):
        return FileStorage(stream=BytesIO(content), filename=name, content_type="application/pdf")

    def test_creates_edits_lists_and_shows_evaluation_in_person_detail(self):
        evaluacion = create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data())
        db.session.commit()

        data = self.evaluacion_data(codigo="EVC-001", resultado="COMPETENTE_CON_OBSERVACIONES")
        update_evaluacion_competencia(self.user(), evaluacion, data)
        db.session.commit()

        self.assertEqual(evaluacion.empresa_id, 101)
        self.assertEqual(evaluacion.personal_id, self.person.id)
        self.assertEqual(evaluacion.evaluador_personal_id, self.evaluator.id)
        self.assertEqual(evaluacion.resultado, "COMPETENTE_CON_OBSERVACIONES")

        client = self.login()
        index = client.get("/personal/evaluaciones?q=espectrofotometro")
        detail = client.get(f"/personal/{self.person.id}")
        evaluation_detail = client.get(f"/personal/evaluaciones/{evaluacion.id}")

        self.assertEqual(index.status_code, 200)
        self.assertIn("operacion de espectrofotometro", index.get_data(as_text=True))
        self.assertIn("Evaluaciones de competencia", detail.get_data(as_text=True))
        self.assertIn("COMPETENTE_CON_OBSERVACIONES", detail.get_data(as_text=True))
        self.assertIn("Metodo", evaluation_detail.get_data(as_text=True))
        self.assertIn("Evidencias", evaluation_detail.get_data(as_text=True))

    def test_required_fields_and_valid_catalog_values(self):
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(self.user(), "", self.evaluacion_data())
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data(actividad=""))
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data(metodo_evaluacion="INVALIDO"))
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data(resultado="AUTORIZADO"))
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data(fecha_evaluacion=""))

    def test_evaluator_and_evaluation_cross_tenant_rejections(self):
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(
                self.user(),
                self.person.id,
                self.evaluacion_data(evaluador_personal_id=str(self.other_person.id)),
            )
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(self.user(), self.other_person.id, self.evaluacion_data())

        other_eval = create_evaluacion_competencia(
            self.user(204),
            self.other_person.id,
            self.evaluacion_data(
                codigo="EVC-OTRA",
                personal_id=str(self.other_person.id),
                evaluador_personal_id="",
                evaluador_externo_nombre="Evaluador externo",
            ),
        )
        db.session.commit()
        with self.assertRaises(PersonalError):
            update_evaluacion_competencia(self.user(), other_eval, self.evaluacion_data())
        self.assertEqual(self.login(201).get(f"/personal/evaluaciones/{other_eval.id}").status_code, 404)

    def test_allows_external_evaluator_and_optional_training_relation(self):
        capacitacion = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.flush()
        participante = add_capacitacion_participante(self.user(), capacitacion, self.person.id, {})
        db.session.flush()

        evaluacion = create_evaluacion_competencia(
            self.user(),
            self.person.id,
            self.evaluacion_data(
                evaluador_personal_id="",
                evaluador_externo_nombre="Inspector externo",
                evaluador_externo_entidad="Proveedor tecnico",
                capacitacion_participante_id=str(participante.id),
            ),
        )
        db.session.commit()

        self.assertEqual(evaluacion.evaluador_nombre, "Inspector externo")
        self.assertEqual(evaluacion.capacitacion_id, capacitacion.id)
        self.assertEqual(evaluacion.capacitacion_participante_id, participante.id)

    def test_evidence_upload_download_and_cross_tenant_isolation(self):
        evaluacion = create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data())
        db.session.flush()
        evidencia = add_evaluacion_competencia_evidencia(
            self.user(),
            evaluacion,
            self.evidence_file("../checklist.pdf"),
            {"tipo_evidencia": "CHECKLIST", "observaciones": "Formato firmado"},
        )
        db.session.commit()

        self.assertEqual(evidencia.empresa_id, 101)
        self.assertTrue(evidencia.archivo_storage_path.startswith(
            f"empresa_101/personal_{self.person.id}/evaluacion_competencia_{evaluacion.id}/evidencias/"
        ))
        self.assertTrue(resolve_document_path(evidencia.archivo_storage_path).is_file())
        self.assertNotIn("..", evidencia.archivo_nombre_guardado)

        response = self.login(201).get(f"/personal/evaluaciones/evidencias/{evidencia.id}/descargar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"evidencia evaluacion")
        response.close()
        self.assertEqual(self.login(204).get(f"/personal/evaluaciones/evidencias/{evidencia.id}/descargar").status_code, 404)

    def test_http_permissions_manage_permission_and_csrf(self):
        viewer = self.login(202)
        self.assertEqual(viewer.get("/personal/evaluaciones").status_code, 200)
        self.assertEqual(viewer.get(f"/personal/{self.person.id}/evaluaciones/nueva").status_code, 403)

        no_permission = self.login(203)
        self.assertEqual(no_permission.get("/personal/evaluaciones").status_code, 403)

        manager = self.login(201)
        form = manager.get(f"/personal/{self.person.id}/evaluaciones/nueva")
        self.assertEqual(form.status_code, 200)
        self.assertEqual(manager.post(f"/personal/{self.person.id}/evaluaciones/nueva", data=self.evaluacion_data()).status_code, 403)

        token = self.csrf_token(manager)
        created = manager.post(
            f"/personal/{self.person.id}/evaluaciones/nueva",
            data={**self.evaluacion_data(), "csrf_token": token},
        )
        self.assertEqual(created.status_code, 302)
        evaluacion = PersonalEvaluacionCompetencia.query.filter_by(codigo="EVC-001", empresa_id=101).one()

        manager.get(f"/personal/evaluaciones/{evaluacion.id}")
        self.assertEqual(manager.post(
            f"/personal/evaluaciones/{evaluacion.id}/evidencias",
            data={"evidencia": (BytesIO(b"x"), "evaluacion.pdf"), "tipo_evidencia": "CHECKLIST"},
            content_type="multipart/form-data",
        ).status_code, 403)

        token = self.csrf_token(manager)
        uploaded = manager.post(
            f"/personal/evaluaciones/{evaluacion.id}/evidencias",
            data={"csrf_token": token, "evidencia": (BytesIO(b"x"), "evaluacion.pdf"), "tipo_evidencia": "CHECKLIST"},
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 302)
        self.assertEqual(PersonalEvaluacionCompetenciaEvidencia.query.filter_by(evaluacion_id=evaluacion.id).count(), 1)
        self.assertEqual(len(list(Path(self.temp_directory.name).rglob("*.pdf"))), 1)

    def test_multiple_historical_evaluations_and_competent_does_not_authorize(self):
        first = create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data(codigo="EVC-001"))
        second = create_evaluacion_competencia(
            self.user(),
            self.person.id,
            self.evaluacion_data(codigo="EVC-002", fecha_evaluacion="2027-01-20", resultado="REQUIERE_ENTRENAMIENTO"),
        )
        third = create_evaluacion_competencia(
            self.user(),
            self.person.id,
            self.evaluacion_data(codigo="EVC-003", fecha_evaluacion="2027-03-20", resultado="COMPETENTE"),
        )
        db.session.commit()

        self.assertEqual(PersonalEvaluacionCompetencia.query.filter_by(personal_id=self.person.id).count(), 3)
        self.assertEqual([item.id for item in self.person.evaluaciones_competencia], [third.id, second.id, first.id])
        self.assertFalse(hasattr(db.session.get(Personal, self.person.id), "estado_competencia"))
        self.assertFalse(hasattr(db.session.get(Personal, self.person.id), "competente"))
        self.assertNotIn("autorizacion", PersonalEvaluacionCompetencia.__tablename__)

    def test_basic_4a_4b_4c_regressions_remain_person_scoped(self):
        calificacion = create_calificacion(self.user(), self.person.id, self.calificacion_data())
        experiencia = create_experiencia(self.user(), self.person.id, self.experiencia_data())
        capacitacion = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.flush()
        participante = add_capacitacion_participante(self.user(), capacitacion, self.person.id, {})
        evaluacion = create_evaluacion_competencia(self.user(), self.person.id, self.evaluacion_data())
        db.session.commit()

        person = db.session.get(Personal, self.person.id)
        self.assertIsInstance(db.session.get(Cargo, person.cargo_id), Cargo)
        self.assertEqual(person.calificaciones[0].id, calificacion.id)
        self.assertEqual(person.experiencias[0].id, experiencia.id)
        self.assertEqual(person.capacitaciones_participacion[0].id, participante.id)
        self.assertEqual(person.evaluaciones_competencia[0].id, evaluacion.id)
        self.assertEqual(PersonalCalificacion.query.filter_by(empresa_id=102).count(), 0)
        self.assertEqual(PersonalExperiencia.query.filter_by(empresa_id=102).count(), 0)
        self.assertEqual(PersonalCapacitacion.query.filter_by(empresa_id=102).count(), 0)


if __name__ == "__main__":
    unittest.main()
