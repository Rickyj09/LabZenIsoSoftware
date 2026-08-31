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
    Personal,
    PersonalAutorizacionTecnica,
    PersonalAutorizacionTecnicaEvidencia,
    PersonalCapacitacion,
    PersonalCalificacion,
    PersonalEvaluacionCompetencia,
    PersonalExperiencia,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.security.permissions import user_has_permission
from app.services.personal_service import (
    PersonalError,
    add_autorizacion_tecnica_evidencia,
    create_autorizacion_tecnica,
    create_calificacion,
    create_capacitacion,
    create_cargo,
    create_evaluacion_competencia,
    create_experiencia,
    create_personal,
    estado_efectivo_autorizacion,
    reactivar_autorizacion_tecnica,
    revocar_autorizacion_tecnica,
    suspender_autorizacion_tecnica,
    update_autorizacion_tecnica,
)
from app.services.storage_service import resolve_document_path


PERSONAL_PERMISSIONS = ("personal.ver", "personal.gestionar")


class Personal4ETest(unittest.TestCase):
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
        self.authorizer = self._create_person(user_id=201, cargo_code="AU", person_code="PER-AUT")
        self.other_person = self._create_person(user_id=204, cargo_code="OT", person_code="PER-OTRA")
        self.equipment = self._create_equipment(empresa_id=101, code="EQ-001")
        self.other_equipment = self._create_equipment(empresa_id=102, code="EQ-OTRA")
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
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@per4e", username="admin-per4e", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@per4e", username="consulta-per4e", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin@per4e", username="sin-per4e", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@per4e", username="admin2-per4e", password_hash="x", activo=True),
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

    def _create_equipment(self, empresa_id, code):
        equipo = Equipo(
            empresa_id=empresa_id,
            codigo=code,
            nombre=f"Equipo {code}",
            tipo="Instrumento",
            estado="activo",
            estado_operativo="OPERATIVO",
        )
        db.session.add(equipo)
        db.session.flush()
        return equipo

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

    def authorization_data(self, **overrides):
        data = {
            "codigo": "AUT-001",
            "personal_id": str(self.person.id),
            "tipo_autorizacion": "ACTIVIDAD_TECNICA",
            "actividad": "preparacion de muestras",
            "alcance": "Puede preparar muestras de agua bajo procedimientos internos vigentes.",
            "descripcion": "Autorizacion inicial",
            "equipo_id": "",
            "metodo_referencia": "",
            "metodo_descripcion": "",
            "evaluacion_competencia_id": "",
            "autorizador_personal_id": str(self.authorizer.id),
            "autorizador_usuario_id": "",
            "autorizador_externo_nombre": "",
            "autorizador_externo_entidad": "",
            "fecha_autorizacion": "2026-08-25",
            "fecha_inicio": "2026-09-01",
            "fecha_fin": "",
            "estado": "VIGENTE",
            "fundamento": "Experiencia, capacitacion y evidencia documental revisadas.",
            "observaciones": "Sin restricciones adicionales",
        }
        data.update(overrides)
        return data

    def evaluation_data(self, **overrides):
        data = {
            "codigo": "EVC-4E",
            "personal_id": str(self.person.id),
            "evaluador_personal_id": str(self.authorizer.id),
            "actividad": "preparacion de muestras",
            "descripcion": "Demostracion tecnica",
            "tipo_competencia": "TECNICA",
            "metodo_evaluacion": "OBSERVACION_DIRECTA",
            "criterio_evaluacion": "Cumple procedimiento",
            "fecha_evaluacion": "2026-08-20",
            "resultado": "COMPETENTE",
            "evaluador_externo_nombre": "",
        }
        data.update(overrides)
        return data

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

    def capacitacion_data(self):
        return {
            "codigo": "CAP-4E",
            "nombre": "Entrenamiento autorizacion",
            "tipo": "ENTRENAMIENTO",
            "modalidad": "PRESENCIAL",
            "fecha_inicio": "2026-08-01",
            "estado": "COMPLETADA",
        }

    @staticmethod
    def evidence_file(name="autorizacion.pdf", content=b"evidencia autorizacion"):
        return FileStorage(stream=BytesIO(content), filename=name, content_type="application/pdf")

    def test_creates_activity_equipment_and_method_authorizations(self):
        activity = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data())
        equipment = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(
                codigo="AUT-EQ",
                tipo_autorizacion="EQUIPO",
                actividad="operar balanza",
                equipo_id=str(self.equipment.id),
            ),
        )
        method = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(
                codigo="AUT-MET",
                tipo_autorizacion="METODO",
                actividad="ejecutar metodo",
                metodo_referencia="ISO 10523",
                metodo_descripcion="Determinacion de pH",
            ),
        )
        db.session.commit()

        self.assertEqual(activity.tipo_autorizacion, "ACTIVIDAD_TECNICA")
        self.assertEqual(equipment.equipo_id, self.equipment.id)
        self.assertEqual(method.metodo_referencia, "ISO 10523")
        self.assertEqual(self.equipment.estado_operativo, "OPERATIVO")

    def test_validates_required_fields_types_dates_equipment_and_method_reference(self):
        cases = [
            self.authorization_data(personal_id=""),
            self.authorization_data(actividad=""),
            self.authorization_data(tipo_autorizacion="INVALIDA"),
            self.authorization_data(fecha_autorizacion=""),
            self.authorization_data(fecha_inicio=""),
            self.authorization_data(fecha_fin="2026-08-31"),
            self.authorization_data(tipo_autorizacion="EQUIPO", equipo_id=""),
            self.authorization_data(tipo_autorizacion="METODO", metodo_referencia=""),
        ]
        for data in cases:
            with self.assertRaises(PersonalError):
                create_autorizacion_tecnica(self.user(), data.get("personal_id"), data)

        create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(codigo="AUT-SIN-EQ"))
        db.session.commit()
        self.assertIsNone(PersonalAutorizacionTecnica.query.filter_by(codigo="AUT-SIN-EQ").one().equipo_id)

    def test_rejects_cross_tenant_equipment_authorizer_evaluation_and_authorization(self):
        with self.assertRaises(PersonalError):
            create_autorizacion_tecnica(
                self.user(),
                self.person.id,
                self.authorization_data(tipo_autorizacion="EQUIPO", equipo_id=str(self.other_equipment.id)),
            )
        with self.assertRaises(PersonalError):
            create_autorizacion_tecnica(
                self.user(),
                self.person.id,
                self.authorization_data(autorizador_personal_id=str(self.other_person.id)),
            )
        other_auth = create_autorizacion_tecnica(
            self.user(204),
            self.other_person.id,
            self.authorization_data(
                codigo="AUT-OTRA",
                personal_id=str(self.other_person.id),
                autorizador_personal_id="",
                autorizador_externo_nombre="Director externo",
            ),
        )
        db.session.commit()
        with self.assertRaises(PersonalError):
            update_autorizacion_tecnica(self.user(), other_auth, self.authorization_data())
        self.assertEqual(self.login(201).get(f"/personal/autorizaciones/{other_auth.id}").status_code, 404)

    def test_evaluation_foundation_rules(self):
        competent = create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data(codigo="EVC-COMP"))
        observed = create_evaluacion_competencia(
            self.user(),
            self.person.id,
            self.evaluation_data(codigo="EVC-OBS", resultado="COMPETENTE_CON_OBSERVACIONES"),
        )
        no_competent = create_evaluacion_competencia(
            self.user(),
            self.person.id,
            self.evaluation_data(codigo="EVC-NO", resultado="NO_COMPETENTE"),
        )
        training = create_evaluacion_competencia(
            self.user(),
            self.person.id,
            self.evaluation_data(codigo="EVC-TR", resultado="REQUIERE_ENTRENAMIENTO"),
        )
        other_person_eval = create_evaluacion_competencia(
            self.user(),
            self.authorizer.id,
            self.evaluation_data(codigo="EVC-OTHER", personal_id=str(self.authorizer.id)),
        )
        other_company_eval = create_evaluacion_competencia(
            self.user(204),
            self.other_person.id,
            self.evaluation_data(
                codigo="EVC-EMP2",
                personal_id=str(self.other_person.id),
                evaluador_personal_id="",
                evaluador_externo_nombre="Externo",
            ),
        )
        db.session.flush()

        create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(codigo="AUT-COMP", evaluacion_competencia_id=str(competent.id)))
        create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(codigo="AUT-OBS", evaluacion_competencia_id=str(observed.id)))
        for evaluation in (no_competent, training, other_person_eval, other_company_eval):
            with self.assertRaises(PersonalError):
                create_autorizacion_tecnica(
                    self.user(),
                    self.person.id,
                    self.authorization_data(codigo=f"AUT-BAD-{evaluation.id}", evaluacion_competencia_id=str(evaluation.id)),
                )
        create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(codigo="AUT-SIN-EVAL", evaluacion_competencia_id=""))
        with self.assertRaises(PersonalError):
            create_autorizacion_tecnica(
                self.user(),
                self.person.id,
                self.authorization_data(codigo="AUT-SIN-FUND", evaluacion_competencia_id="", fundamento=""),
            )

    def test_effective_status_and_state_transitions(self):
        vigente = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(codigo="AUT-VIG"))
        vencida = create_autorizacion_tecnica(
            self.user(),
            self.person.id,
            self.authorization_data(codigo="AUT-VEN", fecha_inicio="2026-01-01", fecha_fin="2026-01-31"),
        )
        db.session.commit()

        self.assertEqual(estado_efectivo_autorizacion(vigente, today=date(2026, 9, 2)), "VIGENTE")
        self.assertEqual(estado_efectivo_autorizacion(vencida, today=date(2026, 9, 2)), "VENCIDA")

        suspender_autorizacion_tecnica(self.user(), vigente, "Pausa temporal", "2026-09-05")
        db.session.commit()
        self.assertEqual(vigente.estado, "SUSPENDIDA")
        self.assertEqual(estado_efectivo_autorizacion(vigente, today=date(2026, 9, 6)), "SUSPENDIDA")

        reactivar_autorizacion_tecnica(self.user(), vigente, "Causa resuelta", "2026-09-06")
        db.session.commit()
        self.assertEqual(vigente.estado, "VIGENTE")

        revocar_autorizacion_tecnica(self.user(), vigente, "Cambio de alcance", "2026-09-07")
        db.session.commit()
        self.assertEqual(vigente.estado, "REVOCADA")
        with self.assertRaises(PersonalError):
            reactivar_autorizacion_tecnica(self.user(), vigente, "No permitido")

    def test_history_preserves_revoked_authorization_with_new_record(self):
        revoked = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(codigo="AUT-H1"))
        db.session.commit()
        revocar_autorizacion_tecnica(self.user(), revoked, "Se reemplaza por nueva autorizacion")
        replacement = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(codigo="AUT-H2"))
        db.session.commit()

        self.assertEqual(PersonalAutorizacionTecnica.query.filter_by(personal_id=self.person.id).count(), 2)
        self.assertEqual(revoked.estado, "REVOCADA")
        self.assertEqual(replacement.estado, "VIGENTE")
        with self.assertRaises(PersonalError):
            update_autorizacion_tecnica(self.user(), revoked, self.authorization_data())

    def test_evidence_upload_download_and_cross_tenant_isolation(self):
        autorizacion = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data())
        db.session.flush()
        evidencia = add_autorizacion_tecnica_evidencia(
            self.user(),
            autorizacion,
            self.evidence_file("../acta.pdf"),
            {"tipo_evidencia": "ACTA_AUTORIZACION", "observaciones": "Acta firmada"},
        )
        db.session.commit()

        self.assertTrue(evidencia.archivo_storage_path.startswith(
            f"empresa_101/personal_{self.person.id}/autorizacion_tecnica_{autorizacion.id}/evidencias/"
        ))
        self.assertTrue(resolve_document_path(evidencia.archivo_storage_path).is_file())
        self.assertNotIn("..", evidencia.archivo_nombre_guardado)

        response = self.login(201).get(f"/personal/autorizaciones/evidencias/{evidencia.id}/descargar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"evidencia autorizacion")
        response.close()
        self.assertEqual(self.login(204).get(f"/personal/autorizaciones/evidencias/{evidencia.id}/descargar").status_code, 404)

    def test_http_permissions_csrf_list_detail_and_person_detail(self):
        viewer = self.login(202)
        self.assertEqual(viewer.get("/personal/autorizaciones").status_code, 200)
        self.assertEqual(viewer.get(f"/personal/{self.person.id}/autorizaciones/nueva").status_code, 403)

        no_permission = self.login(203)
        self.assertEqual(no_permission.get("/personal/autorizaciones").status_code, 403)

        manager = self.login(201)
        form = manager.get(f"/personal/{self.person.id}/autorizaciones/nueva")
        self.assertEqual(form.status_code, 200)
        self.assertEqual(manager.post(f"/personal/{self.person.id}/autorizaciones/nueva", data=self.authorization_data()).status_code, 403)

        token = self.csrf_token(manager)
        created = manager.post(
            f"/personal/{self.person.id}/autorizaciones/nueva",
            data={**self.authorization_data(), "csrf_token": token},
        )
        self.assertEqual(created.status_code, 302)
        autorizacion = PersonalAutorizacionTecnica.query.filter_by(codigo="AUT-001", empresa_id=101).one()

        index = manager.get("/personal/autorizaciones?q=preparacion")
        detail = manager.get(f"/personal/autorizaciones/{autorizacion.id}")
        person_detail = manager.get(f"/personal/{self.person.id}")
        self.assertIn("preparacion de muestras", index.get_data(as_text=True))
        self.assertIn("Fundamento", detail.get_data(as_text=True))
        self.assertIn("Autorizaciones tecnicas", person_detail.get_data(as_text=True))

    def test_http_state_and_evidence_mutations_require_csrf(self):
        autorizacion = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data())
        db.session.commit()
        client = self.login(201)
        client.get(f"/personal/autorizaciones/{autorizacion.id}")

        self.assertEqual(client.post(
            f"/personal/autorizaciones/{autorizacion.id}/suspender",
            data={"motivo_estado": "Sin token"},
        ).status_code, 403)
        token = self.csrf_token(client)
        self.assertEqual(client.post(
            f"/personal/autorizaciones/{autorizacion.id}/suspender",
            data={"csrf_token": token, "motivo_estado": "Revision temporal"},
        ).status_code, 302)
        self.assertEqual(db.session.get(PersonalAutorizacionTecnica, autorizacion.id).estado, "SUSPENDIDA")

        token = self.csrf_token(client)
        self.assertEqual(client.post(
            f"/personal/autorizaciones/{autorizacion.id}/reactivar",
            data={"csrf_token": token, "motivo_estado": "Revision completada"},
        ).status_code, 302)
        self.assertEqual(db.session.get(PersonalAutorizacionTecnica, autorizacion.id).estado, "VIGENTE")

        token = self.csrf_token(client)
        uploaded = client.post(
            f"/personal/autorizaciones/{autorizacion.id}/evidencias",
            data={"csrf_token": token, "evidencia": (BytesIO(b"x"), "autorizacion.pdf"), "tipo_evidencia": "MATRIZ_FIRMADA"},
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 302)
        self.assertEqual(PersonalAutorizacionTecnicaEvidencia.query.filter_by(autorizacion_id=autorizacion.id).count(), 1)
        self.assertEqual(len(list(Path(self.temp_directory.name).rglob("*.pdf"))), 1)

    def test_competent_evaluation_does_not_create_authorization_automatically(self):
        create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data(resultado="COMPETENTE"))
        db.session.commit()

        self.assertEqual(PersonalEvaluacionCompetencia.query.filter_by(personal_id=self.person.id).count(), 1)
        self.assertEqual(PersonalAutorizacionTecnica.query.filter_by(personal_id=self.person.id).count(), 0)
        self.assertFalse(hasattr(db.session.get(Personal, self.person.id), "autorizado"))

    def test_basic_4a_4b_4c_4d_regressions_remain_person_scoped(self):
        calificacion = create_calificacion(self.user(), self.person.id, self.calificacion_data())
        experiencia = create_experiencia(self.user(), self.person.id, self.experiencia_data())
        capacitacion = create_capacitacion(self.user(), self.capacitacion_data())
        evaluacion = create_evaluacion_competencia(self.user(), self.person.id, self.evaluation_data())
        autorizacion = create_autorizacion_tecnica(self.user(), self.person.id, self.authorization_data(evaluacion_competencia_id=""))
        db.session.commit()

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
