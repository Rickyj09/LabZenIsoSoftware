import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from werkzeug.datastructures import FileStorage

from app import create_app
from app.services.storage_service import (
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
            self.file(), empresa_id=7, documento_id=11, version="2.0"
        )

        self.assertTrue(stored.storage_path.startswith("empresa_7/documento_11/v2.0/"))
        self.assertEqual(stored.original_name, "procedimiento.pdf")
        self.assertEqual(stored.size, 9)
        self.assertEqual(len(stored.sha256), 64)
        self.assertTrue(resolve_document_path(stored.storage_path).is_file())

        delete_document_file(stored.storage_path)
        self.assertFalse(resolve_document_path(stored.storage_path).exists())

    def test_rejects_disallowed_extension(self):
        with self.assertRaises(DocumentStorageError):
            store_document_file(
                self.file(name="script.exe"),
                empresa_id=1,
                documento_id=1,
                version="1",
            )

    def test_rejects_file_over_configured_limit_without_leaving_file(self):
        with self.assertRaises(DocumentStorageError):
            store_document_file(
                self.file(content=b"x" * 17),
                empresa_id=1,
                documento_id=1,
                version="1",
            )

        self.assertEqual(list(Path(self.temp_directory.name).rglob("*.pdf")), [])

    def test_rejects_path_traversal_when_resolving(self):
        with self.assertRaises(DocumentStorageError):
            resolve_document_path("../../fuera.pdf")


if __name__ == "__main__":
    unittest.main()
