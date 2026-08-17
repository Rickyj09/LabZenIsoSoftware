import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.empresa import Empresa
from app.models.equipos import (
    AreaAmbiente,
    AreaCondicionAmbiental,
    AreaHistorialAmbiental,
    AreaMedicionAmbiental,
    Instalacion,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services import area_condicion_ambiental_service as ambient_service
from app.services.area_condicion_ambiental_service import CondicionAmbientalError


EQUIPAMIENTO_PERMISSIONS = (
    "equipos.ver",
    "equipos.editar",
)


class Equipamiento5DCondicionesAmbientalesTest(unittest.TestCase):
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
        self._seed_data()
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def _seed_data(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="calidad@amb", username="calidad-amb", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@amb", username="consulta-amb", password_hash="x", activo=True),
            Usuario(id=205, empresa_id=102, nombre="Calidad", apellido="Dos", email="calidad2@amb", username="calidad2-amb", password_hash="x", activo=True),
        ])
        permissions = {}
        for offset, code in enumerate(EQUIPAMIENTO_PERMISSIONS, start=1):
            permission = Permiso(id=1000 + offset, codigo=code, nombre=code, modulo="equipamiento")
            db.session.add(permission)
            permissions[code] = permission
        manager = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        reader = Rol(id=2002, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([manager, reader])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=manager.id, permiso_id=permissions["equipos.ver"].id),
            RolPermiso(id=3002, rol_id=manager.id, permiso_id=permissions["equipos.editar"].id),
            RolPermiso(id=3003, rol_id=reader.id, permiso_id=permissions["equipos.ver"].id),
            UsuarioRol(id=4001, usuario_id=201, rol_id=manager.id),
            UsuarioRol(id=4002, usuario_id=202, rol_id=reader.id),
            UsuarioRol(id=4003, usuario_id=205, rol_id=manager.id),
        ])
        db.session.add_all([
            Instalacion(id=301, empresa_id=101, codigo="LAB-1", nombre="Laboratorio uno", estado="activo"),
            Instalacion(id=302, empresa_id=102, codigo="LAB-2", nombre="Laboratorio dos", estado="activo"),
            AreaAmbiente(
                id=401,
                empresa_id=101,
                instalacion_id=301,
                codigo="AREA-TEST-001",
                nombre="LABORATORIO PRUEBA EQUIPOS",
                requiere_control_ambiental=True,
                estado="activo",
            ),
            AreaAmbiente(
                id=402,
                empresa_id=101,
                instalacion_id=301,
                codigo="AREA-SIN-CONTROL",
                nombre="Bodega",
                requiere_control_ambiental=False,
                estado="activo",
            ),
            AreaAmbiente(
                id=403,
                empresa_id=101,
                instalacion_id=301,
                codigo="AREA-INACTIVA",
                nombre="Area inactiva",
                requiere_control_ambiental=True,
                estado="inactivo",
            ),
            AreaAmbiente(
                id=405,
                empresa_id=101,
                instalacion_id=301,
                codigo="AREA-CONTROL-2",
                nombre="Laboratorio secundario",
                requiere_control_ambiental=True,
                estado="activo",
            ),
            AreaAmbiente(
                id=404,
                empresa_id=102,
                instalacion_id=302,
                codigo="AREA-OTRA",
                nombre="Laboratorio externo",
                requiere_control_ambiental=True,
                estado="activo",
            ),
        ])

    def user(self, user_id=201):
        return db.session.get(Usuario, user_id)

    def create_temperature(self, **overrides):
        data = {
            "codigo": "TEMPERATURA",
            "nombre": "Temperatura ambiente",
            "unidad": "°C",
            "limite_minimo": "20",
            "limite_maximo": "25",
        }
        data.update(overrides)
        return ambient_service.crear_condicion(self.user(), 401, data)

    def test_model_schema_supports_configurable_environmental_conditions(self):
        inspector = inspect(db.engine)
        self.assertIn("area_condiciones_ambientales", inspector.get_table_names())
        self.assertIn("area_mediciones_ambientales", inspector.get_table_names())
        self.assertIn("area_historial_ambiental", inspector.get_table_names())
        condition_columns = {column["name"] for column in inspector.get_columns("area_condiciones_ambientales")}
        measurement_columns = {column["name"] for column in inspector.get_columns("area_mediciones_ambientales")}
        self.assertTrue({"codigo", "nombre", "unidad", "limite_minimo", "limite_maximo", "valor_referencia", "activa"}.issubset(condition_columns))
        self.assertTrue({"fecha_hora_medicion", "valor", "estado", "limite_minimo_aplicado", "limite_maximo_aplicado", "unidad_aplicada"}.issubset(measurement_columns))

    def test_creates_temperature_and_humidity_only_for_controlled_active_area(self):
        temperature = self.create_temperature()
        humidity = ambient_service.crear_condicion(self.user(), 401, {
            "codigo": "HUMEDAD_RELATIVA",
            "nombre": "Humedad relativa",
            "unidad": "%",
            "limite_minimo": "40",
            "limite_maximo": "60",
        })
        db.session.commit()

        self.assertEqual(temperature.area_ambiente_id, 401)
        self.assertEqual(humidity.codigo, "HUMEDAD_RELATIVA")
        self.assertEqual(str(temperature.limite_minimo), "20.0000")
        self.assertEqual(AreaHistorialAmbiental.query.filter_by(tipo_evento="CONDICION_AMBIENTAL_CREADA").count(), 2)
        with self.assertRaisesRegex(CondicionAmbientalError, "control ambiental"):
            ambient_service.crear_condicion(self.user(), 402, {
                "codigo": "TEMPERATURA",
                "nombre": "Temperatura",
                "unidad": "°C",
                "limite_minimo": "20",
            })
        with self.assertRaisesRegex(CondicionAmbientalError, "activo"):
            ambient_service.crear_condicion(self.user(), 403, {
                "codigo": "TEMPERATURA",
                "nombre": "Temperatura",
                "unidad": "°C",
                "limite_minimo": "20",
            })

    def test_rejects_invalid_limits_missing_limits_and_other_company_area(self):
        with self.assertRaisesRegex(CondicionAmbientalError, "mayor"):
            self.create_temperature(limite_minimo="25.1", limite_maximo="20")
        with self.assertRaisesRegex(CondicionAmbientalError, "al menos un limite"):
            self.create_temperature(codigo="SIN_LIMITES", limite_minimo="", limite_maximo="")
        with self.assertRaisesRegex(CondicionAmbientalError, "no pertenece"):
            ambient_service.crear_condicion(self.user(), 404, {
                "codigo": "TEMPERATURA",
                "nombre": "Temperatura",
                "unidad": "°C",
                "limite_minimo": "20",
            })

    def test_registers_conforming_measurement_and_inclusive_limits(self):
        condition = self.create_temperature()
        db.session.commit()

        normal = ambient_service.registrar_medicion(self.user(), 401, condition.id, {
            "valor": "23",
            "fecha_hora_medicion": datetime(2026, 8, 17, 8, 30, tzinfo=timezone.utc),
        })
        lower = ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "20"})
        upper = ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "25"})

        self.assertEqual(normal.estado, "CONFORME")
        self.assertEqual(lower.estado, "CONFORME")
        self.assertEqual(upper.estado, "CONFORME")
        self.assertEqual(str(normal.limite_minimo_aplicado), "20.0000")
        self.assertEqual(normal.unidad_aplicada, "°C")

    def test_registers_out_of_limit_lower_and_upper_measurements(self):
        condition = self.create_temperature()
        db.session.commit()

        lower = ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "19.9"})
        upper = ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "25.1"})

        self.assertEqual(lower.estado, "FUERA_DE_LIMITE")
        self.assertEqual(upper.estado, "FUERA_DE_LIMITE")
        self.assertEqual(ambient_service.mediciones_fuera_de_limite(self.user(), 401), [upper, lower])
        descriptions = [event.descripcion for event in AreaHistorialAmbiental.query.filter_by(tipo_evento="MEDICION_AMBIENTAL_FUERA_DE_LIMITE").all()]
        self.assertTrue(any("19.9" in description and "FUERA_DE_LIMITE" in description for description in descriptions))

    def test_supports_unilateral_minimum_and_maximum_limits(self):
        minimum = self.create_temperature(codigo="PRESION_MIN", nombre="Presion minima", unidad="hPa", limite_minimo="1010", limite_maximo="")
        maximum = self.create_temperature(codigo="PARTICULAS", nombre="Particulas", unidad="ppm", limite_minimo="", limite_maximo="10")
        db.session.commit()

        self.assertEqual(ambient_service.registrar_medicion(self.user(), 401, minimum.id, {"valor": "1010"}).estado, "CONFORME")
        self.assertEqual(ambient_service.registrar_medicion(self.user(), 401, minimum.id, {"valor": "1009.99"}).estado, "FUERA_DE_LIMITE")
        self.assertEqual(ambient_service.registrar_medicion(self.user(), 401, maximum.id, {"valor": "10"}).estado, "CONFORME")
        self.assertEqual(ambient_service.registrar_medicion(self.user(), 401, maximum.id, {"valor": "10.01"}).estado, "FUERA_DE_LIMITE")

    def test_rejects_inactive_condition_wrong_area_and_cross_company_measurement(self):
        condition = self.create_temperature()
        humidity = ambient_service.crear_condicion(self.user(), 401, {
            "codigo": "HUMEDAD_RELATIVA",
            "nombre": "Humedad relativa",
            "unidad": "%",
            "limite_minimo": "40",
            "limite_maximo": "60",
        })
        other_company_condition = ambient_service.crear_condicion(self.user(205), 404, {
            "codigo": "TEMPERATURA",
            "nombre": "Temperatura",
            "unidad": "°C",
            "limite_minimo": "20",
        })
        db.session.commit()

        ambient_service.inactivar_condicion(self.user(), condition.id, "Fuera de uso")
        with self.assertRaisesRegex(CondicionAmbientalError, "inactiva"):
            ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "23"})
        with self.assertRaisesRegex(CondicionAmbientalError, "no pertenece al area"):
            ambient_service.registrar_medicion(self.user(), 405, humidity.id, {"valor": "50"})
        with self.assertRaisesRegex(CondicionAmbientalError, "no pertenece"):
            ambient_service.registrar_medicion(self.user(), 401, other_company_condition.id, {"valor": "23"})

    def test_historical_measurement_keeps_original_evaluation_after_limit_change(self):
        condition = self.create_temperature()
        db.session.commit()

        measurement = ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "24.5"})
        ambient_service.actualizar_condicion(self.user(), condition.id, {"limite_minimo": "20", "limite_maximo": "24"})
        db.session.commit()

        persisted = db.session.get(AreaMedicionAmbiental, measurement.id)
        self.assertEqual(persisted.estado, "CONFORME")
        self.assertEqual(str(persisted.limite_maximo_aplicado), "25.0000")
        self.assertEqual(str(condition.limite_maximo), "24.0000")

    def test_queries_are_company_scoped_and_return_active_conditions_area_measurements_and_outliers(self):
        condition = self.create_temperature()
        inactive = ambient_service.crear_condicion(self.user(), 401, {
            "codigo": "HUMEDAD_RELATIVA",
            "nombre": "Humedad relativa",
            "unidad": "%",
            "limite_minimo": "40",
            "limite_maximo": "60",
        })
        other_company_condition = ambient_service.crear_condicion(self.user(205), 404, {
            "codigo": "TEMPERATURA",
            "nombre": "Temperatura",
            "unidad": "°C",
            "limite_minimo": "20",
        })
        db.session.commit()
        ambient_service.inactivar_condicion(self.user(), inactive.id)
        ok = ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "23"})
        outlier = ambient_service.registrar_medicion(self.user(), 401, condition.id, {"valor": "27"})
        other = ambient_service.registrar_medicion(self.user(205), 404, other_company_condition.id, {"valor": "19"})
        db.session.commit()

        self.assertEqual(ambient_service.condiciones_activas_area(self.user(), 401), [condition])
        self.assertEqual(ambient_service.mediciones_area(self.user(), 401), [outlier, ok])
        self.assertEqual(ambient_service.mediciones_fuera_de_limite(self.user()), [outlier])
        self.assertEqual(ambient_service.mediciones_fuera_de_limite(self.user(205)), [other])
        with self.assertRaisesRegex(CondicionAmbientalError, "no pertenece"):
            ambient_service.condiciones_area(self.user(), 404)

    def test_read_only_user_cannot_create_but_can_query(self):
        condition = self.create_temperature()
        db.session.commit()

        self.assertEqual(ambient_service.condiciones_area(self.user(202), 401), [condition])
        with self.assertRaisesRegex(CondicionAmbientalError, "permisos"):
            ambient_service.registrar_medicion(self.user(202), 401, condition.id, {"valor": "23"})


if __name__ == "__main__":
    unittest.main()
