import unittest
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import (
    CLASIFICACION_CONTROL_FORMATO,
    CLASIFICACION_CONTROL_INTERNO,
    DOCUMENTO_VIGOR_EXTERNO,
    DOCUMENTO_VIGOR_FORMATO,
    DOCUMENTO_VIGOR_INTERNO,
    ESTADO_VIGENTE,
    PUBLICACION_ACTIVA,
    Documento,
    DocumentoPublicacion,
    DocumentoVersion,
    DocumentoVigorCatalogo,
)
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol


class DocumentCurrentCatalogViewTest(unittest.TestCase):
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
        self.next_id = 90000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        self.seed()
        db.session.commit()

    def tearDown(self):
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def seed(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa uno"),
            Empresa(id=102, nombre="Empresa dos"),
            Usuario(id=201, empresa_id=101, nombre="Calidad", apellido="Uno", email="calidad@catalogo", username="calidad-catalogo", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Sin", apellido="Permiso", email="sin@catalogo", username="sin-catalogo", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=102, nombre="Calidad", apellido="Dos", email="calidad2@catalogo", username="calidad2-catalogo", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=101, nombre="Solo", apellido="Ver", email="solo@catalogo", username="solo-ver-catalogo", password_hash="x", activo=True),
        ])
        permissions = [
            Permiso(id=1001, codigo="documentos.ver", nombre="Ver documentos", modulo="documentos"),
            Permiso(id=1002, codigo="documentos.descargar", nombre="Descargar documentos", modulo="documentos"),
            Permiso(id=1003, codigo="documentos.ver_historial", nombre="Ver historial", modulo="documentos"),
        ]
        full_role = Rol(id=2001, nombre="CATALOGO_COMPLETO", es_sistema=True)
        view_role = Rol(id=2002, nombre="CATALOGO_VER", es_sistema=True)
        no_role = Rol(id=2003, nombre="SIN_ACCESO", es_sistema=True)
        db.session.add_all([*permissions, full_role, view_role, no_role])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=full_role.id, permiso_id=1001),
            RolPermiso(id=3002, rol_id=full_role.id, permiso_id=1002),
            RolPermiso(id=3003, rol_id=full_role.id, permiso_id=1003),
            RolPermiso(id=3004, rol_id=view_role.id, permiso_id=1001),
            UsuarioRol(id=4001, usuario_id=201, rol_id=full_role.id),
            UsuarioRol(id=4002, usuario_id=203, rol_id=full_role.id),
            UsuarioRol(id=4003, usuario_id=204, rol_id=view_role.id),
            UsuarioRol(id=4004, usuario_id=202, rol_id=no_role.id),
        ])

        self.add_document_catalog(
            document_id=501,
            version_id=1501,
            publication_id=2501,
            empresa_id=101,
            codigo="INT-CAT-01",
            titulo="Procedimiento interno vigente",
            tipo_documento="PROCEDIMIENTO",
            clasificacion=CLASIFICACION_CONTROL_INTERNO,
            tipo_listado=DOCUMENTO_VIGOR_INTERNO,
            sync=True,
        )
        self.add_document_catalog(
            document_id=502,
            version_id=1502,
            publication_id=2502,
            empresa_id=101,
            codigo="FOR-CAT-01",
            titulo="Formato vigente controlado",
            tipo_documento="FORMATO",
            clasificacion=CLASIFICACION_CONTROL_FORMATO,
            tipo_listado=DOCUMENTO_VIGOR_FORMATO,
            sync=True,
        )
        self.add_document_catalog(
            document_id=601,
            version_id=1601,
            publication_id=2601,
            empresa_id=102,
            codigo="INT-OTRA-01",
            titulo="Documento otra empresa",
            tipo_documento="PROCEDIMIENTO",
            clasificacion=CLASIFICACION_CONTROL_INTERNO,
            tipo_listado=DOCUMENTO_VIGOR_INTERNO,
            sync=True,
        )
        db.session.add_all([
            self.catalog_row(
                empresa_id=101,
                tipo_listado=DOCUMENTO_VIGOR_EXTERNO,
                codigo="EXT-CAT-ISO",
                titulo="Norma externa vigente",
                revision="2025",
                fuente_fila=20,
            ),
            self.catalog_row(
                empresa_id=101,
                tipo_listado=DOCUMENTO_VIGOR_INTERNO,
                codigo="NULL-REL",
                titulo="Registro sin relaciones",
                revision="00",
                fuente_fila=30,
            ),
            self.catalog_row(
                empresa_id=101,
                tipo_listado=DOCUMENTO_VIGOR_INTERNO,
                codigo="INT-CAT-01-OLD",
                titulo="Duplicado historico vinculado",
                revision="0",
                documento_id=501,
                documento_version_id=1501,
                documento_publicacion_id=2501,
                fuente_fila=31,
            ),
        ])

    def add_document_catalog(self, *, document_id, version_id, publication_id, empresa_id, codigo, titulo, tipo_documento, clasificacion, tipo_listado, sync=False):
        document = Documento(
            id=document_id,
            empresa_id=empresa_id,
            codigo=codigo,
            titulo=titulo,
            tipo_documento=tipo_documento,
            clasificacion_control=clasificacion,
            estado=ESTADO_VIGENTE,
            version_actual="1",
            elaborado_por_id=201 if empresa_id == 101 else 203,
        )
        version = DocumentoVersion(
            id=version_id,
            empresa_id=empresa_id,
            documento_id=document_id,
            version="1",
            estado=ESTADO_VIGENTE,
            elaborado_por_id=document.elaborado_por_id,
        )
        document.version_vigente_id = version.id
        publication = DocumentoPublicacion(
            id=publication_id,
            empresa_id=empresa_id,
            documento_id=document_id,
            documento_version_id=version_id,
            public_id=f"pub-{publication_id}",
            token=f"token-{publication_id}",
            estado=PUBLICACION_ACTIVA,
            activa=True,
            qr_payload=f"https://labzeniso.test/documentos/publicados/pub-{publication_id}",
            vigente_desde=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )
        row = self.catalog_row(
            empresa_id=empresa_id,
            tipo_listado=tipo_listado,
            codigo=codigo,
            titulo=titulo,
            revision=version.version,
            documento_id=document_id,
            documento_version_id=version_id,
            documento_publicacion_id=publication_id,
            sincronizado_en=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc) if sync else None,
            fuente_fila=document_id,
        )
        db.session.add_all([document, version, publication, row])

    def catalog_row(
        self,
        *,
        empresa_id,
        tipo_listado,
        codigo,
        titulo,
        revision,
        fuente_fila,
        documento_id=None,
        documento_version_id=None,
        documento_publicacion_id=None,
        sincronizado_en=None,
    ):
        return DocumentoVigorCatalogo(
            empresa_id=empresa_id,
            tipo_listado=tipo_listado,
            clave_importacion=f"{empresa_id}-{tipo_listado}-{codigo}-{fuente_fila}",
            identidad_estable=f"CODIGO:{codigo}#1",
            ordinal_identidad=1,
            codigo=codigo,
            titulo=titulo,
            revision=revision,
            fecha_vigencia=datetime(2026, 8, 9, tzinfo=timezone.utc).date(),
            custodio="Calidad",
            acceso_documento="Controlado",
            lugar_almacenamiento="SharePoint",
            proteccion="Solo lectura",
            medio="PDF",
            destino_final="Archivo",
            seccion="DOCUMENTOS",
            activo=True,
            documento_id=documento_id,
            documento_version_id=documento_version_id,
            documento_publicacion_id=documento_publicacion_id,
            fuente_archivo="PUBLICACION_AUTOMATICA" if sincronizado_en else "vigor.xlsx",
            fuente_hoja="publish_as_current" if sincronizado_en else "C",
            fuente_fila=fuente_fila,
            importado_en=datetime.now(timezone.utc),
            sincronizado_en=sincronizado_en,
        )

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def body(self, path="/documentacion/documentos-vigentes", user_id=201):
        response = self.login(user_id).get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def sidebar(self, body):
        start = body.index('<aside class="sidebar">')
        end = body.index("</aside>", start) + len("</aside>")
        return body[start:end]

    def test_route_requires_authentication(self):
        response = self.app.test_client().get("/documentacion/documentos-vigentes")

        self.assertEqual(response.status_code, 302)

    def test_route_requires_document_view_permission(self):
        response = self.login(202).get("/documentacion/documentos-vigentes")

        self.assertEqual(response.status_code, 403)

    def test_lists_current_company_catalog_and_classifications(self):
        body = self.body()

        self.assertIn("Documentos vigentes", body)
        self.assertIn("INT-CAT-01", body)
        self.assertIn("Procedimiento interno vigente", body)
        self.assertIn("FOR-CAT-01", body)
        self.assertIn("Formato vigente controlado", body)
        self.assertIn("EXT-CAT-ISO", body)
        self.assertIn("INTERNO", body)
        self.assertIn("FORMATO", body)
        self.assertIn("EXTERNO", body)
        self.assertNotIn("INT-OTRA-01", body)

    def test_second_company_only_sees_own_records(self):
        body = self.body(user_id=203)

        self.assertIn("INT-OTRA-01", body)
        self.assertNotIn("INT-CAT-01", body)

    def test_search_by_code_and_title(self):
        code_body = self.body("/documentacion/documentos-vigentes?q=for-cat-01")
        self.assertIn("FOR-CAT-01", code_body)
        self.assertNotIn("INT-CAT-01", code_body)

        title_body = self.body("/documentacion/documentos-vigentes?q=norma+externa")
        self.assertIn("EXT-CAT-ISO", title_body)
        self.assertNotIn("FOR-CAT-01", title_body)

    def test_filters_by_classification_type_and_state_without_cross_tenant_leak(self):
        formato = self.body("/documentacion/documentos-vigentes?clasificacion=FORMATO&empresa_id=102")
        self.assertIn("FOR-CAT-01", formato)
        self.assertNotIn("INT-CAT-01", formato)
        self.assertNotIn("INT-OTRA-01", formato)

        tipo = self.body("/documentacion/documentos-vigentes?tipo_documento=PROCEDIMIENTO")
        self.assertIn("INT-CAT-01", tipo)
        self.assertNotIn("FOR-CAT-01", tipo)

        vigente = self.body("/documentacion/documentos-vigentes?estado=VIGENTE")
        self.assertIn("INT-CAT-01", vigente)
        self.assertNotIn("NULL-REL", vigente)

    def test_listing_avoids_duplicate_rows_for_same_document(self):
        body = self.body()

        self.assertEqual(body.count("INT-CAT-01"), 1)
        self.assertNotIn("INT-CAT-01-OLD", body)

    def test_null_relations_and_empty_state_render_without_error(self):
        body = self.body("/documentacion/documentos-vigentes?estado=SIN_RELACION")

        self.assertIn("NULL-REL", body)
        self.assertIn("Sin relaci", body)

        DocumentoVigorCatalogo.query.filter_by(empresa_id=101).delete()
        db.session.commit()
        empty = self.body()
        self.assertIn("No existen documentos vigentes registrados para esta empresa", empty)

    def test_sidebar_link_visibility_and_active_state(self):
        body = self.body()
        sidebar = self.sidebar(body)

        self.assertIn("2. Documentación", sidebar)
        self.assertIn("Documentos", sidebar)
        self.assertIn("/documentacion/", sidebar)
        self.assertNotIn("Documentos vigentes", sidebar)
        self.assertNotIn("/documentacion/documentos-vigentes", sidebar)
        self.assertIn('class="sidebar-link active"', sidebar)

    def test_document_index_shows_moved_links_without_edit_only_action_for_viewer(self):
        body = self.body("/documentacion/", user_id=204)

        self.assertIn("Accesos documentales", body)
        self.assertIn("Vista explorador", body)
        self.assertIn("/documentacion/explorador", body)
        self.assertIn("Documentos vigentes", body)
        self.assertIn("/documentacion/documentos-vigentes", body)
        self.assertNotIn("Clasificacion pendiente", body)
        self.assertNotIn("/documentacion/clasificacion/pendientes", body)

    def test_actions_for_user_with_full_permissions(self):
        full = self.body()
        self.assertIn("Detalle", full)
        self.assertIn("Ver vigente", full)
        self.assertIn("Descargar", full)
        self.assertIn("Historial", full)

    def test_actions_hide_download_and_history_without_permissions(self):
        view_only = self.body(user_id=204)
        self.assertIn("Detalle", view_only)
        self.assertIn("Ver vigente", view_only)
        self.assertNotIn("/pdf", view_only)
        self.assertNotIn("#historial", view_only)

    def test_cross_tenant_document_detail_id_is_not_accessible(self):
        response = self.login(201).get("/documentacion/601")

        self.assertEqual(response.status_code, 404)

    def test_existing_document_views_still_work(self):
        client = self.login(201)

        self.assertEqual(client.get("/documentacion/").status_code, 200)
        self.assertEqual(client.get("/documentacion/explorador").status_code, 200)
        self.assertEqual(client.get("/documentacion/vigor/internos").status_code, 200)


if __name__ == "__main__":
    unittest.main()
