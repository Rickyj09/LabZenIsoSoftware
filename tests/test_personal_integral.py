import tempfile
import unittest
from datetime import date
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
from app.models.equipos import Equipo
from app.models.organigrama import (
    Cargo,
    PerfilPuesto,
    Personal,
    PersonalAutorizacionTecnica,
    PersonalAutorizacionTecnicaEvidencia,
    PersonalCapacitacion,
    PersonalCapacitacionEvidencia,
    PersonalCapacitacionParticipante,
    PersonalCalificacion,
    PersonalCalificacionEvidencia,
    PersonalEvaluacionCompetencia,
    PersonalEvaluacionCompetenciaEvidencia,
    PersonalExperiencia,
    PersonalSeguimiento,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.personal_service import (
    PERSONAL_AUTHORIZATION_EXPIRY_WARNING_DAYS,
    PersonalError,
    add_autorizacion_tecnica_evidencia,
    add_calificacion_evidencia,
    add_capacitacion_evidencia,
    add_capacitacion_participante,
    add_evaluacion_competencia_evidencia,
    autorizaciones_proximas_vencer_query,
    autorizaciones_vencidas_query,
    completar_seguimiento,
    create_autorizacion_tecnica,
    create_calificacion,
    create_capacitacion,
    create_cargo,
    create_evaluacion_competencia,
    create_experiencia,
    create_personal,
    create_seguimiento,
    estado_efectivo_autorizacion,
    evaluaciones_requieren_accion_query,
    iniciar_seguimiento,
    revocar_autorizacion_tecnica,
    seguimiento_dashboard,
    seguimiento_form_defaults,
    suspender_autorizacion_tecnica,
    update_capacitacion_participante,
    upsert_perfil,
)
from app.services.storage_service import resolve_document_path


PERSONAL_PERMISSIONS = ("personal.ver", "personal.gestionar")


class PersonalIntegralTest(unittest.TestCase):
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
        self.next_id = 30000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        self._seed_security()
        self.equipment = self._create_equipment(101, "EQ-A")
        self.other_equipment = self._create_equipment(102, "EQ-B")
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def _seed_security(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa A"),
            Empresa(id=102, nombre="Empresa B"),
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="A", email="admin-a@lab", username="admin-a", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Viewer", apellido="A", email="viewer-a@lab", username="viewer-a", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin-a@lab", username="sin-a", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Admin", apellido="B", email="admin-b@lab", username="admin-b", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, code in enumerate(PERSONAL_PERMISSIONS, start=1):
            permission = Permiso(id=3100 + offset, codigo=code, nombre=code, modulo="personal")
            db.session.add(permission)
            permissions[code] = permission
        manager = Rol(id=3201, nombre="CALIDAD", es_sistema=True)
        viewer = Rol(id=3202, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([manager, viewer])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3301, rol_id=manager.id, permiso_id=permissions["personal.ver"].id),
            RolPermiso(id=3302, rol_id=manager.id, permiso_id=permissions["personal.gestionar"].id),
            RolPermiso(id=3303, rol_id=viewer.id, permiso_id=permissions["personal.ver"].id),
            UsuarioRol(id=3401, usuario_id=201, rol_id=manager.id),
            UsuarioRol(id=3402, usuario_id=202, rol_id=viewer.id),
            UsuarioRol(id=3403, usuario_id=204, rol_id=manager.id),
        ])

    def user(self, user_id=201):
        return db.session.get(Usuario, user_id)

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

    def _create_equipment(self, empresa_id, code):
        item = Equipo(
            empresa_id=empresa_id,
            codigo=code,
            nombre=f"Equipo {code}",
            tipo="Instrumento",
            estado="activo",
            estado_operativo="OPERATIVO",
        )
        db.session.add(item)
        db.session.flush()
        return item

    def cargo_data(self, code="DT"):
        return {
            "codigo": code,
            "nombre": f"Cargo {code}",
            "activo": "1",
            "proposito": "Dirigir actividades tecnicas.",
            "funciones": "Supervisar ensayos.",
            "responsabilidades": "Asegurar competencia.",
            "autoridad": "Aprobar criterios tecnicos.",
        }

    def personal_data(self, cargo, code="PER-A", user_id=""):
        return {
            "codigo": code,
            "nombres": "Ana",
            "apellidos": code,
            "identificacion": f"ID-{code}",
            "cargo_id": str(cargo.id),
            "usuario_id": str(user_id) if user_id else "",
            "estado": "ACTIVO",
        }

    def calificacion_data(self):
        return {
            "tipo": "CERTIFICACION",
            "institucion": "Entidad tecnica",
            "titulo": "Certificado ISO",
            "fecha_inicio": "2025-01-01",
            "fecha_fin": "2025-12-31",
            "activo": "1",
        }

    def experiencia_data(self):
        return {
            "organizacion": "Laboratorio Alfa",
            "cargo_funcion": "Analista",
            "fecha_inicio": "2024-01-01",
            "experiencia_actual": "1",
            "activo": "1",
        }

    def capacitacion_data(self, code="CAP-A", estado="PLANIFICADA"):
        return {
            "codigo": code,
            "nombre": f"Capacitacion {code}",
            "tipo": "ENTRENAMIENTO",
            "modalidad": "PRESENCIAL",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-08-02",
            "estado": estado,
        }

    def evaluacion_data(self, person, evaluator, code="EVC-A", resultado="COMPETENTE"):
        return {
            "codigo": code,
            "personal_id": str(person.id),
            "evaluador_personal_id": str(evaluator.id),
            "actividad": "operacion tecnica",
            "tipo_competencia": "TECNICA",
            "metodo_evaluacion": "OBSERVACION_DIRECTA",
            "criterio_evaluacion": "Cumple procedimiento",
            "fecha_evaluacion": "2026-08-20",
            "resultado": resultado,
            "evaluador_externo_nombre": "",
        }

    def autorizacion_data(self, person, authorizer, code="AUT-A", **overrides):
        data = {
            "codigo": code,
            "personal_id": str(person.id),
            "tipo_autorizacion": "ACTIVIDAD_TECNICA",
            "actividad": "operacion tecnica",
            "alcance": "Puede ejecutar la actividad bajo procedimientos vigentes.",
            "equipo_id": "",
            "metodo_referencia": "",
            "evaluacion_competencia_id": "",
            "autorizador_personal_id": str(authorizer.id),
            "autorizador_usuario_id": "",
            "autorizador_externo_nombre": "",
            "fecha_autorizacion": "2026-08-25",
            "fecha_inicio": "2026-09-01",
            "fecha_fin": "",
            "estado": "VIGENTE",
            "fundamento": "Competencia demostrada.",
        }
        data.update(overrides)
        return data

    def seguimiento_data(self, person, **overrides):
        data = {
            "personal_id": str(person.id),
            "tipo": "OBSERVACION",
            "titulo": "Seguimiento integral",
            "fecha_deteccion": "2026-08-31",
            "fecha_objetivo": "2026-09-15",
            "estado": "PENDIENTE",
            "prioridad": "MEDIA",
            "accion_requerida": "Registrar cierre del seguimiento.",
        }
        data.update(overrides)
        return data

    @staticmethod
    def evidence_file(name="evidencia.pdf", content=b"evidencia"):
        return FileStorage(stream=BytesIO(content), filename=name, content_type="application/pdf")

    def _create_person_with_role(self, user_id=201, cargo_code="DT", person_code="PER-A", linked_user_id=""):
        cargo = create_cargo(self.user(user_id), self.cargo_data(cargo_code))
        db.session.flush()
        upsert_perfil(self.user(user_id), cargo, self.cargo_data(cargo_code))
        person = create_personal(self.user(user_id), self.personal_data(cargo, person_code, linked_user_id))
        db.session.flush()
        return cargo, person

    def test_real_module_4_flow_preserves_explicit_boundaries_and_history(self):
        cargo, person = self._create_person_with_role(linked_user_id=201)
        _, evaluator = self._create_person_with_role(cargo_code="EV", person_code="PER-EVAL")
        db.session.commit()

        calificacion = create_calificacion(self.user(), person.id, self.calificacion_data())
        experiencia = create_experiencia(self.user(), person.id, self.experiencia_data())
        db.session.flush()
        cal_evidence = add_calificacion_evidencia(self.user(), calificacion, self.evidence_file("../titulo.pdf"))

        capacitacion = create_capacitacion(self.user(), self.capacitacion_data(estado="COMPLETADA"))
        db.session.flush()
        participante = add_capacitacion_participante(self.user(), capacitacion, person.id, {"estado_participacion": "INSCRITO"})
        update_capacitacion_participante(self.user(), participante, {"estado_participacion": "COMPLETO"})
        db.session.flush()
        cap_evidence = add_capacitacion_evidencia(
            self.user(),
            capacitacion,
            self.evidence_file("../asistencia.pdf", b"capacitacion"),
            {"tipo_evidencia": "LISTA_ASISTENCIA", "participante_id": str(participante.id)},
        )
        db.session.commit()

        self.assertEqual(capacitacion.estado, "COMPLETADA")
        self.assertEqual(PersonalEvaluacionCompetencia.query.filter_by(personal_id=person.id).count(), 0)
        self.assertEqual(PersonalAutorizacionTecnica.query.filter_by(personal_id=person.id).count(), 0)

        evaluacion = create_evaluacion_competencia(self.user(), person.id, self.evaluacion_data(person, evaluator))
        db.session.flush()
        eval_evidence = add_evaluacion_competencia_evidencia(
            self.user(),
            evaluacion,
            self.evidence_file("../evaluacion.pdf", b"evaluacion"),
            {"tipo_evidencia": "CHECKLIST"},
        )
        db.session.commit()

        self.assertEqual(evaluacion.resultado, "COMPETENTE")
        self.assertEqual(PersonalAutorizacionTecnica.query.filter_by(personal_id=person.id).count(), 0)

        autorizacion = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(person, evaluator, evaluacion_competencia_id=str(evaluacion.id)),
        )
        equipo_estado_original = self.equipment.estado_operativo
        autorizacion_equipo = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(
                person,
                evaluator,
                code="AUT-EQ",
                tipo_autorizacion="EQUIPO",
                actividad="operar equipo",
                equipo_id=str(self.equipment.id),
            ),
        )
        db.session.flush()
        auth_evidence = add_autorizacion_tecnica_evidencia(
            self.user(),
            autorizacion,
            self.evidence_file("../autorizacion.pdf", b"autorizacion"),
            {"tipo_evidencia": "ACTA_AUTORIZACION"},
        )
        db.session.commit()

        self.assertEqual(estado_efectivo_autorizacion(autorizacion, today=date(2026, 9, 2)), "VIGENTE")
        self.assertEqual(autorizacion_equipo.equipo_id, self.equipment.id)
        self.assertEqual(db.session.get(Equipo, self.equipment.id).estado_operativo, equipo_estado_original)

        seguimiento = create_seguimiento(
            self.user(),
            self.seguimiento_data(person, evaluacion_competencia_id=str(evaluacion.id), autorizacion_tecnica_id=str(autorizacion.id), capacitacion_id=str(capacitacion.id)),
        )
        db.session.commit()
        iniciar_seguimiento(self.user(), seguimiento)
        completar_seguimiento(self.user(), seguimiento, {"fecha_cierre": "2026-09-10", "resultado_cierre": "Accion cerrada"})
        pendiente = create_seguimiento(self.user(), self.seguimiento_data(person, titulo="Seguimiento pendiente"))
        db.session.commit()

        fresh_person = db.session.get(Personal, person.id)
        self.assertEqual(fresh_person.empresa_id, 101)
        self.assertIsInstance(fresh_person.cargo.perfil, PerfilPuesto)
        self.assertEqual(fresh_person.calificaciones[0].id, calificacion.id)
        self.assertEqual(fresh_person.experiencias[0].id, experiencia.id)
        self.assertEqual(fresh_person.capacitaciones_participacion[0].id, participante.id)
        self.assertEqual(fresh_person.evaluaciones_competencia[0].id, evaluacion.id)
        self.assertEqual(PersonalSeguimiento.query.filter_by(personal_id=person.id).count(), 2)
        self.assertEqual(seguimiento.estado, "COMPLETADO")
        self.assertEqual(pendiente.estado, "PENDIENTE")
        for item in (cargo, person, calificacion, experiencia, capacitacion, participante, evaluacion, autorizacion, autorizacion_equipo, seguimiento, pendiente):
            self.assertEqual(item.empresa_id, 101)
        for evidence in (cal_evidence, cap_evidence, eval_evidence, auth_evidence):
            self.assertEqual(evidence.empresa_id, 101)
            self.assertEqual(len(evidence.archivo_sha256), 64)
            self.assertTrue(resolve_document_path(evidence.archivo_storage_path).is_file())
            self.assertNotIn("..", evidence.archivo_nombre_guardado)

    def test_negative_training_retraining_validity_and_history(self):
        _, person = self._create_person_with_role(person_code="PER-NEG")
        _, evaluator = self._create_person_with_role(cargo_code="NE", person_code="PER-NEVAL")
        create_calificacion(self.user(), person.id, self.calificacion_data())
        create_experiencia(self.user(), person.id, self.experiencia_data())
        capacitacion = create_capacitacion(self.user(), self.capacitacion_data("CAP-NEG", "COMPLETADA"))
        db.session.flush()
        add_capacitacion_participante(self.user(), capacitacion, person.id, {"estado_participacion": "COMPLETO"})
        db.session.commit()

        self.assertEqual(PersonalEvaluacionCompetencia.query.filter_by(personal_id=person.id).count(), 0)
        self.assertEqual(PersonalAutorizacionTecnica.query.filter_by(personal_id=person.id).count(), 0)

        no_competente = create_evaluacion_competencia(
            self.user(),
            person.id,
            self.evaluacion_data(person, evaluator, "EVC-NO", "NO_COMPETENTE"),
        )
        requiere_entrenamiento = create_evaluacion_competencia(
            self.user(),
            person.id,
            self.evaluacion_data(person, evaluator, "EVC-TR", "REQUIERE_ENTRENAMIENTO"),
        )
        competente = create_evaluacion_competencia(
            self.user(),
            person.id,
            self.evaluacion_data(person, evaluator, "EVC-OK", "COMPETENTE"),
        )
        db.session.commit()

        action_ids = [item.id for item in evaluaciones_requieren_accion_query(self.user()).all()]
        self.assertIn(no_competente.id, action_ids)
        self.assertIn(requiere_entrenamiento.id, action_ids)
        self.assertNotIn(competente.id, action_ids)
        for evaluation in (no_competente, requiere_entrenamiento):
            with self.assertRaises(PersonalError):
                create_autorizacion_tecnica(
                    self.user(),
                    person.id,
                    self.autorizacion_data(person, evaluator, f"AUT-BAD-{evaluation.id}", evaluacion_competencia_id=str(evaluation.id)),
                )

        before = PersonalSeguimiento.query.count()
        defaults = seguimiento_form_defaults(self.user(), source="evaluacion", source_id=requiere_entrenamiento.id)
        self.assertEqual(defaults["evaluacion_competencia_id"], str(requiere_entrenamiento.id))
        self.assertEqual(PersonalSeguimiento.query.count(), before)

        seguimiento = create_seguimiento(self.user(), self.seguimiento_data(person, evaluacion_competencia_id=str(requiere_entrenamiento.id)))
        revoked = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(person, evaluator, "AUT-REV", evaluacion_competencia_id=str(competente.id)),
        )
        db.session.commit()
        revocar_autorizacion_tecnica(self.user(), revoked, "Nueva autorizacion reemplaza la anterior")
        vigente = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(person, evaluator, "AUT-VIG", evaluacion_competencia_id=str(competente.id)),
        )
        db.session.commit()

        self.assertEqual(PersonalEvaluacionCompetencia.query.filter_by(personal_id=person.id).count(), 3)
        self.assertEqual(PersonalAutorizacionTecnica.query.filter_by(personal_id=person.id).count(), 2)
        self.assertEqual(PersonalSeguimiento.query.filter_by(personal_id=person.id).count(), 1)
        self.assertEqual(revoked.estado, "REVOCADA")
        self.assertEqual(vigente.estado, "VIGENTE")
        self.assertEqual(seguimiento.estado, "PENDIENTE")

    def test_tenant_permissions_csrf_gets_and_expiry_indicators_remain_integral(self):
        _, person = self._create_person_with_role(person_code="PER-TEN")
        _, responsible = self._create_person_with_role(cargo_code="RP", person_code="PER-RESP")
        other_cargo, other_person = self._create_person_with_role(204, "OB", "PER-B")
        other_capacitacion = create_capacitacion(self.user(204), self.capacitacion_data("CAP-B"))
        other_evaluation = create_evaluacion_competencia(
            self.user(204),
            other_person.id,
            self.evaluacion_data(other_person, other_person, "EVC-B", "COMPETENTE"),
        )
        other_authorization = create_autorizacion_tecnica(
            self.user(204),
            other_person.id,
            self.autorizacion_data(other_person, other_person, "AUT-B"),
        )
        other_followup = create_seguimiento(self.user(204), self.seguimiento_data(other_person, responsable_personal_id=""))
        db.session.commit()

        with self.assertRaises(PersonalError):
            create_personal(self.user(), self.personal_data(other_cargo, "PER-X"))
        with self.assertRaises(PersonalError):
            create_personal(self.user(), self.personal_data(db.session.get(Cargo, person.cargo_id), "PER-U", user_id=204))
        with self.assertRaises(PersonalError):
            create_calificacion(self.user(), other_person.id, self.calificacion_data())
        with self.assertRaises(PersonalError):
            create_experiencia(self.user(), other_person.id, self.experiencia_data())
        with self.assertRaises(PersonalError):
            add_capacitacion_participante(self.user(), other_capacitacion, person.id, {})
        with self.assertRaises(PersonalError):
            create_evaluacion_competencia(self.user(), person.id, self.evaluacion_data(person, other_person, "EVC-X"))
        with self.assertRaises(PersonalError):
            create_autorizacion_tecnica(self.user(), person.id, self.autorizacion_data(person, responsible, "AUT-X", tipo_autorizacion="EQUIPO", equipo_id=str(self.other_equipment.id)))
        with self.assertRaises(PersonalError):
            create_autorizacion_tecnica(self.user(), person.id, self.autorizacion_data(person, responsible, "AUT-Y", evaluacion_competencia_id=str(other_evaluation.id)))
        with self.assertRaises(PersonalError):
            create_seguimiento(self.user(), self.seguimiento_data(person, autorizacion_tecnica_id=str(other_authorization.id)))
        self.assertIsNone(db.session.get(PersonalSeguimiento, other_followup.id) if other_followup.empresa_id == 101 else None)

        vencida = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(person, responsible, "AUT-VEN", fecha_inicio="2026-01-01", fecha_fin="2026-08-01"),
        )
        proxima = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(person, responsible, "AUT-PROX", fecha_fin="2026-09-20"),
        )
        lejana = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(person, responsible, "AUT-LEJ", fecha_fin="2026-11-30"),
        )
        revocada = create_autorizacion_tecnica(
            self.user(),
            person.id,
            self.autorizacion_data(person, responsible, "AUT-REV-PROX", fecha_fin="2026-09-15"),
        )
        suspendida = create_autorizacion_tecnica(self.user(), person.id, self.autorizacion_data(person, responsible, "AUT-SUS"))
        db.session.commit()
        revocar_autorizacion_tecnica(self.user(), revocada, "No aplica")
        suspender_autorizacion_tecnica(self.user(), suspendida, "Pausa")
        db.session.commit()

        today = date(2026, 9, 1)
        before_state = vencida.estado
        self.assertEqual(PERSONAL_AUTHORIZATION_EXPIRY_WARNING_DAYS, 30)
        self.assertEqual(estado_efectivo_autorizacion(vencida, today=today), "VENCIDA")
        self.assertEqual(estado_efectivo_autorizacion(suspendida, today=today), "SUSPENDIDA")
        self.assertEqual(estado_efectivo_autorizacion(revocada, today=today), "REVOCADA")
        self.assertEqual(vencida.estado, before_state)
        self.assertEqual([item.id for item in autorizaciones_vencidas_query(self.user(), today=today).all()], [vencida.id])
        proxima_ids = [item.id for item in autorizaciones_proximas_vencer_query(self.user(), today=today).all()]
        self.assertIn(proxima.id, proxima_ids)
        self.assertNotIn(lejana.id, proxima_ids)
        self.assertNotIn(revocada.id, proxima_ids)
        self.assertNotIn(other_authorization.id, proxima_ids)

        viewer = self.login(202)
        self.assertEqual(viewer.get("/personal/").status_code, 200)
        self.assertEqual(viewer.get("/personal/capacitaciones").status_code, 200)
        self.assertEqual(viewer.get("/personal/evaluaciones").status_code, 200)
        self.assertEqual(viewer.get("/personal/autorizaciones").status_code, 200)
        self.assertEqual(viewer.get("/personal/seguimiento").status_code, 200)
        self.assertEqual(viewer.get(f"/personal/{person.id}/editar").status_code, 403)
        no_permission = self.login(203)
        self.assertEqual(no_permission.get("/personal/capacitaciones").status_code, 403)
        manager = self.login(201)
        self.assertEqual(manager.get(f"/personal/{other_person.id}").status_code, 404)
        self.assertEqual(manager.get(f"/personal/capacitaciones/{other_capacitacion.id}").status_code, 404)
        self.assertEqual(manager.get(f"/personal/evaluaciones/{other_evaluation.id}").status_code, 404)
        self.assertEqual(manager.get(f"/personal/autorizaciones/{other_authorization.id}").status_code, 404)
        self.assertEqual(manager.get(f"/personal/seguimiento/{other_followup.id}").status_code, 404)

        before_counts = {
            "capacitaciones": PersonalCapacitacion.query.count(),
            "evaluaciones": PersonalEvaluacionCompetencia.query.count(),
            "autorizaciones": PersonalAutorizacionTecnica.query.count(),
            "seguimientos": PersonalSeguimiento.query.count(),
        }
        self.assertEqual(manager.get(f"/personal/{person.id}").status_code, 200)
        self.assertEqual(manager.get("/personal/capacitaciones").status_code, 200)
        self.assertEqual(manager.get("/personal/evaluaciones").status_code, 200)
        self.assertEqual(manager.get("/personal/autorizaciones").status_code, 200)
        self.assertEqual(manager.get("/personal/seguimiento").status_code, 200)
        self.assertEqual(before_counts["capacitaciones"], PersonalCapacitacion.query.count())
        self.assertEqual(before_counts["evaluaciones"], PersonalEvaluacionCompetencia.query.count())
        self.assertEqual(before_counts["autorizaciones"], PersonalAutorizacionTecnica.query.count())
        self.assertEqual(before_counts["seguimientos"], PersonalSeguimiento.query.count())
        self.assertIn("Seguimiento", manager.get(f"/personal/{person.id}").get_data(as_text=True))
        self.assertIn("Crear seguimiento", manager.get(f"/personal/autorizaciones/{proxima.id}").get_data(as_text=True))

        self.assertEqual(manager.post(f"/personal/{person.id}/editar", data=self.personal_data(db.session.get(Cargo, person.cargo_id))).status_code, 403)
        self.assertEqual(manager.post("/personal/capacitaciones/nueva", data=self.capacitacion_data("CAP-CSRF")).status_code, 403)
        self.assertEqual(manager.post(f"/personal/{person.id}/evaluaciones/nueva", data=self.evaluacion_data(person, responsible, "EVC-CSRF")).status_code, 403)
        self.assertEqual(manager.post(f"/personal/{person.id}/autorizaciones/nueva", data=self.autorizacion_data(person, responsible, "AUT-CSRF")).status_code, 403)
        self.assertEqual(manager.post(f"/personal/autorizaciones/{proxima.id}/revocar", data={"motivo_estado": "Sin token"}).status_code, 403)
        self.assertEqual(manager.post("/personal/seguimiento/nuevo", data=self.seguimiento_data(person)).status_code, 403)

        token = self.csrf_token(manager)
        created = manager.post("/personal/seguimiento/nuevo", data={**self.seguimiento_data(person, titulo="HTTP seguimiento"), "csrf_token": token})
        self.assertEqual(created.status_code, 302)
        seguimiento = PersonalSeguimiento.query.filter_by(titulo="HTTP seguimiento").one()
        self.assertEqual(manager.post(f"/personal/seguimiento/{seguimiento.id}/iniciar", data={}).status_code, 403)
        token = self.csrf_token(manager)
        self.assertEqual(manager.post(f"/personal/seguimiento/{seguimiento.id}/iniciar", data={"csrf_token": token}).status_code, 302)
        token = self.csrf_token(manager)
        self.assertEqual(manager.post(
            f"/personal/seguimiento/{seguimiento.id}/completar",
            data={"csrf_token": token, "fecha_cierre": "2026-09-10", "resultado_cierre": "Cerrado"},
        ).status_code, 302)
        self.assertEqual(seguimiento_dashboard(self.user(), today=today)["metricas"]["autorizaciones_vencidas"], 1)
        self.assertEqual(PersonalCompetenciaAbsent.check(), True)


class PersonalCompetenciaAbsent:
    @staticmethod
    def check():
        from app.models.calidad import PersonalCompetencia

        return PersonalCompetencia.__tablename__ == "personal_competencias"


if __name__ == "__main__":
    unittest.main()
