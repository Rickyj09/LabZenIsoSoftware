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
from app.models.equipos import Equipo, EquipoCalibracion, EquipoCalibracionDocumento, EquipoHistorial, EquipoMantenimiento
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services import equipo_calibracion_service as calibration_service
from app.services.equipo_calibracion_service import EquipoCalibracionError
from migrations.versions import e1a2b3c4d5f6_paquete_5a_instalaciones_equipamiento as migration_5a


EQUIPMENT_PERMISSIONS = {code for code, _name, _module in migration_5a.NEW_PERMISSIONS}


class Equipamiento5CCalibracionesTest(unittest.TestCase):
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
        for index, (code, name, module) in enumerate(migration_5a.NEW_PERMISSIONS, start=1):
            permission = Permiso(id=1000 + index, codigo=code, nombre=name, descripcion=name, modulo=module)
            permissions[code] = permission
            db.session.add(permission)
        db.session.flush()
        link_id = 5000
        role_permissions = {
            "ADMINISTRADOR": EQUIPMENT_PERMISSIONS,
            "CALIDAD": EQUIPMENT_PERMISSIONS,
            "TECNICO": {"equipos.ver", "equipos.editar", "equipos.documentos.vincular"},
            "CONSULTA": {"equipos.ver"},
        }
        for role in Rol.query.all():
            for code in role_permissions[(role.nombre or "").strip().upper()]:
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
                codigo="EQ-CAL-1",
                nombre="Balanza",
                estado="activo",
                estado_operativo="OPERATIVO",
                requiere_calibracion=True,
                frecuencia_calibracion_meses=6,
            ),
            Equipo(
                id=402,
                empresa_id=102,
                codigo="EQ-CAL-2",
                nombre="Balanza externa",
                estado="activo",
                estado_operativo="OPERATIVO",
                requiere_calibracion=True,
            ),
            Equipo(
                id=403,
                empresa_id=101,
                codigo="EQ-INACTIVO",
                nombre="Equipo inactivo",
                estado="inactivo",
                estado_operativo="OPERATIVO",
                requiere_calibracion=True,
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

    def add_control(self, estado="PROGRAMADO", tipo_control="CALIBRACION", empresa_id=101, equipo_id=401, codigo="CAL-TEST"):
        control = EquipoCalibracion(
            empresa_id=empresa_id,
            equipo_id=equipo_id,
            codigo=codigo,
            tipo_control=tipo_control,
            estado=estado,
            fecha_planificada=date(2026, 8, 20),
            fecha_inicio=date(2026, 8, 20) if estado in {"EN_PROCESO", "COMPLETADO"} else None,
            fecha_finalizacion=date(2026, 8, 21) if estado == "COMPLETADO" else None,
            fecha_calibracion=date(2026, 8, 21) if estado == "COMPLETADO" else None,
            periodicidad_meses=6,
            proveedor="Laboratorio externo",
        )
        db.session.add(control)
        db.session.flush()
        return control

    def add_document_version(self, empresa_id=101, document_id=501, version_id=1501, code="DOC-CAL"):
        document = Documento(
            id=document_id,
            empresa_id=empresa_id,
            codigo=code,
            titulo="Certificado de calibracion",
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
            archivo_storage_path=f"empresa_{empresa_id}/documento/certificado.pdf",
        )
        db.session.add_all([document, version])
        db.session.flush()
        return document, version

    def test_model_schema_supports_5c1_without_parallel_table(self):
        inspector = inspect(db.engine)
        calibration_columns = {column["name"] for column in inspector.get_columns("equipo_calibraciones")}
        self.assertTrue({
            "codigo",
            "tipo_control",
            "estado",
            "fecha_planificada",
            "fecha_inicio",
            "fecha_finalizacion",
            "periodicidad_meses",
            "responsable_id",
            "costo",
            "moneda",
            "motivo_cancelacion",
        }.issubset(calibration_columns))
        self.assertIn("equipo_calibracion_documentos", inspector.get_table_names())
        self.assertEqual(EquipoCalibracion.__tablename__, "equipo_calibraciones")

    def test_service_programs_calibration_and_verification_and_records_history(self):
        admin = self.user(201)
        calibration = calibration_service.programar_control(admin, 401, {
            "codigo": "CAL-0001",
            "tipo_control": "CALIBRACION",
            "fecha_planificada": date(2026, 9, 1),
            "periodicidad_meses": 6,
            "responsable_id": 202,
            "proveedor": "Lab externo",
        })
        verification = calibration_service.programar_control(admin, 401, {
            "codigo": "VER-0001",
            "tipo_control": "VERIFICACION",
            "fecha_planificada": "2026-09-02",
        })

        self.assertEqual(calibration.estado, "PROGRAMADO")
        self.assertEqual(calibration.tipo_control, "CALIBRACION")
        self.assertEqual(calibration.responsable_id, 202)
        self.assertEqual(verification.tipo_control, "VERIFICACION")
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="CALIBRACION_PROGRAMADA").count(), 1)
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="VERIFICACION_PROGRAMADA").count(), 1)

    def test_service_rejects_invalid_type_other_company_equipment_and_inactive_equipment(self):
        admin = self.user(201)
        with self.assertRaisesRegex(EquipoCalibracionError, "CALIBRACION o VERIFICACION"):
            calibration_service.programar_control(admin, 401, {"tipo_control": "AJUSTE", "fecha_planificada": date(2026, 9, 1)})
        with self.assertRaisesRegex(EquipoCalibracionError, "no pertenece"):
            calibration_service.programar_control(admin, 402, {"tipo_control": "CALIBRACION", "fecha_planificada": date(2026, 9, 1)})
        with self.assertRaisesRegex(EquipoCalibracionError, "activo"):
            calibration_service.programar_control(admin, 403, {"tipo_control": "CALIBRACION", "fecha_planificada": date(2026, 9, 1)})

    def test_service_transitions_complete_with_result_cost_currency_and_next_date(self):
        admin = self.user(201)
        control = self.add_control(codigo="CAL-FLOW")
        calibration_service.iniciar_control(admin, control.id, date(2026, 8, 20))
        self.assertEqual(control.estado, "EN_PROCESO")
        self.assertEqual(control.fecha_inicio, date(2026, 8, 20))

        calibration_service.completar_control(admin, control.id, {
            "fecha_finalizacion": date(2026, 8, 21),
            "resultado": "APTO",
            "observaciones": "Dentro de tolerancia",
            "costo": "125.50",
            "moneda": "USD",
        })

        self.assertEqual(control.estado, "COMPLETADO")
        self.assertEqual(control.fecha_calibracion, date(2026, 8, 21))
        self.assertEqual(control.fecha_proxima, date(2027, 2, 21))
        self.assertEqual(str(control.costo), "125.50")
        self.assertEqual(control.moneda, "USD")
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="CALIBRACION_INICIADA").count(), 1)
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="CALIBRACION_COMPLETADA").count(), 1)

    def test_service_rejects_invalid_transitions_missing_result_and_invalid_completion_date(self):
        admin = self.user(201)
        programmed = self.add_control(codigo="CAL-PROG")
        completed = self.add_control(estado="COMPLETADO", codigo="CAL-CLOSED")
        in_process = self.add_control(estado="EN_PROCESO", codigo="CAL-DATE")

        with self.assertRaisesRegex(EquipoCalibracionError, "programados"):
            calibration_service.iniciar_control(admin, completed.id)
        with self.assertRaisesRegex(EquipoCalibracionError, "en proceso"):
            calibration_service.completar_control(admin, programmed.id, {"fecha_finalizacion": date(2026, 8, 21), "resultado": "APTO"})
        with self.assertRaisesRegex(EquipoCalibracionError, "obligatorio"):
            calibration_service.completar_control(admin, in_process.id, {"fecha_finalizacion": date(2026, 8, 21)})
        with self.assertRaisesRegex(EquipoCalibracionError, "anterior al inicio"):
            calibration_service.completar_control(admin, in_process.id, {"fecha_finalizacion": date(2026, 8, 19), "resultado": "APTO"})

    def test_service_cancels_open_controls_with_mandatory_reason_and_locks_cancelled(self):
        admin = self.user(201)
        control = self.add_control(estado="EN_PROCESO", codigo="CAL-CANCEL")
        with self.assertRaisesRegex(EquipoCalibracionError, "motivo"):
            calibration_service.cancelar_control(admin, control.id, "bad")

        calibration_service.cancelar_control(admin, control.id, "Proveedor no disponible")
        self.assertEqual(control.estado, "CANCELADO")
        self.assertEqual(control.cancelado_por_id, 201)
        self.assertIn("Proveedor", control.motivo_cancelacion)
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="CALIBRACION_CANCELADA").count(), 1)
        with self.assertRaisesRegex(EquipoCalibracionError, "programados o en proceso"):
            calibration_service.cancelar_control(admin, control.id, "Intento posterior")

    def test_completed_maintenance_does_not_affect_calibration_rules(self):
        admin = self.user(201)
        db.session.add(EquipoMantenimiento(
            empresa_id=101,
            equipo_id=401,
            codigo="MANT-CLOSED",
            tipo_mantenimiento="PREVENTIVO",
            estado="COMPLETADO",
            fecha_planificada=date(2026, 8, 1),
            fecha_finalizacion=date(2026, 8, 2),
        ))
        control = calibration_service.programar_control(admin, 401, {
            "codigo": "CAL-AFTER-MANT",
            "tipo_control": "CALIBRACION",
            "fecha_planificada": date(2026, 9, 1),
        })
        self.assertEqual(control.estado, "PROGRAMADO")

    def test_service_links_unlinks_evidence_and_validates_document_version_company(self):
        admin = self.user(201)
        control = self.add_control(codigo="CAL-DOC")
        document, version = self.add_document_version()
        other_document, other_version = self.add_document_version(empresa_id=102, document_id=502, version_id=1502, code="DOC-OTRA")
        wrong_document, wrong_version = self.add_document_version(document_id=503, version_id=1503, code="DOC-CAL-2")
        db.session.commit()

        with self.assertRaisesRegex(EquipoCalibracionError, "no pertenece"):
            calibration_service.vincular_evidencia_documental(admin, control.id, other_document.id, other_version.id, "CERTIFICADO")
        with self.assertRaisesRegex(EquipoCalibracionError, "no pertenece al documento"):
            calibration_service.vincular_evidencia_documental(admin, control.id, document.id, wrong_version.id, "CERTIFICADO")

        evidence = calibration_service.vincular_evidencia_documental(admin, control.id, document.id, version.id, "CERTIFICADO", "Certificado externo")
        self.assertEqual(evidence.documento_version_id, version.id)
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="EVIDENCIA_CALIBRACION_VINCULADA").count(), 1)
        calibration_service.desvincular_evidencia_documental(admin, evidence.id, "Correccion de version")
        db.session.flush()
        self.assertIsNone(db.session.get(EquipoCalibracionDocumento, evidence.id))
        self.assertEqual(EquipoHistorial.query.filter_by(tipo_evento="EVIDENCIA_CALIBRACION_DESVINCULADA").count(), 1)

    def test_service_rejects_link_and_unlink_evidence_after_completed_without_mutating(self):
        admin = self.user(201)
        control = self.add_control(estado="COMPLETADO", codigo="CAL-CERT-CLOSED")
        document, version = self.add_document_version()
        evidence = EquipoCalibracionDocumento(
            empresa_id=101,
            calibracion_id=control.id,
            documento_id=document.id,
            documento_version_id=version.id,
            tipo_evidencia="CERTIFICADO",
            vinculado_por_id=201,
        )
        db.session.add(evidence)
        db.session.commit()

        with self.assertRaisesRegex(EquipoCalibracionError, "completado"):
            calibration_service.vincular_evidencia_documental(admin, control.id, document.id, version.id, "CERTIFICADO")
        with self.assertRaisesRegex(EquipoCalibracionError, "completado"):
            calibration_service.desvincular_evidencia_documental(admin, evidence.id, "Retiro posterior")
        db.session.rollback()

        self.assertIsNotNone(db.session.get(EquipoCalibracionDocumento, evidence.id))
        self.assertEqual(EquipoCalibracionDocumento.query.filter_by(calibracion_id=control.id).count(), 1)

    def test_service_enforces_multi_company_on_control_and_evidence(self):
        admin = self.user(201)
        other_admin = self.user(205)
        control = self.add_control(codigo="CAL-EMP1")
        other_control = self.add_control(empresa_id=102, equipo_id=402, codigo="CAL-EMP2")
        document, version = self.add_document_version()
        db.session.commit()

        with self.assertRaisesRegex(EquipoCalibracionError, "no pertenece"):
            calibration_service.iniciar_control(admin, other_control.id)
        with self.assertRaisesRegex(EquipoCalibracionError, "no pertenece"):
            calibration_service.vincular_evidencia_documental(other_admin, control.id, document.id, version.id, "CERTIFICADO")
        self.assertEqual(calibration_service.controles_pendientes(admin), [control])

    def test_web_lists_controls_with_company_scope_and_basic_filters(self):
        client = self.login(201)
        calibration = self.add_control(codigo="CAL-WEB-LIST")
        verification = self.add_control(tipo_control="VERIFICACION", codigo="VER-WEB-LIST")
        self.add_control(empresa_id=102, equipo_id=402, codigo="CAL-OTHER")
        db.session.commit()

        response = client.get("/equipamiento/calibraciones")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(calibration.codigo, body)
        self.assertIn(verification.codigo, body)
        self.assertNotIn("CAL-OTHER", body)
        self.assertIn("Calibraciones y verificaciones", body)

        filtered = client.get("/equipamiento/calibraciones?tipo=VERIFICACION").get_data(as_text=True)
        self.assertIn("VER-WEB-LIST", filtered)
        self.assertNotIn("CAL-WEB-LIST", filtered)
        searched = client.get("/equipamiento/calibraciones?q=CAL-WEB").get_data(as_text=True)
        self.assertIn("CAL-WEB-LIST", searched)
        self.assertNotIn("VER-WEB-LIST", searched)

    def test_web_create_form_programs_calibration_verification_and_rejects_cross_company_equipment(self):
        client = self.login(201)
        form = client.get("/equipamiento/calibraciones/nueva")
        self.assertEqual(form.status_code, 200)
        self.assertIn("Nuevo control metrologico", form.get_data(as_text=True))
        token = self.csrf_token(client)

        response = client.post("/equipamiento/calibraciones/nueva", data={
            "csrf_token": token,
            "equipo_id": 401,
            "codigo": "CAL-WEB-CREATE",
            "tipo_control": "CALIBRACION",
            "fecha_planificada": "2026-09-01",
            "periodicidad_meses": "12",
            "responsable_id": 202,
            "proveedor": "Lab web",
        })
        self.assertEqual(response.status_code, 302)
        calibration = EquipoCalibracion.query.filter_by(codigo="CAL-WEB-CREATE").one()
        self.assertEqual(calibration.tipo_control, "CALIBRACION")
        self.assertEqual(calibration.estado, "PROGRAMADO")

        response = client.post("/equipamiento/calibraciones/nueva", data={
            "csrf_token": token,
            "equipo_id": 401,
            "codigo": "VER-WEB-CREATE",
            "tipo_control": "VERIFICACION",
            "fecha_planificada": "2026-09-02",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(EquipoCalibracion.query.filter_by(codigo="VER-WEB-CREATE", tipo_control="VERIFICACION").first())

        response = client.post("/equipamiento/calibraciones/nueva", data={
            "csrf_token": token,
            "equipo_id": 402,
            "codigo": "CAL-CROSS",
            "tipo_control": "CALIBRACION",
            "fecha_planificada": "2026-09-03",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(EquipoCalibracion.query.filter_by(codigo="CAL-CROSS").first())

    def test_web_detail_access_state_actions_complete_and_next_date(self):
        client = self.login(201)
        control = self.add_control(codigo="CAL-WEB-FLOW")
        other_control = self.add_control(empresa_id=102, equipo_id=402, codigo="CAL-WEB-OTHER")
        db.session.commit()

        detail = client.get(f"/equipamiento/calibraciones/{control.id}")
        body = detail.get_data(as_text=True)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("CAL-WEB-FLOW", body)
        self.assertIn("Iniciar", body)
        self.assertEqual(client.get(f"/equipamiento/calibraciones/{other_control.id}").status_code, 404)
        token = self.csrf_token(client)

        response = client.post(f"/equipamiento/calibraciones/{control.id}/iniciar", data={
            "csrf_token": token,
            "fecha_inicio": "2026-08-16",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(control.estado, "EN_PROCESO")
        body = client.get(f"/equipamiento/calibraciones/{control.id}").get_data(as_text=True)
        self.assertIn("Completar", body)
        self.assertNotIn("<h5 class=\"mb-3\">Iniciar control</h5>", body)

        response = client.post(f"/equipamiento/calibraciones/{control.id}/completar", data={
            "csrf_token": token,
            "fecha_finalizacion": "2026-08-16",
            "resultado": "APTO",
            "costo": "80.00",
            "moneda": "USD",
            "observaciones": "Control finalizado",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(control.estado, "COMPLETADO")
        body = client.get(f"/equipamiento/calibraciones/{control.id}").get_data(as_text=True)
        self.assertIn("APTO", body)
        self.assertIn("80.00", body)
        self.assertIn("2027-02-16", body)
        self.assertNotIn("<h5 class=\"mb-3\">Completar control</h5>", body)

    def test_web_cancel_requires_reason_and_turns_detail_read_only(self):
        client = self.login(201)
        control = self.add_control(codigo="VER-WEB-CANCEL", tipo_control="VERIFICACION")
        document, version = self.add_document_version()
        evidence = EquipoCalibracionDocumento(
            empresa_id=101,
            calibracion_id=control.id,
            documento_id=document.id,
            documento_version_id=version.id,
            tipo_evidencia="CERTIFICADO",
            vinculado_por_id=201,
        )
        db.session.add(evidence)
        db.session.commit()
        client.get(f"/equipamiento/calibraciones/{control.id}")
        token = self.csrf_token(client)

        response = client.post(f"/equipamiento/calibraciones/{control.id}/cancelar", data={
            "csrf_token": token,
            "motivo": "bad",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(control.estado, "PROGRAMADO")

        response = client.post(f"/equipamiento/calibraciones/{control.id}/cancelar", data={
            "csrf_token": token,
            "motivo": "Cancelacion autorizada",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(control.estado, "CANCELADO")
        body = client.get(f"/equipamiento/calibraciones/{control.id}").get_data(as_text=True)
        self.assertIn("Cancelacion autorizada", body)
        self.assertIn("DOC-CAL", body)
        self.assertNotIn("Vincular", body)
        self.assertNotIn("Desvincular", body)
        self.assertNotIn("Iniciar", body)
        self.assertNotIn("Completar", body)

    def test_web_evidence_selector_link_unlink_and_completed_read_only(self):
        client = self.login(201)
        control = self.add_control(codigo="CAL-WEB-EVID")
        document, version = self.add_document_version()
        other_document, other_version = self.add_document_version(document_id=503, version_id=1503, code="DOC-CAL-2")
        other_company_document, other_company_version = self.add_document_version(empresa_id=102, document_id=502, version_id=1502, code="DOC-OTRA")
        db.session.commit()

        detail = client.get(f"/equipamiento/calibraciones/{control.id}")
        body = detail.get_data(as_text=True)
        self.assertIn('id="calibracion-documento-select"', body)
        self.assertIn('id="calibracion-version-select" required disabled', body)
        version_data = body.split('<script type="application/json" id="calibracion-versiones-data">', 1)[1].split("</script>", 1)[0]
        self.assertIn(f'"documento_id": {document.id}', version_data)
        self.assertIn(f'"documento_id": {other_document.id}', version_data)
        self.assertNotIn("DOC-OTRA", body)
        token = self.csrf_token(client)

        bad = client.post(f"/equipamiento/calibraciones/{control.id}/evidencias", data={
            "csrf_token": token,
            "documento_id": document.id,
            "documento_version_id": other_version.id,
            "tipo_evidencia": "CERTIFICADO",
        })
        self.assertEqual(bad.status_code, 302)
        self.assertEqual(EquipoCalibracionDocumento.query.filter_by(calibracion_id=control.id).count(), 0)

        response = client.post(f"/equipamiento/calibraciones/{control.id}/evidencias", data={
            "csrf_token": token,
            "documento_id": document.id,
            "documento_version_id": version.id,
            "tipo_evidencia": "CERTIFICADO",
            "observaciones": "Certificado web",
        })
        self.assertEqual(response.status_code, 302)
        evidence = EquipoCalibracionDocumento.query.filter_by(calibracion_id=control.id).one()
        body = client.get(f"/equipamiento/calibraciones/{control.id}").get_data(as_text=True)
        self.assertIn("Certificado web", body)
        self.assertIn("Desvincular", body)

        response = client.post(f"/equipamiento/calibraciones/evidencias/{evidence.id}/desvincular", data={
            "csrf_token": token,
            "motivo": "Cambio de certificado",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(EquipoCalibracionDocumento.query.filter_by(calibracion_id=control.id).count(), 0)

        evidence = calibration_service.vincular_evidencia_documental(self.user(201), control.id, document.id, version.id, "CERTIFICADO", "Final")
        calibration_service.iniciar_control(self.user(201), control.id, date(2026, 8, 20))
        calibration_service.completar_control(self.user(201), control.id, {
            "fecha_finalizacion": date(2026, 8, 21),
            "resultado": "APTO",
        })
        db.session.commit()
        body = client.get(f"/equipamiento/calibraciones/{control.id}").get_data(as_text=True)
        self.assertIn("Final", body)
        self.assertNotIn('id="calibracion-documento-select"', body)
        self.assertNotIn("Vincular", body)
        self.assertNotIn("Desvincular", body)
        response = client.post(f"/equipamiento/calibraciones/evidencias/{evidence.id}/desvincular", data={
            "csrf_token": token,
            "motivo": "Retiro posterior",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(db.session.get(EquipoCalibracionDocumento, evidence.id))

    def test_web_equipment_detail_shows_metrology_controls_and_history_events(self):
        client = self.login(201)
        admin = self.user(201)
        control = calibration_service.programar_control(admin, 401, {
            "codigo": "CAL-EQ-DETAIL",
            "tipo_control": "CALIBRACION",
            "fecha_planificada": date(2026, 9, 1),
        })
        db.session.commit()

        response = client.get("/equipamiento/equipos/401")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Calibraciones y verificaciones", body)
        self.assertIn("CAL-EQ-DETAIL", body)
        self.assertIn(f"/equipamiento/calibraciones/{control.id}", body)
        self.assertIn("CALIBRACION PROGRAMADA", body)


if __name__ == "__main__":
    unittest.main()
