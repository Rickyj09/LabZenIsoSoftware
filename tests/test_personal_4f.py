import unittest
from datetime import date

from flask import g
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.empresa import Empresa
from app.models.equipos import Equipo
from app.models.organigrama import (
    Cargo,
    Personal,
    PersonalAutorizacionTecnica,
    PersonalCapacitacion,
    PersonalCalificacion,
    PersonalEvaluacionCompetencia,
    PersonalExperiencia,
    PersonalSeguimiento,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.personal_service import (
    PersonalError,
    autorizaciones_proximas_vencer_query,
    autorizaciones_vencidas_query,
    cancelar_seguimiento,
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
    personal_followup_summary,
    seguimiento_dashboard,
    update_seguimiento,
)


PERSONAL_PERMISSIONS = ("personal.ver", "personal.gestionar")


class Personal4FTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DOCUMENT_STORAGE_ROOT": "/tmp/labzen-test",
            "DOCUMENT_LEGACY_STORAGE_ROOT": "/tmp/labzen-test",
            "ONLYOFFICE_ENABLED": False,
            "ONLYOFFICE_EDIT_ENABLED": False,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.next_id = 20000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        self._seed_security()
        self.person = self._create_person(201, "DT", "PER-4F")
        self.responsible = self._create_person(201, "RS", "PER-RESP")
        self.other_person = self._create_person(204, "OT", "PER-OTRA")
        self.equipment = self._create_equipment(101, "EQ-4F")
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _seed_security(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@per4f", username="admin-per4f", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@per4f", username="consulta-per4f", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin@per4f", username="sin-per4f", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@per4f", username="admin2-per4f", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, code in enumerate(PERSONAL_PERMISSIONS, start=1):
            permission = Permiso(id=2100 + offset, codigo=code, nombre=code, modulo="personal")
            db.session.add(permission)
            permissions[code] = permission
        manager = Rol(id=2201, nombre="CALIDAD", es_sistema=True)
        viewer = Rol(id=2202, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([manager, viewer])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=2301, rol_id=manager.id, permiso_id=permissions["personal.ver"].id),
            RolPermiso(id=2302, rol_id=manager.id, permiso_id=permissions["personal.gestionar"].id),
            RolPermiso(id=2303, rol_id=viewer.id, permiso_id=permissions["personal.ver"].id),
            UsuarioRol(id=2401, usuario_id=201, rol_id=manager.id),
            UsuarioRol(id=2402, usuario_id=202, rol_id=viewer.id),
            UsuarioRol(id=2403, usuario_id=204, rol_id=manager.id),
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

    def seguimiento_data(self, **overrides):
        data = {
            "personal_id": str(self.person.id),
            "tipo": "OBSERVACION",
            "titulo": "Revision periodica de desempeno",
            "descripcion": "Seguimiento rutinario",
            "fecha_deteccion": "2026-08-31",
            "fecha_objetivo": "2026-09-15",
            "estado": "PENDIENTE",
            "prioridad": "MEDIA",
            "responsable_personal_id": str(self.responsible.id),
            "responsable_usuario_id": "",
            "evaluacion_competencia_id": "",
            "autorizacion_tecnica_id": "",
            "capacitacion_id": "",
            "accion_requerida": "Revisar desempeno y registrar resultado.",
            "resultado_cierre": "",
            "observaciones": "",
        }
        data.update(overrides)
        return data

    def evaluation_data(self, **overrides):
        data = {
            "codigo": "EVC-4F",
            "personal_id": str(self.person.id),
            "evaluador_personal_id": str(self.responsible.id),
            "actividad": "operacion rutinaria",
            "tipo_competencia": "TECNICA",
            "metodo_evaluacion": "OBSERVACION_DIRECTA",
            "criterio_evaluacion": "Cumple procedimiento",
            "fecha_evaluacion": "2026-08-20",
            "resultado": "REQUIERE_ENTRENAMIENTO",
            "evaluador_externo_nombre": "",
        }
        data.update(overrides)
        return data

    def authorization_data(self, **overrides):
        data = {
            "codigo": "AUT-4F",
            "personal_id": str(self.person.id),
            "tipo_autorizacion": "ACTIVIDAD_TECNICA",
            "actividad": "operacion rutinaria",
            "alcance": "Operacion bajo supervision.",
            "descripcion": "",
            "equipo_id": "",
            "metodo_referencia": "",
            "metodo_descripcion": "",
            "evaluacion_competencia_id": "",
            "autorizador_personal_id": str(self.responsible.id),
            "autorizador_usuario_id": "",
            "autorizador_externo_nombre": "",
            "fecha_autorizacion": "2026-01-01",
            "fecha_inicio": "2026-01-01",
            "fecha_fin": "2026-09-10",
            "estado": "VIGENTE",
            "fundamento": "Competencia demostrada previamente.",
        }
        data.update(overrides)
        return data

    def capacitacion_data(self):
        return {
            "codigo": "CAP-4F",
            "nombre": "Entrenamiento de refuerzo",
            "tipo": "ENTRENAMIENTO",
            "modalidad": "PRESENCIAL",
            "fecha_inicio": "2026-09-01",
            "estado": "PLANIFICADA",
        }

    def test_create_edit_start_complete_cancel_and_history(self):
        item = create_seguimiento(self.user(), self.seguimiento_data())
        db.session.commit()
        self.assertEqual(item.estado, "PENDIENTE")

        update_seguimiento(self.user(), item, self.seguimiento_data(titulo="Revision actualizada", prioridad="ALTA"))
        iniciar_seguimiento(self.user(), item)
        db.session.commit()
        self.assertEqual(item.estado, "EN_PROCESO")
        self.assertEqual(item.prioridad, "ALTA")

        with self.assertRaises(PersonalError):
            completar_seguimiento(self.user(), item, {"fecha_cierre": "2026-09-05", "resultado_cierre": ""})
        completar_seguimiento(self.user(), item, {"fecha_cierre": "2026-09-05", "resultado_cierre": "Desempeno conforme"})
        db.session.commit()
        self.assertEqual(PersonalSeguimiento.query.count(), 1)
        self.assertEqual(item.estado, "COMPLETADO")
        self.assertEqual(item.fecha_cierre, date(2026, 9, 5))

        canceled = create_seguimiento(self.user(), self.seguimiento_data(titulo="Seguimiento cancelable"))
        cancelar_seguimiento(self.user(), canceled, {"resultado_cierre": "No aplica"})
        db.session.commit()
        self.assertEqual(PersonalSeguimiento.query.count(), 2)
        self.assertEqual(canceled.estado, "CANCELADO")

    def test_validations_dates_responsible_and_relations(self):
        eval_ok = create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data())
        eval_other_person = create_evaluacion_competencia(
            self.user(),
            self.responsible.id,
            self.evaluation_data(codigo="EVC-OTHER", personal_id=str(self.responsible.id)),
        )
        auth_ok = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data())
        auth_other_person = create_autorizacion_tecnica(
            self.user(),
            self.responsible.id,
            self.authorization_data(codigo="AUT-OTHER", personal_id=str(self.responsible.id)),
        )
        capacitacion = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.flush()

        create_seguimiento(self.user(), self.seguimiento_data(
            evaluacion_competencia_id=str(eval_ok.id),
            autorizacion_tecnica_id=str(auth_ok.id),
            capacitacion_id=str(capacitacion.id),
        ))
        bad_cases = [
            self.seguimiento_data(personal_id=""),
            self.seguimiento_data(tipo="INVALIDO"),
            self.seguimiento_data(prioridad="URGENTE"),
            self.seguimiento_data(estado="CERRADO"),
            self.seguimiento_data(fecha_objetivo="2026-08-01"),
            self.seguimiento_data(responsable_personal_id=str(self.other_person.id)),
            self.seguimiento_data(evaluacion_competencia_id=str(eval_other_person.id)),
            self.seguimiento_data(autorizacion_tecnica_id=str(auth_other_person.id)),
        ]
        for data in bad_cases:
            with self.assertRaises(PersonalError):
                create_seguimiento(self.user(), data)

    def test_tenant_permissions_and_csrf(self):
        item = create_seguimiento(self.user(), self.seguimiento_data())
        other = create_seguimiento(
            self.user(204),
            self.seguimiento_data(
                personal_id=str(self.other_person.id),
                responsable_personal_id="",
                titulo="Seguimiento otro tenant",
            ),
        )
        db.session.commit()
        with self.assertRaises(PersonalError):
            update_seguimiento(self.user(), other, self.seguimiento_data())

        viewer = self.login(202)
        self.assertEqual(viewer.get("/personal/seguimiento").status_code, 200)
        self.assertEqual(viewer.get(f"/personal/seguimiento/{item.id}").status_code, 200)
        self.assertEqual(viewer.get("/personal/seguimiento/nuevo").status_code, 403)
        self.assertEqual(self.login(203).get("/personal/seguimiento").status_code, 403)
        self.assertEqual(self.login(204).get(f"/personal/seguimiento/{item.id}").status_code, 404)

        manager = self.login(201)
        manager.get("/personal/seguimiento/nuevo")
        self.assertEqual(manager.post("/personal/seguimiento/nuevo", data=self.seguimiento_data()).status_code, 403)
        token = self.csrf_token(manager)
        created = manager.post("/personal/seguimiento/nuevo", data={**self.seguimiento_data(titulo="HTTP seguimiento"), "csrf_token": token})
        self.assertEqual(created.status_code, 302)
        created_item = PersonalSeguimiento.query.filter_by(titulo="HTTP seguimiento").one()
        manager.get(f"/personal/seguimiento/{created_item.id}")
        self.assertIn("HTTP seguimiento", manager.get("/personal/seguimiento").get_data(as_text=True))

    def test_derived_authorization_and_evaluation_indicators_have_no_get_side_effects(self):
        vencida = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(codigo="AUT-VEN", fecha_inicio="2026-01-01", fecha_fin="2026-08-01"),
        )
        proxima = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(codigo="AUT-PROX", fecha_fin="2026-09-10"),
        )
        lejana = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(codigo="AUT-LEJ", fecha_fin="2026-12-01"),
        )
        revocada = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(codigo="AUT-REV", fecha_fin="2026-09-05"),
        )
        revocada.estado = "REVOCADA"
        suspendida = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(codigo="AUT-SUS", fecha_fin="2026-09-05"),
        )
        suspendida.estado = "SUSPENDIDA"
        req_training = create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data(codigo="EVC-TR", resultado="REQUIERE_ENTRENAMIENTO"))
        no_comp = create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data(codigo="EVC-NO", resultado="NO_COMPETENTE"))
        competent = create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data(codigo="EVC-OK", resultado="COMPETENTE"))
        db.session.commit()

        today = date(2026, 8, 31)
        self.assertEqual([item.id for item in autorizaciones_vencidas_query(self.user(), today=today).all()], [vencida.id])
        self.assertIn(proxima.id, [item.id for item in autorizaciones_proximas_vencer_query(self.user(), today=today).all()])
        self.assertNotIn(lejana.id, [item.id for item in autorizaciones_proximas_vencer_query(self.user(), today=today).all()])
        self.assertNotIn(revocada.id, [item.id for item in autorizaciones_proximas_vencer_query(self.user(), today=today).all()])
        self.assertNotIn(suspendida.id, [item.id for item in autorizaciones_proximas_vencer_query(self.user(), today=today).all()])
        self.assertEqual(estado_efectivo_autorizacion(vencida, today=today), "VENCIDA")

        actions = [item.id for item in evaluaciones_requieren_accion_query(self.user()).all()]
        self.assertIn(req_training.id, actions)
        self.assertIn(no_comp.id, actions)
        self.assertNotIn(competent.id, actions)

        before = PersonalSeguimiento.query.count()
        response = self.login(201).get("/personal/seguimiento")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PersonalSeguimiento.query.count(), before)
        self.assertIn("Autorizaciones vencidas", response.get_data(as_text=True))
        self.assertIn("SUSPENDIDA", self.login(201).get(f"/personal/autorizaciones/{suspendida.id}").get_data(as_text=True))

    def test_person_detail_integration_dashboard_summary_and_regressions(self):
        calificacion = create_calificacion(self.user(), self.person.id, {
            "tipo": "CERTIFICACION",
            "institucion": "Entidad",
            "titulo": "Certificado",
            "fecha_fin": "2026-01-01",
            "activo": "1",
        })
        experiencia = create_experiencia(self.user(), self.person.id, {
            "organizacion": "Laboratorio",
            "cargo_funcion": "Analista",
            "fecha_inicio": "2025-01-01",
            "experiencia_actual": "1",
            "activo": "1",
        })
        capacitacion = create_capacitacion(self.user(), self.capacitacion_data())
        evaluacion = create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data(resultado="REQUIERE_ENTRENAMIENTO"))
        autorizacion = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(fecha_fin="2026-09-10"))
        seguimiento = create_seguimiento(self.user(), self.seguimiento_data(
            evaluacion_competencia_id=str(evaluacion.id),
            autorizacion_tecnica_id=str(autorizacion.id),
            capacitacion_id=str(capacitacion.id),
        ))
        db.session.commit()

        summary = personal_followup_summary(self.user(), self.person, today=date(2026, 8, 31))
        self.assertEqual(summary["seguimientos_abiertos"], 1)
        self.assertEqual(summary["autorizaciones_proximas"], 1)
        self.assertEqual(seguimiento_dashboard(self.user(), today=date(2026, 8, 31))["metricas"]["evaluaciones_requieren_accion"], 1)

        body = self.login(201).get(f"/personal/{self.person.id}").get_data(as_text=True)
        self.assertIn("Seguimiento", body)
        self.assertIn(seguimiento.titulo, body)
        eval_body = self.login(201).get(f"/personal/evaluaciones/{evaluacion.id}").get_data(as_text=True)
        auth_body = self.login(201).get(f"/personal/autorizaciones/{autorizacion.id}").get_data(as_text=True)
        self.assertIn("Crear seguimiento", eval_body)
        self.assertIn("Crear seguimiento", auth_body)

        person = db.session.get(Personal, self.person.id)
        self.assertIsInstance(db.session.get(Cargo, person.cargo_id), Cargo)
        self.assertEqual(person.calificaciones[0].id, calificacion.id)
        self.assertEqual(person.experiencias[0].id, experiencia.id)
        self.assertEqual(PersonalCapacitacion.query.filter_by(id=capacitacion.id, empresa_id=101).count(), 1)
        self.assertEqual(person.evaluaciones_competencia[0].id, evaluacion.id)
        self.assertEqual(person.autorizaciones_tecnicas[0].id, autorizacion.id)
        self.assertEqual(PersonalCalificacion.query.filter_by(empresa_id=102).count(), 0)
        self.assertEqual(PersonalExperiencia.query.filter_by(empresa_id=102).count(), 0)


if __name__ == "__main__":
    unittest.main()
