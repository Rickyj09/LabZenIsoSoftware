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
from app.models.organigrama import Cargo, Personal, PersonalCalificacion, PersonalExperiencia
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.personal_service import (
    PersonalError,
    add_calificacion_evidencia,
    cerrar_experiencia_actual,
    create_calificacion,
    create_cargo,
    create_experiencia,
    create_personal,
    update_calificacion,
    update_experiencia,
)
from app.services.storage_service import resolve_document_path


PERSONAL_PERMISSIONS = ("personal.ver", "personal.gestionar")


class Personal4BTest(unittest.TestCase):
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
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@per4b", username="admin-per4b", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@per4b", username="consulta-per4b", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin@per4b", username="sin-per4b", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@per4b", username="admin2-per4b", password_hash="x", activo=True),
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

    def calificacion_data(self):
        return {
            "tipo": "EDUCACION_FORMAL",
            "institucion": "Universidad Central",
            "titulo": "Ingenieria Quimica",
            "area_especialidad": "Quimica analitica",
            "fecha_inicio": "2018-01-01",
            "fecha_fin": "2022-12-20",
            "numero_registro": "REG-001",
            "observaciones": "Titulo verificado",
            "activo": "1",
        }

    def experiencia_data(self):
        return {
            "organizacion": "Laboratorio Alfa",
            "cargo_funcion": "Analista",
            "area_especialidad": "Fisicoquimica",
            "descripcion_actividades": "Ensayos rutinarios",
            "fecha_inicio": "2023-01-01",
            "fecha_fin": "",
            "experiencia_actual": "1",
            "observaciones": "Experiencia relevante",
            "activo": "1",
        }

    @staticmethod
    def evidence_file(name="titulo.pdf", content=b"evidencia"):
        return FileStorage(stream=BytesIO(content), filename=name, content_type="application/pdf")

    def test_creates_and_edits_calificacion(self):
        calificacion = create_calificacion(self.user(), self.person.id, self.calificacion_data())
        db.session.commit()

        data = self.calificacion_data()
        data["titulo"] = "Magister en Quimica"
        update_calificacion(self.user(), calificacion, data)
        db.session.commit()

        self.assertEqual(calificacion.empresa_id, 101)
        self.assertEqual(calificacion.personal_id, self.person.id)
        self.assertEqual(calificacion.titulo, "Magister en Quimica")

    def test_lists_calificaciones_in_person_detail(self):
        create_calificacion(self.user(), self.person.id, self.calificacion_data())
        db.session.commit()

        response = self.login().get(f"/personal/{self.person.id}")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Calificaciones / formacion", body)
        self.assertIn("Ingenieria Quimica", body)

    def test_creates_edits_and_closes_current_experience(self):
        experiencia = create_experiencia(self.user(), self.person.id, self.experiencia_data())
        db.session.commit()

        self.assertTrue(experiencia.experiencia_actual)
        self.assertIsNone(experiencia.fecha_fin)

        data = self.experiencia_data()
        data["cargo_funcion"] = "Analista senior"
        update_experiencia(self.user(), experiencia, data)
        cerrar_experiencia_actual(self.user(), experiencia, "2026-08-01")
        db.session.commit()

        self.assertEqual(experiencia.cargo_funcion, "Analista senior")
        self.assertFalse(experiencia.experiencia_actual)
        self.assertEqual(experiencia.fecha_fin.isoformat(), "2026-08-01")

    def test_rejects_invalid_dates_for_calificacion_and_experiencia(self):
        bad_calificacion = self.calificacion_data()
        bad_calificacion["fecha_fin"] = "2017-12-31"
        with self.assertRaises(PersonalError):
            create_calificacion(self.user(), self.person.id, bad_calificacion)

        bad_experiencia = self.experiencia_data()
        bad_experiencia["fecha_fin"] = "2022-12-31"
        bad_experiencia["experiencia_actual"] = ""
        with self.assertRaises(PersonalError):
            create_experiencia(self.user(), self.person.id, bad_experiencia)

    def test_rejects_cross_company_calificacion_and_experience(self):
        with self.assertRaises(PersonalError):
            create_calificacion(self.user(), self.other_person.id, self.calificacion_data())
        with self.assertRaises(PersonalError):
            create_experiencia(self.user(), self.other_person.id, self.experiencia_data())

    def test_direct_url_access_to_other_company_records_returns_404(self):
        other_calificacion = create_calificacion(self.user(204), self.other_person.id, self.calificacion_data())
        other_experiencia = create_experiencia(self.user(204), self.other_person.id, self.experiencia_data())
        db.session.commit()

        client = self.login(201)
        self.assertEqual(client.get(f"/personal/calificaciones/{other_calificacion.id}/editar").status_code, 404)
        self.assertEqual(client.get(f"/personal/experiencias/{other_experiencia.id}/editar").status_code, 404)

    def test_http_read_manage_permissions_and_csrf(self):
        viewer = self.login(202)
        self.assertEqual(viewer.get(f"/personal/{self.person.id}").status_code, 200)
        self.assertEqual(viewer.get(f"/personal/{self.person.id}/calificaciones/nueva").status_code, 403)

        no_permission = self.login(203)
        self.assertEqual(no_permission.get(f"/personal/{self.person.id}").status_code, 403)

        manager = self.login(201)
        form = manager.get(f"/personal/{self.person.id}/calificaciones/nueva")
        self.assertEqual(form.status_code, 200)
        missing = manager.post(f"/personal/{self.person.id}/calificaciones/nueva", data=self.calificacion_data())
        self.assertEqual(missing.status_code, 403)

        token = self.csrf_token(manager)
        created = manager.post(
            f"/personal/{self.person.id}/calificaciones/nueva",
            data={**self.calificacion_data(), "csrf_token": token},
        )
        self.assertEqual(created.status_code, 302)

    def test_http_experience_routes_and_person_detail_regression(self):
        client = self.login(201)
        form = client.get(f"/personal/{self.person.id}/experiencias/nueva")
        self.assertEqual(form.status_code, 200)
        token = self.csrf_token(client)

        created = client.post(
            f"/personal/{self.person.id}/experiencias/nueva",
            data={**self.experiencia_data(), "csrf_token": token},
        )
        self.assertEqual(created.status_code, 302)
        experiencia = PersonalExperiencia.query.filter_by(personal_id=self.person.id).one()

        detail = client.get(f"/personal/{self.person.id}")
        body = detail.get_data(as_text=True)
        self.assertIn("Datos generales", body)
        self.assertIn("Experiencia", body)
        self.assertIn("Laboratorio Alfa", body)

        token = self.csrf_token(client)
        closed = client.post(
            f"/personal/experiencias/{experiencia.id}/cerrar",
            data={"csrf_token": token, "fecha_fin": "2026-08-01"},
        )
        self.assertEqual(closed.status_code, 302)
        self.assertFalse(db.session.get(PersonalExperiencia, experiencia.id).experiencia_actual)

    def test_evidence_upload_download_and_cross_company_isolation(self):
        calificacion = create_calificacion(self.user(), self.person.id, self.calificacion_data())
        db.session.flush()
        evidencia = add_calificacion_evidencia(self.user(), calificacion, self.evidence_file("../titulo.pdf"))
        db.session.commit()

        self.assertEqual(evidencia.empresa_id, 101)
        self.assertTrue(evidencia.archivo_storage_path.startswith(f"empresa_101/personal_{self.person.id}/calificacion_{calificacion.id}/evidencias/"))
        self.assertTrue(resolve_document_path(evidencia.archivo_storage_path).is_file())
        self.assertNotIn("..", evidencia.archivo_nombre_guardado)

        response = self.login(201).get(f"/personal/evidencias/{evidencia.id}/descargar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"evidencia")
        response.close()

        self.assertEqual(self.login(204).get(f"/personal/evidencias/{evidencia.id}/descargar").status_code, 404)

    def test_http_evidence_upload_requires_csrf(self):
        calificacion = create_calificacion(self.user(), self.person.id, self.calificacion_data())
        db.session.commit()
        client = self.login(201)
        client.get(f"/personal/{self.person.id}")

        missing = client.post(
            f"/personal/calificaciones/{calificacion.id}/evidencias",
            data={"evidencia": (BytesIO(b"x"), "evidencia.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(missing.status_code, 403)

        token = self.csrf_token(client)
        created = client.post(
            f"/personal/calificaciones/{calificacion.id}/evidencias",
            data={"csrf_token": token, "evidencia": (BytesIO(b"x"), "evidencia.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(created.status_code, 302)
        self.assertEqual(len(calificacion.evidencias), 1)
        self.assertEqual(len(list(Path(self.temp_directory.name).rglob("*.pdf"))), 1)

    def test_database_relationships_are_person_scoped(self):
        calificacion = create_calificacion(self.user(), self.person.id, self.calificacion_data())
        experiencia = create_experiencia(self.user(), self.person.id, self.experiencia_data())
        db.session.commit()

        person = db.session.get(Personal, self.person.id)
        self.assertEqual(person.calificaciones[0].id, calificacion.id)
        self.assertEqual(person.experiencias[0].id, experiencia.id)
        self.assertIsInstance(db.session.get(Cargo, person.cargo_id), Cargo)
        self.assertEqual(PersonalCalificacion.query.filter_by(empresa_id=102).count(), 0)


if __name__ == "__main__":
    unittest.main()
