import unittest
from datetime import date, datetime

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import (
    DOCUMENTO_VIGOR_EXTERNO,
    DOCUMENTO_VIGOR_FORMATO,
    DOCUMENTO_VIGOR_INTERNO,
    DocumentoVigorCatalogo,
)
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol


class DocumentVigorViewsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
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
        self.seed_security()
        self.seed_catalog()
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def seed_security(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="calidad@vigor", username="calidad", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin@vigor", username="sinpermiso", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=102, nombre="Calidad", apellido="Dos", email="calidad2@vigor", username="calidad2", password_hash="x", activo=True),
        ])
        permission = Permiso(id=1001, codigo="documentos.ver", nombre="Ver documentos", modulo="documentos")
        viewer = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        no_access = Rol(id=2002, nombre="SIN_ACCESO", es_sistema=True)
        db.session.add_all([permission, viewer, no_access])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=viewer.id, permiso_id=permission.id),
            UsuarioRol(id=4001, usuario_id=201, rol_id=viewer.id),
            UsuarioRol(id=4002, usuario_id=203, rol_id=viewer.id),
            UsuarioRol(id=4003, usuario_id=202, rol_id=no_access.id),
        ])

    def catalog_item(
        self,
        *,
        empresa_id=101,
        tipo_listado=DOCUMENTO_VIGOR_INTERNO,
        codigo,
        titulo,
        revision="00",
        custodio="Calidad",
        seccion="DOCUMENTOS",
        fuente_fila=1,
        activo=True,
        fecha_vigencia=None,
        ordinal=1,
    ):
        identity = f"CODIGO:{codigo}#{ordinal}" if codigo else f"SIN_CODIGO:{fuente_fila}#{ordinal}"
        return DocumentoVigorCatalogo(
            empresa_id=empresa_id,
            tipo_listado=tipo_listado,
            clave_importacion=f"{tipo_listado}-{empresa_id}-{identity}",
            identidad_estable=identity,
            ordinal_identidad=ordinal,
            codigo=codigo,
            titulo=titulo,
            revision=revision,
            fecha_vigencia=fecha_vigencia,
            custodio=custodio,
            acceso_documento="Controlado",
            lugar_almacenamiento="SharePoint",
            proteccion="Solo lectura",
            medio="ELECTRONICO",
            destino_final="Archivo",
            seccion=seccion,
            activo=activo,
            fuente_archivo="vigor.xlsx",
            fuente_hoja="C",
            fuente_fila=fuente_fila,
            importado_en=datetime.now(),
        )

    def seed_catalog(self):
        rows = []
        for index in range(1, 31):
            rows.append(self.catalog_item(
                codigo=f"INT-PAG-{index:02d}",
                titulo=f"Procedimiento paginado {index:02d}",
                revision="00" if index < 28 else "01",
                custodio="Custodio Alfa" if index == 5 else "Calidad",
                seccion="Seccion A" if index <= 15 else "Seccion B",
                fuente_fila=index,
                fecha_vigencia=date(2026, 1, min(index, 28)),
            ))
        rows.extend([
            self.catalog_item(codigo="INT-INACTIVO", titulo="No visible", fuente_fila=40, activo=False),
            self.catalog_item(empresa_id=102, codigo="INT-OTRA-EMPRESA", titulo="Otra empresa", seccion="Seccion Otra", fuente_fila=1),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_EXTERNO, codigo="DOCEXT/LI/42", titulo=None, revision=None, custodio=None, seccion="DOCUMENTOS", fuente_fila=53),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_EXTERNO, codigo="EXT-ISO", titulo="Norma ISO externa", revision="2025", custodio="Responsable externo", seccion="NORMAS", fuente_fila=54),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_EXTERNO, empresa_id=102, codigo="EXT-OTRA", titulo="Externo otra empresa", seccion="NORMAS B", fuente_fila=1),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_FORMATO, codigo="PGT/LI/01-FO02", titulo="Registro con fecha invalida", fecha_vigencia=None, seccion="FORMATOS", fuente_fila=48),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_FORMATO, codigo="PGT/LI/01-FO04", titulo="Registro de capacitaciones", seccion="FORMATOS", fuente_fila=50, ordinal=1),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_FORMATO, codigo="PGT/LI/01-FO04", titulo="Historial de operaciones", seccion="FORMATOS", fuente_fila=57, ordinal=2),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_FORMATO, codigo="PGT/LI/01-FO05", titulo="Evaluacion de capacitacion", seccion="FORMATOS", fuente_fila=51, ordinal=1),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_FORMATO, codigo="PGT/LI/01-FO05", titulo="Plan anual de mantenimiento", seccion="FORMATOS", fuente_fila=58, ordinal=2),
            self.catalog_item(tipo_listado=DOCUMENTO_VIGOR_FORMATO, empresa_id=102, codigo="FOR-OTRA", titulo="Formato otra empresa", seccion="FORMATOS B", fuente_fila=1),
        ])
        db.session.add_all(rows)

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def body(self, path, user_id=201):
        response = self.login(user_id).get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_unauthenticated_user_is_redirected(self):
        response = self.app.test_client().get("/documentacion/vigor/internos")
        self.assertEqual(response.status_code, 302)

    def test_authenticated_user_without_permission_is_forbidden(self):
        response = self.login(202).get("/documentacion/vigor/internos")
        self.assertEqual(response.status_code, 403)

    def test_authorized_user_can_open_all_vigor_views(self):
        client = self.login(201)
        for path, title in (
            ("/documentacion/vigor/internos", "Documentos internos en vigor"),
            ("/documentacion/vigor/externos", "Documentos externos en vigor"),
            ("/documentacion/vigor/formatos", "Formatos en vigor"),
        ):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(title, response.get_data(as_text=True))

    def test_visual_structure_uses_responsive_header_table_and_metadata_details(self):
        body = self.body("/documentacion/vigor/formatos?per_page=100")

        self.assertIn("vigor-heading d-flex", body)
        self.assertIn("vigor-heading-main", body)
        self.assertIn("vigor-heading-summary", body)
        self.assertIn("table-responsive vigor-table-wrap", body)
        self.assertIn("table table-hover align-middle vigor-table", body)
        self.assertIn("vigor-col-code", body)
        self.assertIn("vigor-col-section", body)
        self.assertIn("<details class=\"vigor-metadata\">", body)
        self.assertIn("<summary>Ver</summary>", body)
        self.assertIn("<strong>Acceso:</strong>", body)
        self.assertIn("<strong>Destino:</strong>", body)

    def test_base_layout_constrains_main_area_after_sidebar(self):
        body = self.body("/documentacion/vigor/internos")

        self.assertIn(".admin-layout", body)
        self.assertIn(".layout-main", body)
        self.assertIn("flex: 1 1 0;", body)
        self.assertIn("width: 0;", body)
        self.assertIn("max-width: calc(100% - 280px);", body)
        self.assertIn(".topbar > .d-flex:last-child", body)
        self.assertIn(".content-area", body)
        self.assertIn("box-sizing: border-box;", body)

    def test_existing_document_index_uses_same_constrained_admin_layout(self):
        body = self.body("/documentacion/")

        self.assertIn("Gesti", body)
        self.assertIn(".layout-main", body)
        self.assertIn("max-width: calc(100% - 280px);", body)
        self.assertIn(".topbar > .d-flex:last-child", body)

    def test_filter_buttons_can_wrap_without_forcing_horizontal_overflow(self):
        body = self.body("/documentacion/vigor/internos")

        self.assertIn("d-flex flex-wrap gap-2 vigor-filter-actions", body)
        self.assertIn("Limpiar filtros", body)

    def test_endpoints_are_fixed_to_their_document_type(self):
        self.assertIn("INT-PAG-01", self.body("/documentacion/vigor/internos"))
        self.assertNotIn("EXT-ISO", self.body("/documentacion/vigor/internos"))
        self.assertIn("EXT-ISO", self.body("/documentacion/vigor/externos"))
        self.assertNotIn("INT-PAG-01", self.body("/documentacion/vigor/externos"))
        self.assertIn("PGT/LI/01-FO02", self.body("/documentacion/vigor/formatos"))
        self.assertNotIn("EXT-ISO", self.body("/documentacion/vigor/formatos"))

    def test_strict_company_isolation_and_query_string_cannot_select_company(self):
        body = self.body("/documentacion/vigor/internos?empresa_id=102&per_page=100")
        self.assertIn("INT-PAG-01", body)
        self.assertNotIn("INT-OTRA-EMPRESA", body)

    def test_second_company_user_only_sees_own_company(self):
        other_body = self.body("/documentacion/vigor/internos?empresa_id=101", user_id=203)
        self.assertIn("INT-OTRA-EMPRESA", other_body)
        self.assertNotIn("INT-PAG-01", other_body)

    def test_only_active_records_are_visible(self):
        body = self.body("/documentacion/vigor/internos?per_page=100")
        self.assertNotIn("INT-INACTIVO", body)

    def test_filter_by_code_title_custodian_revision_and_section(self):
        self.assertIn("INT-PAG-05", self.body("/documentacion/vigor/internos?q=int-pag-05"))
        self.assertNotIn("INT-PAG-06", self.body("/documentacion/vigor/internos?q=int-pag-05"))
        self.assertIn("Procedimiento paginado 06", self.body("/documentacion/vigor/internos?q=PAGINADO 06"))
        self.assertIn("INT-PAG-05", self.body("/documentacion/vigor/internos?q=custodio alfa"))
        revision_body = self.body("/documentacion/vigor/internos?revision=01&per_page=100")
        self.assertIn("INT-PAG-28", revision_body)
        self.assertNotIn("INT-PAG-01", revision_body)
        section_body = self.body("/documentacion/vigor/internos?seccion=Seccion+B&per_page=100")
        self.assertIn("INT-PAG-16", section_body)
        self.assertNotIn("INT-PAG-01", section_body)

    def test_search_tolerates_null_fields_and_no_results(self):
        body = self.body("/documentacion/vigor/externos?q=docext")
        self.assertIn("DOCEXT/LI/42", body)
        self.assertIn("—", body)
        empty = self.body("/documentacion/vigor/externos?q=no-existe")
        self.assertIn("No existen registros para los filtros seleccionados.", empty)

    def test_default_pagination_and_allowed_per_page_values(self):
        default_body = self.body("/documentacion/vigor/internos")
        self.assertIn("Página 1 de 2", default_body)
        self.assertIn("INT-PAG-25", default_body)
        self.assertNotIn("INT-PAG-26", default_body)
        self.assertIn("INT-PAG-30", self.body("/documentacion/vigor/internos?per_page=50"))
        self.assertIn("INT-PAG-30", self.body("/documentacion/vigor/internos?per_page=100"))
        invalid_body = self.body("/documentacion/vigor/internos?per_page=999")
        self.assertIn("Página 1 de 2", invalid_body)
        self.assertNotIn("INT-PAG-26", invalid_body)

    def test_out_of_range_page_does_not_500_and_pagination_preserves_filters(self):
        response = self.login(201).get("/documentacion/vigor/internos?page=99")
        self.assertEqual(response.status_code, 200)
        body = self.body("/documentacion/vigor/internos?q=INT-PAG&per_page=25")
        self.assertIn("q=INT-PAG", body)
        self.assertIn("per_page=25", body)

    def test_null_dates_titles_and_duplicate_codes_render(self):
        external = self.body("/documentacion/vigor/externos?q=DOCEXT/LI/42")
        self.assertIn("DOCEXT/LI/42", external)
        self.assertIn("—", external)
        formats = self.body("/documentacion/vigor/formatos?per_page=100")
        self.assertIn("PGT/LI/01-FO02", formats)
        self.assertIn("Registro con fecha invalida", formats)
        self.assertEqual(formats.count("PGT/LI/01-FO04"), 2)
        self.assertEqual(formats.count("PGT/LI/01-FO05"), 2)

    def test_section_selector_is_isolated_by_company_and_type(self):
        internal = self.body("/documentacion/vigor/internos")
        self.assertIn("Seccion A", internal)
        self.assertNotIn("FORMATOS", internal)
        self.assertNotIn("Seccion Otra", internal)

    def test_section_selector_uses_current_company(self):
        other_company = self.body("/documentacion/vigor/internos", user_id=203)
        self.assertIn("Seccion Otra", other_company)
        self.assertNotIn("Seccion A", other_company)

    def test_get_routes_do_not_write_records(self):
        before = DocumentoVigorCatalogo.query.count()
        client = self.login(201)
        client.get("/documentacion/vigor/internos?q=INT")
        client.get("/documentacion/vigor/externos")
        client.get("/documentacion/vigor/formatos?per_page=50")
        self.assertEqual(DocumentoVigorCatalogo.query.count(), before)


if __name__ == "__main__":
    unittest.main()
