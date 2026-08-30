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
    PersonalCapacitacionEvidencia,
    PersonalCapacitacionParticipante,
    PersonalCalificacion,
    PersonalExperiencia,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.personal_service import (
    PersonalError,
    add_capacitacion_evidencia,
    add_capacitacion_participante,
    create_calificacion,
    create_capacitacion,
    create_cargo,
    create_experiencia,
    create_personal,
    set_capacitacion_estado,
    update_capacitacion,
    update_capacitacion_participante,
)
from app.services.storage_service import resolve_document_path


PERSONAL_PERMISSIONS = ("personal.ver", "personal.gestionar")


class Personal4CTest(unittest.TestCase):
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
        self.second_person = self._create_person(user_id=201, cargo_code="AN", person_code="PER-002")
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
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@per4c", username="admin-per4c", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@per4c", username="consulta-per4c", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin@per4c", username="sin-per4c", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@per4c", username="admin2-per4c", password_hash="x", activo=True),
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

    def capacitacion_data(self):
        return {
            "codigo": "CAP-001",
            "nombre": "Buenas practicas de laboratorio",
            "tipo": "INTERNA",
            "objetivo": "Actualizar criterios de trabajo tecnico.",
            "proveedor": "LabZen",
            "instructor": "Director tecnico",
            "modalidad": "PRESENCIAL",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-08-02",
            "duracion_horas": "8.5",
            "lugar": "Sala tecnica",
            "estado": "PLANIFICADA",
            "observaciones": "Registro inicial",
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
    def evidence_file(name="lista.pdf", content=b"evidencia capacitacion"):
        return FileStorage(stream=BytesIO(content), filename=name, content_type="application/pdf")

    def test_creates_edits_lists_and_validates_training(self):
        item = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.commit()

        data = self.capacitacion_data()
        data["nombre"] = "Buenas practicas actualizadas"
        data["estado"] = "EN_CURSO"
        update_capacitacion(self.user(), item, data)
        db.session.commit()

        self.assertEqual(item.empresa_id, 101)
        self.assertEqual(item.nombre, "Buenas practicas actualizadas")
        self.assertEqual(item.estado, "EN_CURSO")

        bad_dates = self.capacitacion_data()
        bad_dates["fecha_fin"] = "2026-07-31"
        with self.assertRaises(PersonalError):
            create_capacitacion(self.user(), bad_dates)

        bad_hours = self.capacitacion_data()
        bad_hours["codigo"] = "CAP-NEG"
        bad_hours["duracion_horas"] = "-1"
        with self.assertRaises(PersonalError):
            create_capacitacion(self.user(), bad_hours)

        client = self.login(201)
        response = client.get("/personal/capacitaciones?q=actualizadas")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Buenas practicas actualizadas", response.get_data(as_text=True))

    def test_participants_tenant_duplicates_and_state_changes(self):
        item = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.flush()
        participante = add_capacitacion_participante(self.user(), item, self.person.id, {"estado_participacion": "INSCRITO"})
        db.session.commit()

        self.assertEqual(participante.empresa_id, 101)
        self.assertEqual(participante.personal_id, self.person.id)

        with self.assertRaises(PersonalError):
            add_capacitacion_participante(self.user(), item, self.person.id, {})
        with self.assertRaises(PersonalError):
            add_capacitacion_participante(self.user(), item, self.other_person.id, {})

        update_capacitacion_participante(self.user(), participante, {"estado_participacion": "COMPLETO"})
        set_capacitacion_estado(self.user(), item, "COMPLETADA")
        db.session.commit()

        self.assertEqual(participante.estado_participacion, "COMPLETO")
        self.assertEqual(item.estado, "COMPLETADA")

        other_item = create_capacitacion(self.user(204), {**self.capacitacion_data(), "codigo": "CAP-OTRA"})
        db.session.commit()
        with self.assertRaises(PersonalError):
            update_capacitacion(self.user(), other_item, self.capacitacion_data())

    def test_http_permissions_csrf_and_person_detail_history(self):
        viewer = self.login(202)
        self.assertEqual(viewer.get("/personal/capacitaciones").status_code, 200)
        self.assertEqual(viewer.get("/personal/capacitaciones/nueva").status_code, 403)

        no_permission = self.login(203)
        self.assertEqual(no_permission.get("/personal/capacitaciones").status_code, 403)

        manager = self.login(201)
        form = manager.get("/personal/capacitaciones/nueva")
        self.assertEqual(form.status_code, 200)
        missing = manager.post("/personal/capacitaciones/nueva", data=self.capacitacion_data())
        self.assertEqual(missing.status_code, 403)

        token = self.csrf_token(manager)
        created = manager.post("/personal/capacitaciones/nueva", data={**self.capacitacion_data(), "csrf_token": token})
        self.assertEqual(created.status_code, 302)
        item = PersonalCapacitacion.query.filter_by(codigo="CAP-001", empresa_id=101).one()

        token = self.csrf_token(manager)
        added = manager.post(
            f"/personal/capacitaciones/{item.id}/participantes",
            data={"csrf_token": token, "personal_id": str(self.person.id), "estado_participacion": "ASISTIO"},
        )
        self.assertEqual(added.status_code, 302)

        detail = manager.get(f"/personal/{self.person.id}")
        body = detail.get_data(as_text=True)
        self.assertIn("Capacitaciones", body)
        self.assertIn("Buenas practicas de laboratorio", body)
        self.assertIn("ASISTIO", body)

    def test_http_training_detail_state_and_cross_tenant_access(self):
        item = create_capacitacion(self.user(), self.capacitacion_data())
        other_item = create_capacitacion(self.user(204), {**self.capacitacion_data(), "codigo": "CAP-OTRA"})
        db.session.commit()

        client = self.login(201)
        self.assertEqual(client.get(f"/personal/capacitaciones/{other_item.id}").status_code, 404)

        client.get(f"/personal/capacitaciones/{item.id}")
        token = self.csrf_token(client)
        changed = client.post(
            f"/personal/capacitaciones/{item.id}/estado",
            data={"csrf_token": token, "estado": "COMPLETADA"},
        )
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(db.session.get(PersonalCapacitacion, item.id).estado, "COMPLETADA")

    def test_training_evidence_upload_download_and_individual_scope(self):
        item = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.flush()
        participante = add_capacitacion_participante(self.user(), item, self.person.id, {})
        db.session.flush()
        evidencia = add_capacitacion_evidencia(
            self.user(),
            item,
            self.evidence_file("../certificado.pdf"),
            {"tipo_evidencia": "CERTIFICADO", "participante_id": str(participante.id)},
        )
        db.session.commit()

        self.assertEqual(evidencia.empresa_id, 101)
        self.assertEqual(evidencia.capacitacion_id, item.id)
        self.assertEqual(evidencia.participante_id, participante.id)
        self.assertTrue(evidencia.archivo_storage_path.startswith(f"empresa_101/capacitacion_{item.id}/evidencias/participante_{participante.id}/"))
        self.assertTrue(resolve_document_path(evidencia.archivo_storage_path).is_file())
        self.assertNotIn("..", evidencia.archivo_nombre_guardado)

        response = self.login(201).get(f"/personal/capacitaciones/evidencias/{evidencia.id}/descargar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"evidencia capacitacion")
        response.close()

        self.assertEqual(self.login(204).get(f"/personal/capacitaciones/evidencias/{evidencia.id}/descargar").status_code, 404)

    def test_http_evidence_upload_requires_csrf_and_allows_general_evidence(self):
        item = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.commit()
        client = self.login(201)
        client.get(f"/personal/capacitaciones/{item.id}")

        missing = client.post(
            f"/personal/capacitaciones/{item.id}/evidencias",
            data={"evidencia": (BytesIO(b"x"), "asistencia.pdf"), "tipo_evidencia": "LISTA_ASISTENCIA"},
            content_type="multipart/form-data",
        )
        self.assertEqual(missing.status_code, 403)

        token = self.csrf_token(client)
        created = client.post(
            f"/personal/capacitaciones/{item.id}/evidencias",
            data={
                "csrf_token": token,
                "tipo_evidencia": "LISTA_ASISTENCIA",
                "evidencia": (BytesIO(b"x"), "asistencia.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(created.status_code, 302)
        self.assertEqual(PersonalCapacitacionEvidencia.query.filter_by(capacitacion_id=item.id).count(), 1)
        self.assertEqual(len(list(Path(self.temp_directory.name).rglob("*.pdf"))), 1)

    def test_rejects_evidence_participant_from_another_training(self):
        item = create_capacitacion(self.user(), self.capacitacion_data())
        other = create_capacitacion(self.user(), {**self.capacitacion_data(), "codigo": "CAP-002"})
        db.session.flush()
        participante = add_capacitacion_participante(self.user(), other, self.second_person.id, {})
        db.session.flush()

        with self.assertRaises(PersonalError):
            add_capacitacion_evidencia(
                self.user(),
                item,
                self.evidence_file(),
                {"tipo_evidencia": "CERTIFICADO", "participante_id": str(participante.id)},
            )

    def test_basic_4a_and_4b_regression_relationships(self):
        calificacion = create_calificacion(self.user(), self.person.id, self.calificacion_data())
        experiencia = create_experiencia(self.user(), self.person.id, self.experiencia_data())
        capacitacion = create_capacitacion(self.user(), self.capacitacion_data())
        db.session.flush()
        participante = add_capacitacion_participante(self.user(), capacitacion, self.person.id, {})
        db.session.commit()

        person = db.session.get(Personal, self.person.id)
        self.assertIsInstance(db.session.get(Cargo, person.cargo_id), Cargo)
        self.assertEqual(person.calificaciones[0].id, calificacion.id)
        self.assertEqual(person.experiencias[0].id, experiencia.id)
        self.assertEqual(person.capacitaciones_participacion[0].id, participante.id)
        self.assertEqual(PersonalCalificacion.query.filter_by(empresa_id=102).count(), 0)
        self.assertEqual(PersonalExperiencia.query.filter_by(empresa_id=102).count(), 0)
        self.assertEqual(PersonalCapacitacionParticipante.query.filter_by(empresa_id=102).count(), 0)


if __name__ == "__main__":
    unittest.main()
