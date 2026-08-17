import tempfile
import unittest
from datetime import date

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import Documento, DocumentoVersion
from app.models.empresa import Empresa
from app.models.equipos import (
    MaterialReferencia,
    MaterialReferenciaDocumento,
    MaterialReferenciaHistorial,
)
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services import material_referencia_service as material_service
from app.services.material_referencia_service import MaterialReferenciaError
from migrations.versions import e1a2b3c4d5f6_paquete_5a_instalaciones_equipamiento as migration_5a


EQUIPMENT_PERMISSIONS = {code for code, _name, _module in migration_5a.NEW_PERMISSIONS}


class Equipamiento5EMaterialesReferenciaTest(unittest.TestCase):
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
            Usuario(id=201, empresa_id=101, nombre="Admin", apellido="Uno", email="admin@mat", username="admin-mat", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Tecnico", apellido="Uno", email="tecnico@mat", username="tecnico-mat", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Consulta", apellido="Uno", email="consulta@mat", username="consulta-mat", password_hash="x", activo=True),
            Usuario(id=205, empresa_id=102, nombre="Admin", apellido="Dos", email="admin2@mat", username="admin2-mat", password_hash="x", activo=True),
        ])
        db.session.add_all([
            Rol(id=2001, nombre="ADMINISTRADOR", es_sistema=True),
            Rol(id=2002, nombre="TECNICO", es_sistema=True),
            Rol(id=2003, nombre="CONSULTA", es_sistema=True),
        ])
        permissions = {}
        for index, (code, name, module) in enumerate(migration_5a.NEW_PERMISSIONS, start=1):
            permission = Permiso(id=1000 + index, codigo=code, nombre=name, descripcion=name, modulo=module)
            db.session.add(permission)
            permissions[code] = permission
        db.session.flush()
        link_id = 5000
        role_permissions = {
            "ADMINISTRADOR": EQUIPMENT_PERMISSIONS,
            "TECNICO": {"equipos.ver", "equipos.editar", "equipos.documentos.vincular"},
            "CONSULTA": {"equipos.ver"},
        }
        for role in Rol.query.all():
            for code in role_permissions[role.nombre]:
                link_id += 1
                db.session.add(RolPermiso(id=link_id, rol_id=role.id, permiso_id=permissions[code].id))
        db.session.add_all([
            UsuarioRol(id=3001, usuario_id=201, rol_id=2001),
            UsuarioRol(id=3002, usuario_id=202, rol_id=2002),
            UsuarioRol(id=3003, usuario_id=203, rol_id=2003),
            UsuarioRol(id=3004, usuario_id=205, rol_id=2001),
        ])

    def user(self, user_id=201):
        return db.session.get(Usuario, user_id)

    def create_material(self, user_id=201, **overrides):
        data = {
            "codigo": "MR-001",
            "nombre": "Solucion buffer pH 7",
            "tipo": "MATERIAL_REFERENCIA",
            "fabricante": "Proveedor certificado",
            "proveedor": "Distribuidor local",
            "lote": "L-2026",
            "certificado_numero": "CERT-001",
            "referencia_fabricante": "BUF-7",
            "fecha_recepcion": date(2026, 8, 17),
            "fecha_caducidad": date(2027, 8, 17),
            "ubicacion": "Almacen frio",
            "condiciones_almacenamiento": "2-8 C",
            "responsable_id": 202 if user_id == 201 else 205,
            "cantidad_inicial": "500",
            "unidad": "mL",
        }
        data.update(overrides)
        return material_service.crear_material_referencia(self.user(user_id), data)

    def add_document_version(self, empresa_id=101, document_id=501, version_id=1501, code="DOC-MR"):
        document = Documento(
            id=document_id,
            empresa_id=empresa_id,
            codigo=code,
            titulo="Certificado material referencia",
            tipo_documento="REGISTRO",
            estado="APROBADO",
            version_actual="1",
            elaborado_por_id=201 if empresa_id == 101 else 205,
        )
        version = DocumentoVersion(
            id=version_id,
            empresa_id=empresa_id,
            documento_id=document_id,
            version="1",
            estado="APROBADO",
            elaborado_por_id=201 if empresa_id == 101 else 205,
            archivo_storage_path=f"empresa_{empresa_id}/documento/material.pdf",
        )
        db.session.add_all([document, version])
        db.session.flush()
        return document, version

    def test_model_schema_supports_materials_reference_without_parallel_structure(self):
        inspector = inspect(db.engine)
        self.assertIn("materiales_referencia", inspector.get_table_names())
        self.assertIn("material_referencia_documentos", inspector.get_table_names())
        self.assertIn("material_referencia_historial", inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("materiales_referencia")}
        self.assertTrue({
            "codigo", "nombre", "tipo", "fabricante", "proveedor", "lote",
            "certificado_numero", "fecha_recepcion", "fecha_apertura",
            "fecha_puesta_en_uso", "fecha_caducidad", "estado", "ubicacion",
            "condiciones_almacenamiento", "responsable_id", "cantidad_inicial",
            "cantidad_disponible", "unidad", "activo",
        }.issubset(columns))
        self.assertEqual(MaterialReferencia.__tablename__, "materiales_referencia")

    def test_service_creates_material_and_reference_standard_with_validations(self):
        material = self.create_material()
        standard = self.create_material(
            codigo="PR-001",
            nombre="Pesa patron 100 g",
            tipo="PATRON_REFERENCIA",
            cantidad_inicial="",
            unidad="",
        )
        other_company = self.create_material(user_id=205, codigo="MR-001", responsable_id=205)

        self.assertEqual(material.estado, "DISPONIBLE")
        self.assertEqual(material.cantidad_disponible, material.cantidad_inicial)
        self.assertEqual(standard.tipo, "PATRON_REFERENCIA")
        self.assertEqual(other_company.empresa_id, 102)
        self.assertEqual(MaterialReferenciaHistorial.query.filter_by(tipo_evento="MATERIAL_REFERENCIA_CREADO").count(), 3)
        with self.assertRaisesRegex(MaterialReferenciaError, "codigo"):
            self.create_material(codigo="")
        with self.assertRaisesRegex(MaterialReferenciaError, "Ya existe"):
            self.create_material(codigo="MR-001")
        with self.assertRaisesRegex(MaterialReferenciaError, "tipo"):
            self.create_material(codigo="MR-BAD", tipo="REACTIVO")
        with self.assertRaisesRegex(MaterialReferenciaError, "caducidad"):
            self.create_material(codigo="MR-DATE", fecha_caducidad=date(2026, 8, 16))
        with self.assertRaisesRegex(MaterialReferenciaError, "responsable"):
            self.create_material(codigo="MR-RESP", responsable_id=205)

    def test_service_state_transitions_terminal_states_and_history(self):
        material = self.create_material()
        material_service.poner_en_uso(self.user(), material.id, date(2026, 8, 20), "Apertura controlada")
        self.assertEqual(material.estado, "EN_USO")
        self.assertEqual(material.fecha_apertura, date(2026, 8, 20))
        self.assertEqual(material.fecha_puesta_en_uso, date(2026, 8, 20))
        with self.assertRaisesRegex(MaterialReferenciaError, "ya se encuentra en uso"):
            material_service.poner_en_uso(self.user(), material.id, date(2026, 8, 21))

        material_service.agotar(self.user(), material.id, "Consumo total")
        self.assertEqual(material.estado, "AGOTADO")
        self.assertEqual(int(material.cantidad_disponible), 0)
        with self.assertRaisesRegex(MaterialReferenciaError, "estado terminal|disponibles"):
            material_service.poner_en_uso(self.user(), material.id, date(2026, 8, 22))

        retired = self.create_material(codigo="MR-RET")
        with self.assertRaisesRegex(MaterialReferenciaError, "motivo"):
            material_service.retirar(self.user(), retired.id, "")
        material_service.retirar(self.user(), retired.id, "Certificado invalido")
        self.assertEqual(retired.estado, "RETIRADO")

        events = {event.tipo_evento for event in MaterialReferenciaHistorial.query.all()}
        self.assertTrue({
            "MATERIAL_REFERENCIA_PUESTO_EN_USO",
            "MATERIAL_REFERENCIA_AGOTADO",
            "MATERIAL_REFERENCIA_RETIRADO",
        }.issubset(events))

    def test_service_detects_expiration_marks_expired_and_queries_upcoming(self):
        past = self.create_material(codigo="MR-PAST", fecha_recepcion=date(2026, 7, 1), fecha_caducidad=date(2026, 8, 1))
        future = self.create_material(codigo="MR-FUTURE", fecha_caducidad=date(2026, 9, 1))
        later = self.create_material(codigo="MR-LATER", fecha_caducidad=date(2026, 10, 1))
        no_expiration = self.create_material(codigo="MR-NO-EXP", fecha_caducidad="")
        db.session.commit()

        today = date(2026, 8, 17)
        self.assertTrue(material_service.esta_vencido(past, today=today))
        self.assertFalse(material_service.esta_vencido(future, today=today))
        self.assertFalse(material_service.esta_vencido(no_expiration, today=today))
        self.assertEqual(material_service.vencidos(self.user(), today=today), [past])

        material_service.marcar_vencido(self.user(), past.id, today=today)
        self.assertEqual(past.estado, "VENCIDO")
        self.assertIs(material_service.marcar_vencido(self.user(), past.id, today=today), past)
        self.assertEqual(
            [item.codigo for item in material_service.proximos_a_vencer(self.user(), 20, today=today)],
            ["MR-FUTURE"],
        )
        material_service.agotar(self.user(), later.id, "No queda material")
        with self.assertRaisesRegex(MaterialReferenciaError, "agotado o retirado"):
            material_service.marcar_vencido(self.user(), later.id, today=date(2026, 11, 1))

    def test_service_links_unlinks_evidence_validates_document_version_and_freezes_terminal(self):
        material = self.create_material()
        document, version = self.add_document_version()
        other_document, other_version = self.add_document_version(empresa_id=102, document_id=502, version_id=1502, code="DOC-OTRA")
        wrong_document, wrong_version = self.add_document_version(document_id=503, version_id=1503, code="DOC-MR-2")
        db.session.commit()

        with self.assertRaisesRegex(MaterialReferenciaError, "documento seleccionado"):
            material_service.vincular_evidencia_documental(self.user(), material.id, other_document.id, other_version.id, "CERTIFICADO")
        with self.assertRaisesRegex(MaterialReferenciaError, "version documental seleccionada"):
            material_service.vincular_evidencia_documental(self.user(), material.id, document.id, other_version.id, "CERTIFICADO")
        with self.assertRaisesRegex(MaterialReferenciaError, "no pertenece al documento"):
            material_service.vincular_evidencia_documental(self.user(), material.id, document.id, wrong_version.id, "CERTIFICADO")

        evidence = material_service.vincular_evidencia_documental(self.user(), material.id, document.id, version.id, "CERTIFICADO", "Certificado lote")
        self.assertEqual(evidence.documento_version_id, version.id)
        self.assertEqual(MaterialReferenciaHistorial.query.filter_by(tipo_evento="EVIDENCIA_MATERIAL_REFERENCIA_VINCULADA").count(), 1)

        material_service.desvincular_evidencia_documental(self.user(), evidence.id, "Version corregida")
        db.session.flush()
        self.assertIsNone(db.session.get(MaterialReferenciaDocumento, evidence.id))
        self.assertEqual(MaterialReferenciaHistorial.query.filter_by(tipo_evento="EVIDENCIA_MATERIAL_REFERENCIA_DESVINCULADA").count(), 1)

        frozen = self.create_material(codigo="MR-FROZEN")
        frozen_evidence = material_service.vincular_evidencia_documental(self.user(), frozen.id, document.id, version.id, "CERTIFICADO")
        material_service.retirar(self.user(), frozen.id, "Decision tecnica")
        db.session.commit()
        before_events = MaterialReferenciaHistorial.query.count()
        with self.assertRaisesRegex(MaterialReferenciaError, "estado terminal"):
            material_service.vincular_evidencia_documental(self.user(), frozen.id, document.id, wrong_version.id, "CERTIFICADO")
        with self.assertRaisesRegex(MaterialReferenciaError, "estado terminal"):
            material_service.desvincular_evidencia_documental(self.user(), frozen_evidence.id, "Retiro posterior")
        self.assertEqual(MaterialReferenciaHistorial.query.count(), before_events)
        self.assertIsNotNone(db.session.get(MaterialReferenciaDocumento, frozen_evidence.id))

    def test_service_enforces_multicompany_scope_records_history_and_reuses_permissions(self):
        admin = self.user(201)
        other_admin = self.user(205)
        reader = self.user(203)
        material = self.create_material(codigo="MR-EMP1")
        other_material = self.create_material(user_id=205, codigo="MR-EMP2", responsable_id=205)
        document, version = self.add_document_version()
        db.session.commit()

        with self.assertRaisesRegex(MaterialReferenciaError, "no pertenece"):
            material_service.poner_en_uso(admin, other_material.id, date(2026, 8, 20))
        with self.assertRaisesRegex(MaterialReferenciaError, "no pertenece"):
            material_service.vincular_evidencia_documental(other_admin, material.id, document.id, version.id, "CERTIFICADO")
        with self.assertRaisesRegex(MaterialReferenciaError, "permisos"):
            material_service.crear_material_referencia(reader, {
                "codigo": "MR-READ",
                "nombre": "Lectura",
                "tipo": "MATERIAL_REFERENCIA",
                "fecha_recepcion": date(2026, 8, 17),
            })

        self.assertEqual(material_service.materiales(admin), [material])
        self.assertEqual(material_service.disponibles(admin), [material])
        material_service.poner_en_uso(admin, material.id, date(2026, 8, 20))
        self.assertEqual(material_service.en_uso(admin), [material])
        self.assertTrue(all(event.empresa_id == 101 for event in material.historial))


if __name__ == "__main__":
    unittest.main()
