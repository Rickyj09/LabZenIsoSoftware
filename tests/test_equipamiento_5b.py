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
        ])

    def user(self, user_id):
        return db.session.get(Usuario, user_id)

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


if __name__ == "__main__":
    unittest.main()
