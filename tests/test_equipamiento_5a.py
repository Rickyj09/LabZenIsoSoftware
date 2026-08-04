import tempfile
import unittest
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import Documento, DocumentoVersion
from app.models.equipos import AreaAmbiente, Equipo, EquipoHistorial, Instalacion
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.security.permissions import user_has_permission
from app.services.equipamiento_service import (
    EquipamientoError,
    change_equipo_status,
    create_area,
    create_equipo,
    create_instalacion,
    equipo_history_change_labels,
    link_document_version,
    update_equipo,
)


EQUIPAMIENTO_PERMISSIONS = (
    "equipamiento.dashboard.ver",
    "instalaciones.ver",
    "instalaciones.crear",
    "instalaciones.editar",
    "instalaciones.inactivar",
    "areas.ver",
    "areas.crear",
    "areas.editar",
    "areas.inactivar",
    "equipos.ver",
    "equipos.crear",
    "equipos.editar",
    "equipos.cambiar_estado",
    "equipos.inactivar",
    "equipos.historial.ver",
    "equipos.documentos.vincular",
    "documentos.ver",
)


class Equipamiento5ATest(unittest.TestCase):
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
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="calidad@eq", username="calidad-eq", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Tecnico", apellido="Uno", email="tecnico@eq", username="tecnico-eq", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@eq", username="consulta-eq", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=102, nombre="Calidad", apellido="Dos", email="calidad2@eq", username="calidad2-eq", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, code in enumerate(EQUIPAMIENTO_PERMISSIONS, start=1):
            permission = Permiso(id=1000 + offset, codigo=code, nombre=code, modulo=code.split(".")[0])
            db.session.add(permission)
            permissions[code] = permission
        quality = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        technical = Rol(id=2002, nombre="TECNICO", es_sistema=True)
        consultation = Rol(id=2003, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([quality, technical, consultation])
        db.session.flush()
        link_id = 3000
        for code in EQUIPAMIENTO_PERMISSIONS:
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=quality.id, permiso_id=permissions[code].id))
        for code in ("equipamiento.dashboard.ver", "instalaciones.ver", "areas.ver", "equipos.ver", "equipos.historial.ver"):
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=consultation.id, permiso_id=permissions[code].id))
        for code in ("equipamiento.dashboard.ver", "instalaciones.ver", "areas.ver", "equipos.ver", "equipos.crear", "equipos.editar", "equipos.cambiar_estado", "equipos.documentos.vincular"):
            link_id += 1
            db.session.add(RolPermiso(id=link_id, rol_id=technical.id, permiso_id=permissions[code].id))
        db.session.add_all([
            UsuarioRol(id=4001, usuario_id=201, rol_id=quality.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=technical.id),
            UsuarioRol(id=4003, usuario_id=203, rol_id=consultation.id),
            UsuarioRol(id=4004, usuario_id=204, rol_id=quality.id),
        ])

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def user(self, user_id=201):
        return db.session.get(Usuario, user_id)

    def create_basic_location(self, user_id=201, code_suffix=""):
        user = self.user(user_id)
        installation = create_instalacion(user, {"codigo": f"LAB{code_suffix}", "nombre": f"Lab {code_suffix}", "estado": "activo"})
        db.session.flush()
        area = create_area(user, {
            "instalacion_id": installation.id,
            "codigo": f"AREA{code_suffix}",
            "nombre": f"Area {code_suffix}",
            "tipo": "Laboratorio",
            "estado": "activo",
        })
        db.session.commit()
        return installation, area

    def equipo_data(self, installation, area, code="EQ-001"):
        return {
            "codigo": code,
            "nombre": "Balanza analitica",
            "tipo": "Balanza",
            "marca": "Mettler",
            "modelo": "XPR",
            "serie": "SN-001",
            "fabricante": "Mettler Toledo",
            "instalacion_id": str(installation.id),
            "area_ambiente_id": str(area.id),
            "ubicacion_especifica": "Mesa 1",
            "responsable": "Ana Calidad",
            "estado": "activo",
            "estado_operativo": "OPERATIVO",
            "criticidad": "ALTA",
            "requiere_calibracion": "1",
            "requiere_mantenimiento": "1",
        }

    def test_creates_installation_and_enforces_code_unique_per_company(self):
        user = self.user()
        item = create_instalacion(user, {"codigo": "LAB-01", "nombre": "Principal"})
        db.session.commit()

        self.assertEqual(item.empresa_id, 101)
        with self.assertRaises(EquipamientoError):
            create_instalacion(user, {"codigo": "LAB-01", "nombre": "Duplicada"})

    def test_allows_repeated_installation_code_in_different_companies(self):
        create_instalacion(self.user(201), {"codigo": "LAB-01", "nombre": "Empresa uno"})
        create_instalacion(self.user(204), {"codigo": "LAB-01", "nombre": "Empresa dos"})
        db.session.commit()

        self.assertEqual(Instalacion.query.filter_by(codigo="LAB-01").count(), 2)

    def test_creates_area_and_validates_installation_company(self):
        installation, _ = self.create_basic_location()
        other_installation = create_instalacion(self.user(204), {"codigo": "LAB2", "nombre": "Otra empresa"})
        db.session.commit()

        area = create_area(self.user(), {"instalacion_id": installation.id, "codigo": "MICRO", "nombre": "Microbiologia"})
        self.assertEqual(area.empresa_id, 101)
        with self.assertRaises(EquipamientoError):
            create_area(self.user(), {"instalacion_id": other_installation.id, "codigo": "CRUZ", "nombre": "Cruzada"})

    def test_creates_and_edits_equipment_with_history(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        db.session.commit()

        update_data = self.equipo_data(installation, area)
        update_data["responsable"] = "Nuevo custodio"
        update_data["ubicacion_especifica"] = "Mesa 2"
        update_data["estado_operativo"] = "FUERA_DE_SERVICIO"
        update_equipo(self.user(), equipment, update_data)
        db.session.commit()

        events = [event.tipo_evento for event in EquipoHistorial.query.filter_by(equipo_id=equipment.id).all()]
        self.assertIn("CREACION", events)
        self.assertIn("ACTUALIZACION", events)
        self.assertIn("CAMBIO_UBICACION", events)
        self.assertIn("CAMBIO_RESPONSABLE", events)
        self.assertIn("CAMBIO_ESTADO_OPERATIVO", events)

    def test_location_history_stores_readable_values_and_preserves_previous_and_new_values(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        db.session.commit()

        update_data = self.equipo_data(installation, area)
        update_data["ubicacion_especifica"] = "Mesa 2"
        update_equipo(self.user(), equipment, update_data)
        db.session.commit()

        event = EquipoHistorial.query.filter_by(
            equipo_id=equipment.id,
            tipo_evento="CAMBIO_UBICACION",
        ).one()
        previous, current = equipo_history_change_labels(event)

        self.assertIn("Mesa 1", previous)
        self.assertIn("Mesa 2", current)
        self.assertNotIn(f"{installation.id}:{area.id}:", previous)
        self.assertNotIn(f"{installation.id}:{area.id}:", current)

    def test_location_history_renders_legacy_serialized_location_cleanly(self):
        event = EquipoHistorial(
            empresa_id=101,
            equipo_id=999,
            tipo_evento="CAMBIO_UBICACION",
            estado_anterior="2:4:Mesa de balanzas 1",
            estado_nuevo="2:4:Mesa de balanzas 2",
        )

        previous, current = equipo_history_change_labels(event)

        self.assertEqual(previous, "Mesa de balanzas 1")
        self.assertEqual(current, "Mesa de balanzas 2")

    def test_detail_route_renders_persisted_legacy_location_history_cleanly(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area, code="EQ-PRUEBA-01"))
        db.session.flush()
        event = EquipoHistorial(
            empresa_id=101,
            equipo_id=equipment.id,
            tipo_evento="CAMBIO_UBICACION",
            descripcion="Ubicacion del equipo actualizada.",
            estado_anterior="2:4:Mesa de balanzas 1",
            estado_nuevo="2:4:Mesa de balanzas 2",
            usuario_id=201,
            created_at=datetime(2026, 8, 4, 12, 56),
        )
        db.session.add(event)
        db.session.commit()

        response = self.login(201).get(f"/equipamiento/equipos/{equipment.id}")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Mesa de balanzas 1", body)
        self.assertIn("Mesa de balanzas 2", body)
        self.assertNotIn("2:4:Mesa", body)
        self.assertIn("CAMBIO UBICACION", body)
        self.assertIn("2026-08-04 12:56", body)
        self.assertIn("Calidad", body)

    def test_equipment_code_unique_per_company_and_repeat_allowed_between_companies(self):
        installation, area = self.create_basic_location()
        create_equipo(self.user(), self.equipo_data(installation, area, code="EQ-001"))
        with self.assertRaises(EquipamientoError):
            create_equipo(self.user(), self.equipo_data(installation, area, code="EQ-001"))

        installation2, area2 = self.create_basic_location(user_id=204, code_suffix="2")
        create_equipo(self.user(204), self.equipo_data(installation2, area2, code="EQ-001"))
        db.session.commit()
        self.assertEqual(Equipo.query.filter_by(codigo="EQ-001").count(), 2)

    def test_validates_equipment_area_matches_installation_and_company(self):
        installation, area = self.create_basic_location()
        other_installation = create_instalacion(self.user(), {"codigo": "LAB-X", "nombre": "Otra instalacion"})
        db.session.commit()

        bad_data = self.equipo_data(other_installation, area)
        with self.assertRaises(EquipamientoError):
            create_equipo(self.user(), bad_data)

    def test_changes_operational_status_and_records_history(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        change_equipo_status(self.user(), equipment, "RETIRADO", "Fin de vida util")
        db.session.commit()

        self.assertEqual(equipment.estado_operativo, "RETIRADO")
        self.assertTrue(EquipoHistorial.query.filter_by(equipo_id=equipment.id, tipo_evento="RETIRO").first())

    def test_listing_filters_and_dashboard_are_company_scoped(self):
        installation, area = self.create_basic_location()
        create_equipo(self.user(), self.equipo_data(installation, area, code="EQ-FILTRO"))
        installation2, area2 = self.create_basic_location(user_id=204, code_suffix="2")
        create_equipo(self.user(204), self.equipo_data(installation2, area2, code="EQ-OTRA"))
        db.session.commit()

        client = self.login(201)
        body = client.get("/equipamiento/equipos?q=FILTRO").get_data(as_text=True)
        dashboard = client.get("/equipamiento/").get_data(as_text=True)

        self.assertIn("EQ-FILTRO", body)
        self.assertNotIn("EQ-OTRA", body)
        self.assertIn("Equipos activos", dashboard)
        self.assertIn(">1<", dashboard)

    def test_permissions_allow_read_and_block_missing_create_permission(self):
        self.assertTrue(user_has_permission(self.user(203), "equipos.ver"))
        self.assertFalse(user_has_permission(self.user(203), "equipos.crear"))

        client = self.login(203)
        self.assertEqual(client.get("/equipamiento/equipos").status_code, 200)
        self.assertEqual(client.get("/equipamiento/equipos/nuevo").status_code, 403)

    def test_direct_url_access_to_other_company_records_returns_404(self):
        installation2, area2 = self.create_basic_location(user_id=204, code_suffix="2")
        equipment2 = create_equipo(self.user(204), self.equipo_data(installation2, area2, code="EQ-OTRA"))
        db.session.commit()

        self.assertEqual(self.login(201).get(f"/equipamiento/equipos/{equipment2.id}").status_code, 404)

    def test_links_existing_document_version_without_copying_file(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        document = Documento(
            empresa_id=101,
            codigo="DOC-EQ",
            titulo="Manual de equipo",
            tipo_documento="MANUAL",
            estado="APROBADO",
            version_actual="1",
            elaborado_por_id=201,
        )
        db.session.add(document)
        db.session.flush()
        version = DocumentoVersion(
            empresa_id=101,
            documento_id=document.id,
            version="1",
            estado="APROBADO",
            elaborado_por_id=201,
            archivo_storage_path="empresa_101/documento/manual.docx",
        )
        db.session.add(version)
        db.session.flush()

        link = link_document_version(self.user(), equipment, version.id, "MANUAL", "Manual vigente")
        db.session.commit()

        self.assertEqual(link.documento_version_id, version.id)
        self.assertIsNone(link.archivo_url)
        self.assertTrue(EquipoHistorial.query.filter_by(equipo_id=equipment.id, tipo_evento="VINCULO_DOCUMENTO").first())

    def add_document_version(self, document_id=501, code="DOC-EQ", title="Manual de equipo"):
        document = Documento(
            id=document_id,
            empresa_id=101,
            codigo=code,
            titulo=title,
            tipo_documento="MANUAL",
            estado="APROBADO",
            version_actual="1",
            elaborado_por_id=201,
        )
        version = DocumentoVersion(
            id=document_id + 1000,
            empresa_id=101,
            documento_id=document_id,
            version="1",
            estado="APROBADO",
            elaborado_por_id=201,
        )
        db.session.add_all([document, version])
        db.session.commit()
        return document, version

    def test_document_link_form_renders_filter_and_available_versions(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        _document, version = self.add_document_version(title="Manual visible")

        response = self.login(201).get(f"/equipamiento/equipos/{equipment.id}")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Buscar documento", body)
        self.assertIn("data-document-version-filter", body)
        self.assertIn("name=\"documento_version_id\"", body)
        self.assertIn(f"value=\"{version.id}\"", body)
        self.assertIn("DOC-EQ v1 - Manual visible", body)

    def test_technician_document_link_form_renders_filter_and_available_versions(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        _document, version = self.add_document_version(title="Manual tecnico")

        response = self.login(202).get(f"/equipamiento/equipos/{equipment.id}")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Buscar documento", body)
        self.assertIn("id=\"document-version-filter\"", body)
        self.assertIn("data-document-version-select", body)
        self.assertIn(f"value=\"{version.id}\"", body)
        self.assertIn("DOC-EQ v1 - Manual tecnico", body)

    def test_document_link_post_still_links_after_selector_improvement(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        _document, version = self.add_document_version()

        response = self.login(201).post(
            f"/equipamiento/equipos/{equipment.id}/documentos",
            data={
                "documento_version_id": str(version.id),
                "tipo_documento": "MANUAL",
                "observaciones": "Manual vigente",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(equipment.documentos[0].documento_version_id, version.id)

    def test_consultation_user_cannot_render_or_post_document_link_form(self):
        installation, area = self.create_basic_location()
        equipment = create_equipo(self.user(), self.equipo_data(installation, area))
        _document, version = self.add_document_version()
        client = self.login(203)

        detail = client.get(f"/equipamiento/equipos/{equipment.id}")
        body = detail.get_data(as_text=True)
        post = client.post(
            f"/equipamiento/equipos/{equipment.id}/documentos",
            data={"documento_version_id": str(version.id), "tipo_documento": "MANUAL"},
        )

        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("Buscar documento", body)
        self.assertEqual(post.status_code, 403)

    def test_equipment_role_permissions_remain_expected(self):
        admin = self.user(201)
        technician = self.user(202)
        consultation = self.user(203)

        self.assertTrue(user_has_permission(admin, "equipos.documentos.vincular"))
        self.assertTrue(user_has_permission(admin, "equipos.cambiar_estado"))
        self.assertTrue(user_has_permission(technician, "equipos.documentos.vincular"))
        self.assertTrue(user_has_permission(technician, "equipos.cambiar_estado"))
        self.assertTrue(user_has_permission(consultation, "equipos.ver"))
        self.assertTrue(user_has_permission(consultation, "equipos.historial.ver"))
        self.assertFalse(user_has_permission(consultation, "equipos.documentos.vincular"))
        self.assertFalse(user_has_permission(consultation, "equipos.cambiar_estado"))
        self.assertFalse(user_has_permission(consultation, "equipos.editar"))

    def test_document_module_regression_basic_view_still_loads(self):
        response = self.login(201).get("/documentacion/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Gesti", response.get_data(as_text=True))

    def test_database_unique_constraint_for_equipment_code(self):
        installation, area = self.create_basic_location()
        db.session.add_all([
            Equipo(empresa_id=101, codigo="EQ-DB", nombre="Uno", instalacion_id=installation.id, area_ambiente_id=area.id, estado_operativo="OPERATIVO"),
            Equipo(empresa_id=101, codigo="EQ-DB", nombre="Dos", instalacion_id=installation.id, area_ambiente_id=area.id, estado_operativo="OPERATIVO"),
        ])
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()


if __name__ == "__main__":
    unittest.main()
