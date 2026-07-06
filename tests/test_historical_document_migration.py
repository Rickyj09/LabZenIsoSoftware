import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

from werkzeug.datastructures import FileStorage

from app import create_app
from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.empresa import Empresa
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_migration_service import migrate_historical_document_files
from app.services.storage_service import (
    apply_stored_file_metadata,
    resolve_document_path,
    store_document_file,
)


class HistoricalDocumentMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.private_root = self.root / "private"
        self.legacy_root = self.root / "legacy"
        self.legacy_root.mkdir(parents=True)

        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DOCUMENT_STORAGE_ROOT": str(self.private_root),
            "DOCUMENT_LEGACY_STORAGE_ROOT": str(self.legacy_root),
            "DOCUMENT_MAX_FILE_SIZE": 1024 * 1024,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        empresa_1 = Empresa(id=101, nombre="Empresa uno")
        empresa_2 = Empresa(id=102, nombre="Empresa dos")
        usuario_1 = Usuario(
            id=201,
            empresa_id=101,
            nombre="Usuario",
            apellido="Uno",
            email="uno@example.test",
            username="usuario-uno",
            password_hash="test",
            activo=True,
        )
        usuario_2 = Usuario(
            id=202,
            empresa_id=102,
            nombre="Usuario",
            apellido="Dos",
            email="dos@example.test",
            username="usuario-dos",
            password_hash="test",
            activo=True,
        )
        documento = Documento(
            id=301,
            empresa_id=101,
            codigo="DOC-TEST-001",
            titulo="Documento de prueba",
            tipo_documento="PROCEDIMIENTO",
            estado="BORRADOR",
            version_actual="1",
            elaborado_por_id=201,
        )
        db.session.add_all([empresa_1, empresa_2, usuario_1, usuario_2, documento])
        download_role = Rol(id=501, nombre="TEST_DOWNLOAD", es_sistema=False)
        download_permission = Permiso(
            id=502,
            codigo="documentos.descargar",
            nombre="Descargar documentos",
            modulo="documentos",
        )
        db.session.add_all([download_role, download_permission])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=503, rol_id=download_role.id, permiso_id=download_permission.id),
            UsuarioRol(id=504, usuario_id=201, rol_id=download_role.id),
            UsuarioRol(id=505, usuario_id=202, rol_id=download_role.id),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def add_version(self, *, version_id, archivo_url=None):
        version_doc = DocumentoVersion(
            id=version_id,
            empresa_id=101,
            documento_id=301,
            version=str(version_id),
            archivo_url=archivo_url,
            fecha_version=date.today(),
            estado="BORRADOR",
        )
        db.session.add(version_doc)
        db.session.commit()
        return version_doc

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def test_dry_run_does_not_copy_or_update_database(self):
        legacy = self.legacy_root / "historico.pdf"
        legacy.write_bytes("documento histórico".encode("utf-8"))
        version_doc = self.add_version(
            version_id=401,
            archivo_url="/static/uploads/documentos/historico.pdf",
        )

        summary = migrate_historical_document_files(apply=False)

        db.session.refresh(version_doc)
        self.assertEqual(summary.encontrados, 1)
        self.assertEqual(summary.simulados, 1)
        self.assertEqual(summary.migrados, 0)
        self.assertIsNone(version_doc.archivo_storage_path)
        self.assertEqual(list(self.private_root.rglob("*")), [])

    def test_apply_copies_updates_metadata_and_preserves_legacy_file(self):
        legacy = self.legacy_root / "historico.pdf"
        legacy.write_bytes("documento histórico".encode("utf-8"))
        version_doc = self.add_version(
            version_id=402,
            archivo_url="/static/uploads/documentos/historico.pdf",
        )

        summary = migrate_historical_document_files(apply=True)

        db.session.refresh(version_doc)
        self.assertEqual(summary.migrados, 1)
        self.assertEqual(len(version_doc.archivo_sha256), 64)
        self.assertEqual(version_doc.archivo_size, len("documento histórico".encode("utf-8")))
        self.assertTrue(resolve_document_path(version_doc.archivo_storage_path).is_file())
        self.assertTrue(legacy.is_file())

    def test_invalid_legacy_reference_is_reported_as_omitted(self):
        self.add_version(version_id=407, archivo_url="C:\\ruta-local-no-permitida")

        summary = migrate_historical_document_files(apply=False)

        self.assertEqual(summary.encontrados, 1)
        self.assertEqual(summary.omitidos, 1)
        self.assertEqual(summary.errores, 0)

    def test_downloads_migrated_file(self):
        version_doc = self.add_version(version_id=403)
        upload = FileStorage(
            stream=BytesIO(b"archivo privado"),
            filename="privado.pdf",
            content_type="application/pdf",
        )
        stored = store_document_file(
            upload,
            documento=version_doc.documento,
            version=version_doc.version,
        )
        apply_stored_file_metadata(version_doc, stored)
        db.session.commit()

        response = self.login(201).get(f"/documentacion/version/{version_doc.id}/descargar")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"archivo privado")
        self.assertIn("privado.pdf", response.headers["Content-Disposition"])
        response.close()

    def test_downloads_existing_private_file_with_technical_name(self):
        version_doc = self.add_version(version_id=408)
        relative_path = "empresa_101/documento_301/v408/2e3ebfe3c3ea470580fa31e4e0648fc0.pdf"
        physical_path = self.private_root / relative_path
        physical_path.parent.mkdir(parents=True)
        physical_path.write_bytes(b"archivo privado anterior")
        version_doc.archivo_nombre_original = "procedimiento original.pdf"
        version_doc.archivo_nombre_guardado = physical_path.name
        version_doc.archivo_storage_path = relative_path
        version_doc.archivo_mime = "application/pdf"
        db.session.commit()

        response = self.login(201).get(f"/documentacion/version/{version_doc.id}/descargar")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"archivo privado anterior")
        self.assertIn("procedimiento original.pdf", response.headers["Content-Disposition"])
        response.close()

    def test_downloads_non_migrated_legacy_file_through_protected_route(self):
        (self.legacy_root / "legacy.pdf").write_bytes(b"archivo legacy")
        version_doc = self.add_version(
            version_id=404,
            archivo_url="/static/uploads/documentos/legacy.pdf",
        )

        response = self.login(201).get(f"/documentacion/version/{version_doc.id}/descargar")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"archivo legacy")
        response.close()

    def test_blocks_download_for_another_company(self):
        (self.legacy_root / "legacy.pdf").write_bytes(b"archivo legacy")
        version_doc = self.add_version(
            version_id=405,
            archivo_url="/static/uploads/documentos/legacy.pdf",
        )

        response = self.login(202).get(f"/documentacion/version/{version_doc.id}/descargar")

        self.assertEqual(response.status_code, 404)

    def test_missing_file_returns_404(self):
        version_doc = self.add_version(
            version_id=406,
            archivo_url="/static/uploads/documentos/no-existe.pdf",
        )

        response = self.login(201).get(f"/documentacion/version/{version_doc.id}/descargar")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
