import tempfile
import unittest
from datetime import date

from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import Documento, DocumentoVersion
from app.models.empresa import Empresa
from app.models.equipos import (
    Equipo,
    EquipoHistorial,
    EquipoMantenimiento,
    EquipoMantenimientoDocumento,
    EquipoPlanMantenimiento,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.security.permissions import user_has_permission
from app.services import equipo_mantenimiento_service as maintenance_service
from app.services.equipo_mantenimiento_service import EquipoMantenimientoError
from migrations.versions import f2b3c4d5e6a7_paquete_5b1_mantenimiento_modelos_permisos as migration_5b1


MAINTENANCE_PERMISSIONS = {code for code, _name, _module in migration_5b1.MAINTENANCE_PERMISSIONS}


class Equipamiento5BModelsTest(unittest.TestCase):
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
        self._seed_companies_users_and_equipment()
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def _seed_security(self):
        db.session.add_all([
            Rol(id=2001, nombre="ADMINISTRADOR", es_sistema=True),
            Rol(id=2002, nombre="CALIDAD", es_sistema=True),
            Rol(id=2003, nombre="TECNICO", es_sistema=True),
            Rol(id=2004, nombre="CONSULTA", es_sistema=True),
        ])
        db.session.flush()
        permissions = {}
        for index, (code, name, module) in enumerate(migration_5b1.MAINTENANCE_PERMISSIONS, start=1):
            permission = Permiso(id=1000 + index, codigo=code, nombre=name, descripcion=name, modulo=module)
            permissions[code] = permission
            db.session.add(permission)
        db.session.flush()
        link_id = 5000
        for role in Rol.query.all():
            codes = migration_5b1.ROLE_PERMISSION_CODES[(role.nombre or "").strip().upper()]
            for code in codes:
                link_id += 1
                db.session.add(RolPermiso(id=link_id, rol_id=role.id, permiso_id=permissions[code].id))

    def _seed_companies_users_and_equipment(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@eq", username="admin-eq", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Calidad", apellido="Uno", email="calidad@eq", username="calidad-eq", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Tecnico", apellido="Uno", email="tecnico@eq", username="tecnico-eq", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@eq", username="consulta-eq", password_hash="x", activo=True),
            Usuario(id=205, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@eq", username="admin2-eq", password_hash="x", activo=True),
        ])
        db.session.add_all([
            UsuarioRol(id=3001, usuario_id=201, rol_id=2001),
            UsuarioRol(id=3002, usuario_id=202, rol_id=2002),
            UsuarioRol(id=3003, usuario_id=203, rol_id=2003),
            UsuarioRol(id=3004, usuario_id=204, rol_id=2004),
            UsuarioRol(id=3005, usuario_id=205, rol_id=2001),
        ])
        db.session.add_all([
            Equipo(
                id=401,
                empresa_id=101,
                codigo="EQ-MANT-1",
                nombre="Balanza",
                estado="activo",
                estado_operativo="OPERATIVO",
                requiere_mantenimiento=True,
            ),
            Equipo(
                id=402,
                empresa_id=102,
                codigo="EQ-MANT-2",
                nombre="Estufa",
                estado="activo",
                estado_operativo="OPERATIVO",
                requiere_mantenimiento=True,
            ),
            Equipo(
                id=403,
                empresa_id=101,
                codigo="EQ-INACTIVO",
                nombre="Equipo inactivo",
                estado="inactivo",
                estado_operativo="OPERATIVO",
                requiere_mantenimiento=True,
            ),
            Equipo(
                id=404,
                empresa_id=101,
                codigo="EQ-RETIRADO",
                nombre="Equipo retirado",
                estado="activo",
                estado_operativo="RETIRADO",
                requiere_mantenimiento=True,
            ),
        ])

    def user(self, user_id):
        return db.session.get(Usuario, user_id)

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def csrf_token(self, client):
        with client.session_transaction() as session:
            return session["equipamiento_mantenimiento_csrf"]

    def add_plan(self, empresa_id=101, equipo_id=401, codigo="PLAN-MANT"):
        plan = EquipoPlanMantenimiento(
            empresa_id=empresa_id,
            equipo_id=equipo_id,
            codigo=codigo,
            nombre="Plan preventivo",
            periodicidad_meses=6,
            fecha_inicio=date(2026, 8, 1),
            proxima_fecha=date(2027, 2, 1),
            responsable_id=201 if empresa_id == 101 else 205,
            proveedor="Proveedor externo",
            estado="ACTIVO",
        )
        db.session.add(plan)
        db.session.flush()
        return plan

    def add_maintenance(self, empresa_id=101, equipo_id=401, codigo="MANT-001", plan=None):
        maintenance = EquipoMantenimiento(
            empresa_id=empresa_id,
            equipo_id=equipo_id,
            plan_id=plan.id if plan else None,
            codigo=codigo,
            tipo_mantenimiento="PREVENTIVO" if plan else "CORRECTIVO",
            estado="PROGRAMADO",
            fecha_planificada=date(2026, 8, 10),
            fecha_mantenimiento=None,
            proveedor="Proveedor externo",
            resultado=None,
            observaciones="Orden programada",
            archivo_url="legacy/mantenimiento.pdf",
        )
        db.session.add(maintenance)
        db.session.flush()
        return maintenance

    def add_document_version(self):
        document = Documento(
            id=501,
            empresa_id=101,
            codigo="DOC-MANT",
            titulo="Evidencia de mantenimiento",
            tipo_documento="REGISTRO",
            estado="APROBADO",
            version_actual="1",
            elaborado_por_id=201,
        )
        version = DocumentoVersion(
            id=1501,
            empresa_id=101,
            documento_id=501,
            version="1",
            estado="APROBADO",
            elaborado_por_id=201,
            archivo_storage_path="empresa_101/documento/evidencia.pdf",
        )
        db.session.add_all([document, version])
        db.session.flush()
        return document, version

    def add_other_company_document_version(self):
        document = Documento(
            id=502,
            empresa_id=102,
            codigo="DOC-OTRA",
            titulo="Documento otra empresa",
            tipo_documento="REGISTRO",
            estado="APROBADO",
            version_actual="1",
            elaborado_por_id=205,
        )
        version = DocumentoVersion(
            id=1502,
            empresa_id=102,
            documento_id=502,
            version="1",
            estado="APROBADO",
            elaborado_por_id=205,
            archivo_storage_path="empresa_102/documento/evidencia.pdf",
        )
        db.session.add_all([document, version])
        db.session.flush()
        return document, version

    def test_plan_model_relationships_and_required_fields_exist(self):
        plan = self.add_plan()
        db.session.commit()

        self.assertEqual(plan.equipo.codigo, "EQ-MANT-1")
        self.assertEqual(plan.responsable.username, "admin-eq")
        self.assertEqual(plan.periodicidad_meses, 6)
        self.assertEqual(plan.estado, "ACTIVO")

    def test_plan_code_is_unique_per_company_and_periodicity_is_positive(self):
        self.add_plan(codigo="PLAN-UNICO")
        db.session.commit()

        db.session.add(EquipoPlanMantenimiento(
            empresa_id=101,
            equipo_id=401,
            codigo="PLAN-UNICO",
            nombre="Duplicado",
            periodicidad_meses=3,
            fecha_inicio=date(2026, 8, 1),
            estado="ACTIVO",
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        self.add_plan(empresa_id=102, equipo_id=402, codigo="PLAN-UNICO")
        db.session.commit()
        self.assertEqual(EquipoPlanMantenimiento.query.filter_by(codigo="PLAN-UNICO").count(), 2)

        db.session.add(EquipoPlanMantenimiento(
            empresa_id=101,
            equipo_id=401,
            codigo="PLAN-CERO",
            nombre="Invalido",
            periodicidad_meses=0,
            fecha_inicio=date(2026, 8, 1),
            estado="ACTIVO",
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_maintenance_new_fields_allowed_types_states_and_negative_cost_rejected(self):
        plan = self.add_plan()
        maintenance = self.add_maintenance(plan=plan)
        maintenance.estado = "EN_PROCESO"
        maintenance.fecha_inicio = date(2026, 8, 10)
        maintenance.costo = 125.50
        maintenance.moneda = "USD"
        db.session.commit()

        saved = db.session.get(EquipoMantenimiento, maintenance.id)
        self.assertEqual(saved.plan.codigo, "PLAN-MANT")
        self.assertEqual(saved.estado, "EN_PROCESO")
        self.assertEqual(saved.fecha_planificada, date(2026, 8, 10))
        self.assertEqual(saved.archivo_url, "legacy/mantenimiento.pdf")

        db.session.add(EquipoMantenimiento(
            empresa_id=101,
            equipo_id=401,
            codigo="MANT-COSTO",
            tipo_mantenimiento="CORRECTIVO",
            estado="PROGRAMADO",
            fecha_planificada=date(2026, 9, 1),
            costo=-1,
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(EquipoMantenimiento(
            empresa_id=101,
            equipo_id=401,
            codigo="MANT-TIPO",
            tipo_mantenimiento="CALIBRACION",
            estado="PROGRAMADO",
            fecha_planificada=date(2026, 9, 1),
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(EquipoMantenimiento(
            empresa_id=101,
            equipo_id=401,
            codigo="MANT-ESTADO",
            tipo_mantenimiento="CORRECTIVO",
            estado="VENCIDO",
            fecha_planificada=date(2026, 9, 1),
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_maintenance_code_is_unique_per_company_and_plan_is_optional(self):
        self.add_maintenance(codigo="MANT-UNICO")
        db.session.commit()

        db.session.add(EquipoMantenimiento(
            empresa_id=101,
            equipo_id=401,
            codigo="MANT-UNICO",
            tipo_mantenimiento="CORRECTIVO",
            estado="PROGRAMADO",
            fecha_planificada=date(2026, 9, 1),
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        other = self.add_maintenance(empresa_id=102, equipo_id=402, codigo="MANT-UNICO")
        db.session.commit()
        self.assertIsNone(other.plan_id)
        self.assertEqual(EquipoMantenimiento.query.filter_by(codigo="MANT-UNICO").count(), 2)

    def test_maintenance_document_uses_document_version_and_unique_pair(self):
        maintenance = self.add_maintenance()
        document, version = self.add_document_version()
        evidence = EquipoMantenimientoDocumento(
            empresa_id=101,
            mantenimiento_id=maintenance.id,
            documento_id=document.id,
            documento_version_id=version.id,
            tipo_evidencia="INFORME",
            observaciones="Evidencia aprobada",
            vinculado_por_id=201,
        )
        db.session.add(evidence)
        db.session.commit()

        self.assertEqual(evidence.documento.codigo, "DOC-MANT")
        self.assertEqual(evidence.documento_version.version, "1")
        self.assertEqual(evidence.mantenimiento.codigo, "MANT-001")

        db.session.add(EquipoMantenimientoDocumento(
            empresa_id=101,
            mantenimiento_id=maintenance.id,
            documento_id=document.id,
            documento_version_id=version.id,
            tipo_evidencia="DUPLICADA",
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_equipment_history_accepts_maintenance_event_types(self):
        event = EquipoHistorial(
            empresa_id=101,
            equipo_id=401,
            tipo_evento="MANTENIMIENTO_PROGRAMADO",
            descripcion="Orden programada.",
            usuario_id=201,
        )
        db.session.add(event)
        db.session.commit()

        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="MANTENIMIENTO_PROGRAMADO").count(), 1)

    def test_maintenance_permissions_are_assigned_by_role_without_duplicates(self):
        admin = self.user(201)
        quality = self.user(202)
        technician = self.user(203)
        consultation = self.user(204)

        for permission in MAINTENANCE_PERMISSIONS:
            self.assertTrue(user_has_permission(admin, permission))
            self.assertTrue(user_has_permission(quality, permission))

        self.assertTrue(user_has_permission(technician, "equipos.mantenimientos.ver"))
        self.assertTrue(user_has_permission(technician, "equipos.mantenimientos.programar"))
        self.assertTrue(user_has_permission(technician, "equipos.mantenimientos.correctivos.crear"))
        self.assertTrue(user_has_permission(technician, "equipos.mantenimientos.iniciar"))
        self.assertTrue(user_has_permission(technician, "equipos.mantenimientos.completar"))
        self.assertTrue(user_has_permission(technician, "equipos.mantenimientos.cancelar"))
        self.assertTrue(user_has_permission(technician, "equipos.mantenimientos.evidencias.vincular"))
        self.assertFalse(user_has_permission(technician, "equipos.mantenimientos.planes.crear"))
        self.assertFalse(user_has_permission(technician, "equipos.mantenimientos.planes.editar"))
        self.assertFalse(user_has_permission(technician, "equipos.mantenimientos.evidencias.desvincular"))

        self.assertTrue(user_has_permission(consultation, "equipos.mantenimientos.ver"))
        for permission in MAINTENANCE_PERMISSIONS - {"equipos.mantenimientos.ver"}:
            self.assertFalse(user_has_permission(consultation, permission))

        self.assertEqual(Permiso.query.filter(Permiso.codigo.in_(MAINTENANCE_PERMISSIONS)).count(), len(MAINTENANCE_PERMISSIONS))
        assigned_pairs = db.session.query(RolPermiso.rol_id, RolPermiso.permiso_id).distinct().count()
        self.assertEqual(RolPermiso.query.count(), assigned_pairs)

    def test_structural_indexes_and_columns_are_present(self):
        inspector = inspect(db.engine)

        self.assertIn("equipo_planes_mantenimiento", inspector.get_table_names())
        self.assertIn("equipo_mantenimiento_documentos", inspector.get_table_names())
        maintenance_columns = {column["name"] for column in inspector.get_columns("equipo_mantenimientos")}
        for column in {
            "plan_id",
            "codigo",
            "estado",
            "fecha_planificada",
            "fecha_inicio",
            "fecha_finalizacion",
            "descripcion_trabajo",
            "responsable_id",
            "costo",
            "moneda",
            "cancelado_por_id",
            "motivo_cancelacion",
            "archivo_url",
        }:
            self.assertIn(column, maintenance_columns)

        maintenance_indexes = {index["name"] for index in inspector.get_indexes("equipo_mantenimientos")}
        self.assertIn("ix_equipo_mantenimiento_empresa_estado", maintenance_indexes)
        self.assertIn("ix_equipo_mantenimiento_empresa_fecha_planificada", maintenance_indexes)
        self.assertIn("ix_equipo_mantenimiento_empresa_equipo_estado", maintenance_indexes)
        self.assertIn("ix_equipo_mantenimiento_plan_id", maintenance_indexes)

        evidence_indexes = {index["name"] for index in inspector.get_indexes("equipo_mantenimiento_documentos")}
        self.assertIn("ix_equipo_mantenimiento_documentos_empresa_mantenimiento", evidence_indexes)
        self.assertIn("ix_equipo_mantenimiento_documentos_documento_version_id", evidence_indexes)

    def test_migration_revision_metadata_targets_5a_head(self):
        self.assertEqual(migration_5b1.down_revision, "e1a2b3c4d5f6")
        self.assertEqual(migration_5b1.revision, "f2b3c4d5e6a7")

    def test_service_creates_updates_and_inactivates_plan_with_audit(self):
        admin = self.user(201)
        plan = maintenance_service.crear_plan_preventivo(admin, {
            "equipo_id": 401,
            "codigo": "PM-SERV-001",
            "nombre": "Plan servicio",
            "periodicidad_meses": 2,
            "fecha_inicio": "2026-08-01",
            "responsable_id": 201,
            "proveedor": "Proveedor A",
        })
        db.session.commit()

        self.assertEqual(plan.estado, "ACTIVO")
        self.assertEqual(plan.proxima_fecha, date(2026, 8, 1))
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="PLAN_MANTENIMIENTO_CREADO", usuario_id=201).first())

        updated = maintenance_service.actualizar_plan_preventivo(admin, plan.id, {
            "codigo": "PM-SERV-002",
            "nombre": "Plan actualizado",
            "periodicidad_meses": 3,
            "fecha_inicio": date(2026, 8, 1),
            "proxima_fecha": date(2026, 9, 1),
            "responsable_id": 201,
            "proveedor": "Proveedor B",
        })
        self.assertEqual(updated.codigo, "PM-SERV-002")
        self.assertEqual(updated.periodicidad_meses, 3)

        maintenance_service.inactivar_plan_preventivo(admin, plan.id, "Cambio de estrategia")
        db.session.commit()
        self.assertEqual(plan.estado, "INACTIVO")
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="PLAN_MANTENIMIENTO_ACTUALIZADO").first())
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="PLAN_MANTENIMIENTO_INACTIVADO").first())

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.actualizar_plan_preventivo(admin, plan.id, {"nombre": "No permitido"})

    def test_service_rejects_invalid_plan_data_and_unavailable_equipment(self):
        admin = self.user(201)
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_plan_preventivo(admin, {
                "equipo_id": 401,
                "codigo": "PM-MALA",
                "nombre": "Plan malo",
                "periodicidad_meses": 0,
                "fecha_inicio": "2026-08-01",
            })
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_plan_preventivo(admin, {
                "equipo_id": 403,
                "codigo": "PM-INACTIVO",
                "nombre": "Plan inactivo",
                "periodicidad_meses": 1,
                "fecha_inicio": "2026-08-01",
            })
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_plan_preventivo(admin, {
                "equipo_id": 404,
                "codigo": "PM-RETIRADO",
                "nombre": "Plan retirado",
                "periodicidad_meses": 1,
                "fecha_inicio": "2026-08-01",
            })
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_plan_preventivo(admin, {
                "equipo_id": 401,
                "codigo": "PM-RESP",
                "nombre": "Plan con responsable externo",
                "periodicidad_meses": 1,
                "fecha_inicio": "2026-08-01",
                "responsable_id": 205,
            })

    def test_service_schedules_preventive_and_blocks_inactive_plan_or_duplicate_open_order(self):
        admin = self.user(201)
        plan = self.add_plan(codigo="PM-PROG")
        db.session.commit()

        order = maintenance_service.programar_mantenimiento_desde_plan(admin, plan.id, date(2026, 8, 20))
        db.session.commit()

        self.assertEqual(order.tipo_mantenimiento, "PREVENTIVO")
        self.assertEqual(order.estado, "PROGRAMADO")
        self.assertEqual(order.plan_id, plan.id)
        self.assertIsNone(order.archivo_url)
        self.assertTrue(order.codigo.startswith("MANT-"))
        self.assertEqual(plan.proxima_fecha, date(2027, 2, 1))
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="MANTENIMIENTO_PROGRAMADO").first())

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.programar_mantenimiento_desde_plan(admin, plan.id, date(2026, 8, 20))

        maintenance_service.inactivar_plan_preventivo(admin, plan.id)
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.programar_mantenimiento_desde_plan(admin, plan.id, date(2026, 9, 20))

    def test_service_creates_corrective_without_plan_and_generates_codes_per_company(self):
        admin = self.user(201)
        other_admin = self.user(205)

        corrective = maintenance_service.crear_mantenimiento_correctivo(admin, 401, {
            "descripcion_trabajo": "Ruido anormal en motor",
            "fecha_planificada": "2026-08-15",
            "responsable_id": 201,
        })
        other = maintenance_service.crear_mantenimiento_correctivo(other_admin, 402, {
            "descripcion_trabajo": "Falla de resistencia",
            "fecha_planificada": "2026-08-15",
            "responsable_id": 205,
        })
        db.session.commit()

        self.assertIsNone(corrective.plan_id)
        self.assertEqual(corrective.tipo_mantenimiento, "CORRECTIVO")
        self.assertEqual(corrective.estado, "PROGRAMADO")
        self.assertEqual(corrective.codigo, other.codigo)
        self.assertEqual(EquipoMantenimiento.query.filter_by(codigo=corrective.codigo).count(), 2)
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="MANTENIMIENTO_CORRECTIVO_CREADO").first())

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_mantenimiento_correctivo(admin, 401, {"fecha_planificada": "2026-08-15"})
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_mantenimiento_correctivo(admin, 402, {
                "descripcion_trabajo": "Cruce empresa",
                "fecha_planificada": "2026-08-15",
            })

    def test_service_transitions_validate_state_dates_cost_and_preserve_equipment_status(self):
        admin = self.user(201)
        maintenance = self.add_maintenance(codigo="MANT-FLUJO")
        original_equipment_state = maintenance.equipo.estado_operativo
        db.session.commit()

        started = maintenance_service.iniciar_mantenimiento(admin, maintenance.id, date(2026, 8, 10))
        self.assertEqual(started.estado, "EN_PROCESO")
        self.assertEqual(started.fecha_inicio, date(2026, 8, 10))
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.iniciar_mantenimiento(admin, maintenance.id, date(2026, 8, 11))

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.completar_mantenimiento(admin, maintenance.id, {
                "fecha_finalizacion": date(2026, 8, 9),
                "descripcion_trabajo": "Trabajo",
                "resultado": "OK",
            })
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.completar_mantenimiento(admin, maintenance.id, {
                "fecha_finalizacion": date(2026, 8, 10),
                "descripcion_trabajo": "Trabajo",
                "resultado": "OK",
                "costo": "-1",
                "moneda": "USD",
            })
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.completar_mantenimiento(admin, maintenance.id, {
                "fecha_finalizacion": date(2026, 8, 10),
                "descripcion_trabajo": "",
                "resultado": "OK",
            })

        completed = maintenance_service.completar_mantenimiento(admin, maintenance.id, {
            "fecha_finalizacion": date(2026, 8, 10),
            "descripcion_trabajo": "Trabajo realizado",
            "resultado": "OK",
            "costo": "25.50",
            "moneda": "USD",
        })
        db.session.commit()

        self.assertEqual(completed.estado, "COMPLETADO")
        self.assertEqual(completed.fecha_mantenimiento, date(2026, 8, 10))
        self.assertEqual(completed.equipo.estado_operativo, original_equipment_state)
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="MANTENIMIENTO_INICIADO").first())
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="MANTENIMIENTO_COMPLETADO").first())
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.cancelar_mantenimiento(admin, maintenance.id, "Ya termino")

    def test_service_cancels_from_open_states_requires_reason_and_audits(self):
        admin = self.user(201)
        programmed = self.add_maintenance(codigo="MANT-CANCEL-PROG")
        in_process = self.add_maintenance(codigo="MANT-CANCEL-PROC")
        in_process.estado = "EN_PROCESO"
        in_process.fecha_inicio = date(2026, 8, 10)
        db.session.commit()

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.cancelar_mantenimiento(admin, programmed.id, "no")

        maintenance_service.cancelar_mantenimiento(admin, programmed.id, "Proveedor no disponible")
        maintenance_service.cancelar_mantenimiento(admin, in_process.id, "Falla externa confirmada")
        db.session.commit()

        self.assertEqual(programmed.estado, "CANCELADO")
        self.assertEqual(programmed.cancelado_por_id, admin.id)
        self.assertEqual(in_process.estado, "CANCELADO")
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="MANTENIMIENTO_CANCELADO").count(), 2)

    def test_service_dynamic_due_pending_and_next_30_days_queries_are_company_scoped(self):
        admin = self.user(201)
        today = date(2026, 8, 4)
        past = self.add_maintenance(codigo="MANT-PAST")
        today_order = self.add_maintenance(codigo="MANT-TODAY")
        future_30 = self.add_maintenance(codigo="MANT-30")
        future_31 = self.add_maintenance(codigo="MANT-31")
        completed = self.add_maintenance(codigo="MANT-DONE")
        other = self.add_maintenance(empresa_id=102, equipo_id=402, codigo="MANT-OTHER")
        past.fecha_planificada = date(2026, 8, 3)
        today_order.fecha_planificada = today
        future_30.fecha_planificada = date(2026, 9, 3)
        future_31.fecha_planificada = date(2026, 9, 4)
        completed.fecha_planificada = date(2026, 8, 3)
        completed.estado = "COMPLETADO"
        other.fecha_planificada = date(2026, 8, 3)
        db.session.commit()

        self.assertTrue(maintenance_service.esta_vencido(past, today=today))
        self.assertFalse(maintenance_service.esta_vencido(today_order, today=today))
        self.assertEqual([item.codigo for item in maintenance_service.mantenimientos_vencidos(admin, today=today)], ["MANT-PAST"])
        self.assertEqual(
            [item.codigo for item in maintenance_service.mantenimientos_proximos(admin, today=today)],
            ["MANT-TODAY", "MANT-30"],
        )
        pending_codes = {item.codigo for item in maintenance_service.mantenimientos_pendientes(admin)}
        self.assertIn("MANT-PAST", pending_codes)
        self.assertNotIn("MANT-DONE", pending_codes)
        self.assertNotIn("MANT-OTHER", pending_codes)

    def test_service_monthly_next_date_handles_end_of_month_and_leap_year(self):
        admin = self.user(201)
        plan = self.add_plan(codigo="PM-FIN-MES")
        plan.periodicidad_meses = 1
        order = self.add_maintenance(codigo="MANT-FIN-MES", plan=plan)
        order.estado = "EN_PROCESO"
        order.fecha_inicio = date(2026, 1, 31)
        db.session.commit()

        maintenance_service.completar_mantenimiento(admin, order.id, {
            "fecha_finalizacion": date(2026, 1, 31),
            "descripcion_trabajo": "Preventivo mensual",
            "resultado": "OK",
        })
        self.assertEqual(plan.proxima_fecha, date(2026, 2, 28))
        self.assertEqual(order.fecha_proxima, date(2026, 2, 28))

        plan.proxima_fecha = date(2024, 2, 29)
        order2 = self.add_maintenance(codigo="MANT-BISIESTO", plan=plan)
        order2.estado = "EN_PROCESO"
        order2.fecha_inicio = date(2024, 2, 29)
        db.session.commit()
        maintenance_service.completar_mantenimiento(admin, order2.id, {
            "fecha_finalizacion": date(2024, 2, 29),
            "descripcion_trabajo": "Preventivo bisiesto",
            "resultado": "OK",
        })
        self.assertEqual(plan.proxima_fecha, date(2024, 3, 29))
        self.assertEqual(EquipoMantenimiento.query.filter_by(plan_id=plan.id).count(), 2)

    def test_service_links_and_unlinks_document_evidence_with_permissions_and_audit(self):
        admin = self.user(201)
        technician = self.user(203)
        maintenance = self.add_maintenance(codigo="MANT-EVID")
        maintenance.estado = "COMPLETADO"
        document, version = self.add_document_version()
        db.session.commit()

        evidence = maintenance_service.vincular_evidencia_documental(
            technician,
            maintenance.id,
            document.id,
            version.id,
            "INFORME",
            "Informe final",
        )
        db.session.commit()

        self.assertEqual(evidence.mantenimiento_id, maintenance.id)
        self.assertEqual(evidence.documento_version_id, version.id)
        self.assertEqual(evidence.vinculado_por_id, technician.id)
        self.assertEqual(maintenance.archivo_url, "legacy/mantenimiento.pdf")
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="EVIDENCIA_MANTENIMIENTO_VINCULADA").first())

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.vincular_evidencia_documental(technician, maintenance.id, document.id, version.id, "DUP")
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.desvincular_evidencia_documental(technician, evidence.id)

        maintenance_service.desvincular_evidencia_documental(admin, evidence.id, "Correccion de evidencia")
        db.session.commit()
        self.assertIsNone(db.session.get(EquipoMantenimientoDocumento, evidence.id))
        self.assertIsNotNone(db.session.get(Documento, document.id))
        self.assertIsNotNone(db.session.get(DocumentoVersion, version.id))
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="EVIDENCIA_MANTENIMIENTO_DESVINCULADA").first())

    def test_service_rejects_invalid_evidence_company_version_cancelled_and_consultation_actions(self):
        admin = self.user(201)
        consultation = self.user(204)
        maintenance = self.add_maintenance(codigo="MANT-EVID-ERR")
        document, version = self.add_document_version()
        other_document, other_version = self.add_other_company_document_version()
        db.session.commit()

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.vincular_evidencia_documental(admin, maintenance.id, other_document.id, other_version.id, "INFORME")
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.vincular_evidencia_documental(admin, maintenance.id, document.id, other_version.id, "INFORME")

        maintenance.estado = "CANCELADO"
        db.session.commit()
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.vincular_evidencia_documental(admin, maintenance.id, document.id, version.id, "INFORME")

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_mantenimiento_correctivo(consultation, 401, {
                "descripcion_trabajo": "Consulta sin permiso",
                "fecha_planificada": "2026-08-15",
            })
        self.assertEqual(maintenance_service.mantenimientos_pendientes(consultation), [])

    def test_service_enforces_technician_admin_and_quality_permissions(self):
        admin = self.user(201)
        quality = self.user(202)
        technician = self.user(203)
        plan = self.add_plan(codigo="PM-PERM")
        db.session.commit()

        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.crear_plan_preventivo(technician, {
                "equipo_id": 401,
                "codigo": "PM-TEC",
                "nombre": "Plan tecnico",
                "periodicidad_meses": 1,
                "fecha_inicio": "2026-08-01",
            })

        order = maintenance_service.programar_mantenimiento_desde_plan(technician, plan.id, date(2026, 8, 18))
        maintenance_service.iniciar_mantenimiento(technician, order.id, date(2026, 8, 18))
        maintenance_service.completar_mantenimiento(technician, order.id, {
            "fecha_finalizacion": date(2026, 8, 18),
            "descripcion_trabajo": "Trabajo tecnico",
            "resultado": "OK",
        })
        evidence_doc, evidence_version = self.add_document_version()
        evidence = maintenance_service.vincular_evidencia_documental(
            technician, order.id, evidence_doc.id, evidence_version.id, "REGISTRO"
        )
        with self.assertRaises(EquipoMantenimientoError):
            maintenance_service.desvincular_evidencia_documental(technician, evidence.id)
        maintenance_service.desvincular_evidencia_documental(quality, evidence.id, "Retiro autorizado")
        new_plan = maintenance_service.crear_plan_preventivo(admin, {
            "equipo_id": 401,
            "codigo": "PM-ADMIN",
            "nombre": "Plan admin",
            "periodicidad_meses": 1,
            "fecha_inicio": "2026-08-01",
        })
        db.session.commit()

        self.assertEqual(order.estado, "COMPLETADO")
        self.assertEqual(new_plan.estado, "ACTIVO")

    def test_web_lists_plans_and_maintenances_with_filters_and_navigation(self):
        plan = self.add_plan(codigo="PM-WEB")
        past = self.add_maintenance(codigo="MANT-WEB-PAST", plan=plan)
        future = self.add_maintenance(codigo="MANT-WEB-FUTURE")
        other = self.add_maintenance(empresa_id=102, equipo_id=402, codigo="MANT-WEB-OTHER")
        past.fecha_planificada = date(2020, 1, 1)
        future.fecha_planificada = date.today()
        other.fecha_planificada = date.today()
        db.session.commit()

        client = self.login(201)
        plans = client.get("/equipamiento/planes-mantenimiento")
        body = plans.get_data(as_text=True)
        self.assertEqual(plans.status_code, 200)
        self.assertIn("PM-WEB", body)
        self.assertIn("Planes de mantenimiento", body)
        self.assertIn("Mantenimientos", body)

        vencidos = client.get("/equipamiento/mantenimientos?vista=vencidos").get_data(as_text=True)
        self.assertIn("MANT-WEB-PAST", vencidos)
        self.assertIn("Vencido", vencidos)
        self.assertNotIn("MANT-WEB-OTHER", vencidos)

        proximos = client.get("/equipamiento/mantenimientos?vista=proximos").get_data(as_text=True)
        self.assertIn("MANT-WEB-FUTURE", proximos)
        self.assertNotIn("MANT-WEB-OTHER", proximos)
        self.assertEqual(db.session.get(EquipoMantenimiento, past.id).estado, "PROGRAMADO")

    def test_web_consultation_can_view_but_cannot_create_or_execute(self):
        plan = self.add_plan(codigo="PM-CONSULTA")
        maintenance = self.add_maintenance(codigo="MANT-CONSULTA", plan=plan)
        db.session.commit()

        client = self.login(204)
        self.assertEqual(client.get("/equipamiento/planes-mantenimiento").status_code, 200)
        detail = client.get(f"/equipamiento/mantenimientos/{maintenance.id}")
        self.assertEqual(detail.status_code, 200)
        body = detail.get_data(as_text=True)
        self.assertNotIn("Iniciar mantenimiento", body)
        self.assertNotIn("Cancelar mantenimiento", body)
        self.assertEqual(client.get("/equipamiento/planes-mantenimiento/nuevo").status_code, 403)
        self.assertEqual(client.get("/equipamiento/mantenimientos/correctivo/nuevo").status_code, 403)

    def test_web_blocks_cross_company_direct_ids(self):
        plan = self.add_plan(empresa_id=102, equipo_id=402, codigo="PM-OTRA")
        maintenance = self.add_maintenance(empresa_id=102, equipo_id=402, codigo="MANT-OTRA", plan=plan)
        db.session.commit()

        client = self.login(201)
        self.assertEqual(client.get(f"/equipamiento/planes-mantenimiento/{plan.id}").status_code, 404)
        self.assertEqual(client.get(f"/equipamiento/mantenimientos/{maintenance.id}").status_code, 404)

    def test_web_plan_create_edit_inactivate_and_schedule_use_service_and_csrf(self):
        client = self.login(201)
        form = client.get("/equipamiento/planes-mantenimiento/nuevo")
        self.assertEqual(form.status_code, 200)
        token = self.csrf_token(client)

        missing_csrf = client.post("/equipamiento/planes-mantenimiento/nuevo", data={
            "equipo_id": 401,
            "codigo": "PM-CSRF",
            "nombre": "Sin csrf",
            "periodicidad_meses": 1,
            "fecha_inicio": "2026-08-01",
        })
        self.assertEqual(missing_csrf.status_code, 403)

        response = client.post("/equipamiento/planes-mantenimiento/nuevo", data={
            "csrf_token": token,
            "equipo_id": 401,
            "codigo": "PM-WEB-CREATE",
            "nombre": "Plan web",
            "periodicidad_meses": 2,
            "fecha_inicio": "2026-08-01",
            "proxima_fecha": "2026-08-01",
            "responsable_id": 201,
            "proveedor": "Proveedor web",
        })
        self.assertEqual(response.status_code, 302)
        plan = EquipoPlanMantenimiento.query.filter_by(codigo="PM-WEB-CREATE").first()
        self.assertIsNotNone(plan)
        self.assertTrue(EquipoHistorial.query.filter_by(tipo_evento="PLAN_MANTENIMIENTO_CREADO").first())

        response = client.post(f"/equipamiento/planes-mantenimiento/{plan.id}/editar", data={
            "csrf_token": token,
            "equipo_id": 401,
            "codigo": "PM-WEB-EDIT",
            "nombre": "Plan web editado",
            "periodicidad_meses": 3,
            "fecha_inicio": "2026-08-01",
            "proxima_fecha": "2026-09-01",
            "responsable_id": 201,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(plan.codigo, "PM-WEB-EDIT")

        response = client.post(f"/equipamiento/planes-mantenimiento/{plan.id}/programar", data={
            "csrf_token": token,
            "fecha_planificada": "2026-09-01",
            "observaciones": "Programacion web",
        })
        self.assertEqual(response.status_code, 302)
        order = EquipoMantenimiento.query.filter_by(plan_id=plan.id, fecha_planificada=date(2026, 9, 1)).first()
        self.assertIsNotNone(order)

        response = client.post(f"/equipamiento/planes-mantenimiento/{plan.id}/inactivar", data={
            "csrf_token": token,
            "motivo": "Cierre temporal",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(plan.estado, "INACTIVO")
        self.assertEqual(client.get(f"/equipamiento/planes-mantenimiento/{plan.id}/inactivar").status_code, 405)

    def test_web_corrective_transitions_cancel_and_protected_state_field(self):
        client = self.login(201)
        client.get("/equipamiento/mantenimientos/correctivo/nuevo")
        token = self.csrf_token(client)
        response = client.post("/equipamiento/mantenimientos/correctivo/nuevo", data={
            "csrf_token": token,
            "equipo_id": 401,
            "fecha_planificada": "2026-08-20",
            "descripcion_trabajo": "Falla web",
            "responsable_id": 201,
            "proveedor": "Proveedor web",
            "estado": "COMPLETADO",
            "empresa_id": 102,
        })
        self.assertEqual(response.status_code, 302)
        maintenance = EquipoMantenimiento.query.filter_by(descripcion_trabajo="Falla web").first()
        self.assertEqual(maintenance.estado, "PROGRAMADO")
        self.assertEqual(maintenance.empresa_id, 101)
        original_state = maintenance.equipo.estado_operativo

        response = client.post(f"/equipamiento/mantenimientos/{maintenance.id}/iniciar", data={
            "csrf_token": token,
            "fecha_inicio": "2026-08-20",
            "estado": "CANCELADO",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(maintenance.estado, "EN_PROCESO")

        response = client.post(f"/equipamiento/mantenimientos/{maintenance.id}/completar", data={
            "csrf_token": token,
            "fecha_finalizacion": "2026-08-20",
            "descripcion_trabajo": "Trabajo web realizado",
            "resultado": "OK",
            "costo": "10",
            "moneda": "USD",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(maintenance.estado, "COMPLETADO")
        self.assertEqual(maintenance.equipo.estado_operativo, original_state)
        self.assertEqual(client.get(f"/equipamiento/mantenimientos/{maintenance.id}/iniciar").status_code, 405)

        cancelable = self.add_maintenance(codigo="MANT-WEB-CANCEL")
        db.session.commit()
        response = client.post(f"/equipamiento/mantenimientos/{cancelable.id}/cancelar", data={
            "csrf_token": token,
            "motivo": "",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(cancelable.estado, "PROGRAMADO")
        response = client.post(f"/equipamiento/mantenimientos/{cancelable.id}/cancelar", data={
            "csrf_token": token,
            "motivo": "Cancelacion solicitada",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(cancelable.estado, "CANCELADO")

    def test_web_evidence_link_unlink_permissions_and_document_integrity(self):
        tech_client = self.login(203)
        maintenance = self.add_maintenance(codigo="MANT-WEB-EVID")
        document, version = self.add_document_version()
        other_document, other_version = self.add_other_company_document_version()
        db.session.commit()

        tech_client.get(f"/equipamiento/mantenimientos/{maintenance.id}")
        token = self.csrf_token(tech_client)
        bad = tech_client.post(f"/equipamiento/mantenimientos/{maintenance.id}/evidencias", data={
            "csrf_token": token,
            "documento_id": document.id,
            "documento_version_id": other_version.id,
            "tipo_evidencia": "INFORME",
        })
        self.assertEqual(bad.status_code, 302)
        self.assertEqual(EquipoMantenimientoDocumento.query.count(), 0)

        response = tech_client.post(f"/equipamiento/mantenimientos/{maintenance.id}/evidencias", data={
            "csrf_token": token,
            "documento_id": document.id,
            "documento_version_id": version.id,
            "tipo_evidencia": "INFORME",
            "observaciones": "Evidencia web",
        })
        self.assertEqual(response.status_code, 302)
        evidence = EquipoMantenimientoDocumento.query.filter_by(mantenimiento_id=maintenance.id).first()
        self.assertIsNotNone(evidence)
        detail = tech_client.get(f"/equipamiento/mantenimientos/{maintenance.id}").get_data(as_text=True)
        self.assertIn("DOC-MANT", detail)
        self.assertNotIn("Desvincular", detail)
        self.assertEqual(tech_client.post(f"/equipamiento/mantenimientos/evidencias/{evidence.id}/desvincular", data={"csrf_token": token}).status_code, 403)

        cancelled = self.add_maintenance(codigo="MANT-WEB-EVID-CANCEL")
        cancelled.estado = "CANCELADO"
        db.session.commit()
        response = tech_client.post(f"/equipamiento/mantenimientos/{cancelled.id}/evidencias", data={
            "csrf_token": token,
            "documento_id": document.id,
            "documento_version_id": version.id,
            "tipo_evidencia": "INFORME",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(EquipoMantenimientoDocumento.query.filter_by(mantenimiento_id=cancelled.id).first())

    def test_web_admin_unlinks_evidence_without_deleting_document_or_version(self):
        admin_client = self.login(201)
        maintenance = self.add_maintenance(codigo="MANT-WEB-UNLINK")
        document, version = self.add_document_version()
        evidence = EquipoMantenimientoDocumento(
            empresa_id=101,
            mantenimiento_id=maintenance.id,
            documento_id=document.id,
            documento_version_id=version.id,
            tipo_evidencia="INFORME",
            vinculado_por_id=201,
        )
        db.session.add(evidence)
        db.session.commit()

        admin_client.get(f"/equipamiento/mantenimientos/{maintenance.id}")
        token = self.csrf_token(admin_client)
        response = admin_client.post(f"/equipamiento/mantenimientos/evidencias/{evidence.id}/desvincular", data={
            "csrf_token": token,
            "motivo": "Retiro web",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.session.get(EquipoMantenimientoDocumento, evidence.id))
        self.assertIsNotNone(db.session.get(Documento, document.id))
        self.assertIsNotNone(db.session.get(DocumentoVersion, version.id))


if __name__ == "__main__":
    unittest.main()
