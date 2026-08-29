import tempfile
import unittest

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.empresa import Empresa
from app.models.organigrama import Cargo, PerfilPuesto, Personal
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.security.permissions import user_has_permission
from app.services.personal_service import (
    PersonalError,
    create_cargo,
    create_personal,
    set_cargo_active,
    set_personal_status,
    update_personal,
    upsert_perfil,
)


PERSONAL_PERMISSIONS = ("personal.ver", "personal.gestionar")


class Personal4ATest(unittest.TestCase):
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
        self.next_id = 10000

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
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@per", username="admin-per", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@per", username="consulta-per", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@per", username="admin2-per", password_hash="x", activo=True),
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
            UsuarioRol(id=4003, usuario_id=203, rol_id=manager.id),
        ])

    def login(self, user_id=201):
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

    def cargo_data(self, code="DT"):
        return {
            "codigo": code,
            "nombre": "Director Tecnico",
            "descripcion": "Responsable tecnico",
            "activo": "1",
            "proposito": "Dirigir la operacion tecnica.",
            "funciones": "Supervisar metodos.",
            "responsabilidades": "Asegurar resultados validos.",
            "autoridad": "Aprobar decisiones tecnicas.",
        }

    def create_basic_cargo(self, user_id=201, code="DT"):
        cargo = create_cargo(self.user(user_id), self.cargo_data(code))
        db.session.flush()
        upsert_perfil(self.user(user_id), cargo, self.cargo_data(code))
        db.session.commit()
        return cargo

    def personal_data(self, cargo, code="PER-001", user_id=""):
        return {
            "codigo": code,
            "nombres": "Ana",
            "apellidos": "Calidad",
            "identificacion": f"ID-{code}",
            "email": "ana@lab.test",
            "telefono": "0999999999",
            "cargo_id": str(cargo.id),
            "usuario_id": str(user_id) if user_id else "",
            "fecha_ingreso": "2026-01-15",
            "fecha_salida": "",
            "estado": "ACTIVO",
            "observaciones": "Registro inicial",
        }

    def test_creates_cargo_and_profile(self):
        cargo = self.create_basic_cargo()

        self.assertEqual(cargo.empresa_id, 101)
        self.assertTrue(cargo.activo)
        self.assertEqual(cargo.perfil.proposito, "Dirigir la operacion tecnica.")

    def test_creates_and_edits_personal(self):
        cargo = self.create_basic_cargo()
        person = create_personal(self.user(), self.personal_data(cargo, user_id=201))
        db.session.commit()

        update = self.personal_data(cargo, code="PER-001", user_id=201)
        update["apellidos"] = "Actualizada"
        update["fecha_salida"] = "2026-12-31"
        update_personal(self.user(), person, update)
        db.session.commit()

        self.assertEqual(person.empresa_id, 101)
        self.assertEqual(person.usuario_id, 201)
        self.assertEqual(person.nombre_completo, "Ana Actualizada")
        self.assertEqual(person.fecha_salida.isoformat(), "2026-12-31")

    def test_personal_code_unique_per_company_and_allowed_across_companies(self):
        cargo = self.create_basic_cargo()
        cargo_other = self.create_basic_cargo(user_id=203, code="DT")
        create_personal(self.user(), self.personal_data(cargo, code="PER-001"))
        with self.assertRaises(PersonalError):
            create_personal(self.user(), self.personal_data(cargo, code="PER-001"))

        create_personal(self.user(203), self.personal_data(cargo_other, code="PER-001"))
        db.session.commit()
        self.assertEqual(Personal.query.filter_by(codigo="PER-001").count(), 2)

    def test_cargo_code_unique_per_company(self):
        self.create_basic_cargo(code="AN")
        with self.assertRaises(PersonalError):
            create_cargo(self.user(), {"codigo": "AN", "nombre": "Analista"})

    def test_rejects_other_company_cargo_and_user(self):
        cargo = self.create_basic_cargo()
        other_cargo = self.create_basic_cargo(user_id=203, code="OT")

        with self.assertRaises(PersonalError):
            create_personal(self.user(), self.personal_data(other_cargo, code="PER-X"))

        with self.assertRaises(PersonalError):
            create_personal(self.user(), self.personal_data(cargo, code="PER-Y", user_id=203))

    def test_rejects_exit_date_before_entry_date(self):
        cargo = self.create_basic_cargo()
        data = self.personal_data(cargo)
        data["fecha_salida"] = "2025-12-31"

        with self.assertRaises(PersonalError):
            create_personal(self.user(), data)

    def test_status_changes_preserve_rows(self):
        cargo = self.create_basic_cargo()
        person = create_personal(self.user(), self.personal_data(cargo))
        db.session.commit()

        set_personal_status(self.user(), person, "INACTIVO")
        set_cargo_active(self.user(), cargo, False)
        db.session.commit()

        self.assertEqual(Personal.query.count(), 1)
        self.assertEqual(Cargo.query.count(), 1)
        self.assertEqual(person.estado, "INACTIVO")
        self.assertFalse(cargo.activo)

    def test_direct_url_access_to_other_company_records_returns_404(self):
        other_cargo = self.create_basic_cargo(user_id=203, code="ODT")
        other_person = create_personal(self.user(203), self.personal_data(other_cargo, code="PER-OTRA"))
        db.session.commit()

        client = self.login(201)
        self.assertEqual(client.get(f"/personal/{other_person.id}").status_code, 404)
        self.assertEqual(client.get(f"/personal/cargos/{other_cargo.id}").status_code, 404)

    def test_permissions_allow_read_and_block_manage(self):
        self.assertTrue(user_has_permission(self.user(202), "personal.ver"))
        self.assertFalse(user_has_permission(self.user(202), "personal.gestionar"))

        client = self.login(202)
        self.assertEqual(client.get("/personal/").status_code, 200)
        self.assertEqual(client.get("/personal/nuevo").status_code, 403)

    def test_web_views_create_profile_personal_and_enforce_csrf(self):
        client = self.login(201)
        form = client.get("/personal/cargos/nuevo")
        self.assertEqual(form.status_code, 200)
        token = self.csrf_token(client)

        missing = client.post("/personal/cargos/nuevo", data=self.cargo_data("LAB"))
        self.assertEqual(missing.status_code, 403)

        created = client.post("/personal/cargos/nuevo", data={**self.cargo_data("LAB"), "csrf_token": token})
        self.assertEqual(created.status_code, 302)
        cargo = Cargo.query.filter_by(codigo="LAB", empresa_id=101).one()
        self.assertIsNotNone(cargo.perfil)

        person_form = client.get("/personal/nuevo")
        self.assertEqual(person_form.status_code, 200)
        token = self.csrf_token(client)
        person_payload = self.personal_data(cargo, code="PER-WEB")
        created_person = client.post("/personal/nuevo", data={**person_payload, "csrf_token": token})

        self.assertEqual(created_person.status_code, 302)
        person = Personal.query.filter_by(codigo="PER-WEB", empresa_id=101).one()
        detail = client.get(f"/personal/{person.id}")
        cargos_index = client.get("/personal/cargos")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(cargos_index.status_code, 200)
        self.assertIn("Trazabilidad ISO 17025", detail.get_data(as_text=True))
        self.assertIn("LAB", cargos_index.get_data(as_text=True))

    def test_database_unique_constraint_for_personal_code(self):
        cargo = self.create_basic_cargo()
        db.session.add_all([
            Personal(empresa_id=101, codigo="PER-DB", nombres="Uno", apellidos="A", cargo_id=cargo.id, estado="ACTIVO"),
            Personal(empresa_id=101, codigo="PER-DB", nombres="Dos", apellidos="B", cargo_id=cargo.id, estado="ACTIVO"),
        ])
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_database_relationship_cargo_personal_profile(self):
        cargo = self.create_basic_cargo()
        person = create_personal(self.user(), self.personal_data(cargo))
        db.session.commit()

        self.assertEqual(person.cargo.id, cargo.id)
        self.assertIsInstance(cargo.perfil, PerfilPuesto)
        self.assertEqual(cargo.personal[0].id, person.id)


if __name__ == "__main__":
    unittest.main()
