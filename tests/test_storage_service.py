import tempfile
import unittest
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from werkzeug.datastructures import FileStorage

from app import create_app
from app.services.storage_service import (
    build_document_filename,
    DocumentStorageError,
    delete_document_file,
    resolve_document_path,
    store_document_file,
)


class DocumentStorageServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            DOCUMENT_STORAGE_ROOT=self.temp_directory.name,
            DOCUMENT_MAX_FILE_SIZE=16,
        )
        self.context = self.app.app_context()
        self.context.push()
        self.document = SimpleNamespace(
            id=11,
            empresa_id=7,
            codigo="PR-MIS-001",
            titulo="Procedimiento de muestreo",
        )

    def tearDown(self):
        self.context.pop()
        self.temp_directory.cleanup()

    @staticmethod
    def file(name="procedimiento.pdf", content=b"contenido"):
        return FileStorage(
            stream=BytesIO(content),
            filename=name,
            content_type="application/pdf",
        )

    def test_stores_file_in_tenant_document_version_path_with_metadata(self):
        stored = store_document_file(
            self.file(), documento=self.document, version="2.0"
        )

        self.assertTrue(stored.storage_path.startswith("empresa_7/documento_11/v2.0/"))
        self.assertEqual(stored.original_name, "procedimiento.pdf")
        self.assertEqual(stored.size, 9)
        self.assertEqual(len(stored.sha256), 64)
        self.assertEqual(
            stored.stored_name,
            f"PR-MIS-001_v2_0_procedimiento_de_muestreo_{stored.sha256[:8]}.pdf",
        )
        self.assertTrue(stored.storage_path.endswith(f"/{stored.stored_name}"))
        self.assertTrue(resolve_document_path(stored.storage_path).is_file())

        delete_document_file(stored.storage_path)
        self.assertFalse(resolve_document_path(stored.storage_path).exists())

    def test_rejects_disallowed_extension(self):
        with self.assertRaises(DocumentStorageError):
            store_document_file(
                self.file(name="script.exe"),
                documento=self.document,
                version="1",
            )

    def test_rejects_file_over_configured_limit_without_leaving_file(self):
        with self.assertRaises(DocumentStorageError):
            store_document_file(
                self.file(content=b"x" * 17),
                documento=self.document,
                version="1",
            )

        self.assertEqual(list(Path(self.temp_directory.name).rglob("*.pdf")), [])

    def test_rejects_path_traversal_when_resolving(self):
        with self.assertRaises(DocumentStorageError):
            resolve_document_path("../../fuera.pdf")

    def test_builds_safe_readable_filename_from_accents_and_unsafe_characters(self):
        document = SimpleNamespace(
            id=12,
            empresa_id=7,
            codigo="POL/CAL\\001",
            titulo="Política de calidad: revisión #1",
        )
        sha256 = hashlib.sha256(b"contenido").hexdigest()

        name = build_document_filename(
            document,
            "1.0",
            "../política final.DOCX",
            sha256,
        )

        self.assertEqual(
            name,
            f"POL_CAL_001_v1_0_politica_de_calidad_revision_1_{sha256[:8]}.docx",
        )
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)
        self.assertNotIn("..", name)
        self.assertNotIn(" ", name)
        self.assertLessEqual(len(name), 200)


if __name__ == "__main__":
    unittest.main()
