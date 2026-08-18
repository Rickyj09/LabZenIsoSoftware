import tempfile
import unittest
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko_certvalidator.registry import SimpleCertificateStore

from app import create_app
from app.extensions import db
from app.models.base import BaseModel
from app.models.documentos import (
    ARTEFACTO_DISPONIBLE,
    ARTEFACTO_PDF_APROBADO,
    ARTEFACTO_PDF_APROBADO_CON_QR,
    ARTEFACTO_PDF_FIRMADO_FINAL,
    ARTEFACTO_PDF_FIRMADO_PARCIAL,
    ESTADO_APROBADO,
    FIRMA_IDENTIDAD_PENDIENTE,
    FIRMA_IDENTIDAD_REVOCADA,
    FIRMA_IDENTIDAD_VERIFICADA,
    FIRMA_PASO_FIRMADO,
    FIRMA_PASO_HABILITADO,
    FIRMA_PROCESO_COMPLETADO,
    FIRMA_PROCESO_EN_FIRMA,
    Documento,
    DocumentoArtefacto,
    DocumentoFirmaPaso,
    DocumentoFirmaProceso,
    DocumentoSnapshot,
    DocumentoVersion,
    UsuarioIdentidadFirma,
)
from app.models.empresa import Empresa
from app.models.auditoria import AuditoriaLog
from app.models.seguridad import Permiso, Rol, RolPermiso, Usuario, UsuarioRol
from app.services.document_pdf_service import DocumentPdfService
from app.services.document_signature_identity_service import (
    DocumentSignatureIdentityError,
    DocumentSignatureIdentityService,
    SIGNATURE_IDENTITY_PERMISSION,
)
from app.services.document_signature_dev_service import (
    DEV_TEST_SIGNATURE_VALIDATED,
    DocumentSignatureDevCertificateService,
)
from app.services.document_signature_service import (
    DocumentSignatureError,
    DocumentSignatureService,
    PyHankoPdfSignatureValidator,
    START_SIGNATURE_PERMISSION,
    SignatureValidationResult,
)
from app.services.storage_service import file_digest_and_size, resolve_document_path, store_pdf_artifact_copy


class FakeSignatureProvider:
    provider_name = "external_controlled"

    def validate_signed_pdf(self, *, signed_pdf_path, input_artifact, paso, identidad):
        return SignatureValidationResult(
            is_valid=True,
            status="VALIDA",
            integrity_valid=True,
            trusted=True,
            identity_match=True,
            certificate_valid_at_signing=True,
            previous_signatures_valid=True,
            new_signature_count=1,
            total_signature_count=int(input_artifact.signature_count or 0) + 1,
            sanitized_details="Firma aceptada por proveedor falso de prueba.",
            metadata={"fake": True},
        )


class DocumentSignatureTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DOCUMENT_STORAGE_ROOT": self.temp_directory.name,
            "DOCUMENT_LEGACY_STORAGE_ROOT": self.temp_directory.name,
            "DOCUMENT_SIGNATURES_ENABLED": True,
            "DOCUMENT_SIGNATURE_VALIDATION_MODE": "strict",
            "DOCUMENT_SIGNATURES_DEV_TEST_MODE": False,
            "DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD": "",
            "DOCUMENT_SIGNATURES_DEV_ELABORADOR_BOX": "",
            "DOCUMENT_SIGNATURES_DEV_REVISOR_BOX": "",
            "DOCUMENT_SIGNATURES_DEV_APROBADOR_BOX": "",
            "DOCUMENT_SIGNATURE_PROCESS_TTL_DAYS": 15,
            "DOCUMENT_SIGNATURE_MAX_PDF_BYTES": 5 * 1024 * 1024,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.next_id = 30000

        def assign_ids(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, BaseModel) and item.id is None:
                    self.next_id += 1
                    item.id = self.next_id

        self.assign_ids = assign_ids
        event.listen(Session, "before_flush", self.assign_ids)
        import app.services.document_publication_service as publication_service

        self.original_publication_uuid4 = publication_service.uuid4
        publication_service.uuid4 = lambda: UUID("11111111-1111-1111-1111-111111111111")
        self.seed_data()

    def tearDown(self):
        import app.services.document_publication_service as publication_service

        publication_service.uuid4 = self.original_publication_uuid4
        event.remove(Session, "before_flush", self.assign_ids)
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp_directory.cleanup()

    def minimal_pdf(self, text="LabZenISO"):
        stream = b"BT /F1 12 Tf 72 120 Td (" + text.encode("ascii", "ignore") + b") Tj ET\n"
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >> endobj\n",
            b"4 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"endstream endobj\n",
        ]
        pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        offsets = [0]
        for obj in objects:
            offsets.append(len(pdf))
            pdf += obj
        xref_offset = len(pdf)
        xref_entries = [b"0000000000 65535 f \n"] + [
            f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]
        ]
        pdf += b"xref\n0 5\n" + b"".join(xref_entries)
        pdf += b"trailer << /Root 1 0 R /Size 5 >>\n"
        pdf += b"startxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF\n"
        return pdf

    def two_page_pdf(self):
        first = b"BT /F1 12 Tf 30 120 Td (pagina 1 contenido) Tj ET\n"
        second = b"BT /F1 12 Tf 30 120 Td (ultima pagina tabla firmas) Tj ET\n"
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >> endobj\n",
            b"4 0 obj << /Length " + str(len(first)).encode("ascii") + b" >> stream\n" + first + b"endstream endobj\n",
            b"5 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 6 0 R >> endobj\n",
            b"6 0 obj << /Length " + str(len(second)).encode("ascii") + b" >> stream\n" + second + b"endstream endobj\n",
        ]
        pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        offsets = [0]
        for obj in objects:
            offsets.append(len(pdf))
            pdf += obj
        xref_offset = len(pdf)
        xref_entries = [b"0000000000 65535 f \n"] + [
            f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]
        ]
        pdf += b"xref\n0 7\n" + b"".join(xref_entries)
        pdf += b"trailer << /Root 1 0 R /Size 7 >>\n"
        pdf += b"startxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF\n"
        return pdf

    def seed_data(self):
        db.session.add_all([
            Empresa(id=101, nombre="Empresa firma"),
            Empresa(id=102, nombre="Empresa externa"),
        ])
        users = [
            Usuario(id=201, empresa_id=101, nombre="Ela", apellido="Borador", email="ela@firma", username="tecnico_documental", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Re", apellido="Visor", email="rev@firma", username="revisor_documental", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Apro", apellido="Bador", email="apr@firma", username="apr", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=101, nombre="Admin", apellido="Calidad", email="admin@firma", username="admin", password_hash="x", activo=True),
            Usuario(id=205, empresa_id=101, nombre="Consulta", apellido="Firma", email="consulta@firma", username="consulta", password_hash="x", activo=True),
            Usuario(id=206, empresa_id=102, nombre="Otro", apellido="Admin", email="otro-admin@firma", username="otro-admin", password_hash="x", activo=True),
        ]
        db.session.add_all(users)
        permissions = [
            Permiso(id=1001, codigo="documentos.ver", nombre="Ver documentos", modulo="documentos"),
            Permiso(id=1002, codigo="documentos.descargar", nombre="Descargar documentos", modulo="documentos"),
            Permiso(id=1003, codigo=START_SIGNATURE_PERMISSION, nombre="Iniciar firmas", modulo="documentos"),
            Permiso(id=1004, codigo=SIGNATURE_IDENTITY_PERMISSION, nombre="Gestionar identidades", modulo="documentos"),
        ]
        admin_role = Rol(id=2001, nombre="CALIDAD", es_sistema=True)
        viewer_role = Rol(id=2002, nombre="CONSULTA", es_sistema=True)
        db.session.add_all([*permissions, admin_role, viewer_role])
        db.session.flush()
        db.session.add_all([
            RolPermiso(id=3001, rol_id=admin_role.id, permiso_id=1001),
            RolPermiso(id=3002, rol_id=admin_role.id, permiso_id=1002),
            RolPermiso(id=3003, rol_id=admin_role.id, permiso_id=1003),
            RolPermiso(id=3004, rol_id=admin_role.id, permiso_id=1004),
            RolPermiso(id=3005, rol_id=viewer_role.id, permiso_id=1001),
            RolPermiso(id=3006, rol_id=viewer_role.id, permiso_id=1002),
            UsuarioRol(id=4001, usuario_id=204, rol_id=admin_role.id),
            UsuarioRol(id=4002, usuario_id=205, rol_id=viewer_role.id),
            UsuarioRol(id=4003, usuario_id=206, rol_id=admin_role.id),
            UsuarioRol(id=4004, usuario_id=201, rol_id=viewer_role.id),
            UsuarioRol(id=4005, usuario_id=202, rol_id=viewer_role.id),
        ])
        document = Documento(
            id=501,
            empresa_id=101,
            codigo="DOC-FIRMA",
            titulo="Documento firma",
            tipo_documento="PROCEDIMIENTO",
            estado=ESTADO_APROBADO,
            version_actual="1",
            elaborado_por_id=201,
        )
        version = DocumentoVersion(
            id=1501,
            empresa_id=101,
            documento_id=501,
            version="1",
            estado=ESTADO_APROBADO,
            elaborado_por_id=201,
            revisado_por_id=202,
            aprobado_por_id=203,
            fecha_aprobacion=datetime.now(timezone.utc),
        )
        snapshot = DocumentoSnapshot(
            id=2501,
            empresa_id=101,
            public_id="snapshot-firma-aprobado",
            documento_id=501,
            documento_version_id=1501,
            secuencia=1,
            ciclo_revision=1,
            tipo="APROBADO",
            estado="DISPONIBLE",
            storage_path="not-used-in-signature-test.docx",
            archivo_nombre_interno="test.docx",
            archivo_nombre_original="test.docx",
            archivo_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            archivo_size=100,
            archivo_sha256="a" * 64,
            hash_origen="b" * 64,
            creado_por_id=203,
            creado_en=datetime.now(timezone.utc),
            inmutable=True,
        )
        db.session.add_all([document, version, snapshot])
        db.session.flush()
        for index, user_id in enumerate((201, 202, 203), start=1):
            db.session.add(UsuarioIdentidadFirma(
                empresa_id=101,
                usuario_id=user_id,
                identificacion=f"ID-{user_id}",
                nombre_certificado=f"Cert {user_id}",
                emisor_certificado="CA Test",
                certificado_fingerprint_sha256=f"{index}" * 64,
                estado=FIRMA_IDENTIDAD_VERIFICADA,
                verificado_por_id=204,
                verificado_en=datetime.now(timezone.utc),
            ))
        db.session.flush()
        source_path = Path(self.temp_directory.name) / "aprobado.pdf"
        source_path.write_bytes(self.minimal_pdf("aprobado"))
        validation = DocumentPdfService().validate_pdf_file(source_path)
        stored = store_pdf_artifact_copy(
            source_path=source_path,
            documento=document,
            version_doc=version,
            source_snapshot=snapshot,
            expected_sha256=validation.sha256,
        )
        artifact = DocumentoArtefacto(
            id=3501,
            empresa_id=101,
            public_id="pdf-aprobado-firma",
            documento_id=501,
            documento_version_id=1501,
            source_snapshot_id=2501,
            tipo=ARTEFACTO_PDF_APROBADO,
            estado=ARTEFACTO_DISPONIBLE,
            storage_path=stored.storage_path,
            archivo_nombre_interno=stored.stored_name,
            archivo_nombre_visible="aprobado.pdf",
            archivo_mime="application/pdf",
            archivo_size=stored.size,
            archivo_sha256=stored.sha256,
            source_snapshot_sha256=snapshot.archivo_sha256,
            page_count=validation.page_count,
            signature_count=0,
            provider="onlyoffice",
            creado_por_id=204,
            creado_en=datetime.now(timezone.utc),
            disponible_en=datetime.now(timezone.utc),
            inmutable=True,
            metadata_json={},
        )
        db.session.add(artifact)
        db.session.commit()

    def login(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def clear_identity(self, user_id):
        UsuarioIdentidadFirma.query.filter_by(empresa_id=101, usuario_id=user_id).delete()
        db.session.commit()

    def enable_dev_signature_mode(self):
        cert_dir = Path(self.temp_directory.name) / "dev_signature_certificates"
        self.app.config.update(
            APP_ENV="testing",
            DOCUMENT_SIGNATURES_DEV_TEST_MODE=True,
            DOCUMENT_SIGNATURES_DEV_CERT_DIR=str(cert_dir),
            DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD="local-test-password",
            DOCUMENT_SIGNATURE_VALIDATION_MODE="strict",
        )
        return cert_dir

    def make_current_version_visible_in_detail(self):
        document = Documento.query.get(501)
        document.version_vigente_id = 1501
        db.session.commit()
        return document

    def signed_upload(self, text):
        payload = self.minimal_pdf(text)
        return FileStorage(
            stream=BytesIO(payload),
            filename=f"{text}.pdf",
            content_type="application/pdf",
        )

    def real_signed_upload(self, pdf_bytes, filename):
        return FileStorage(
            stream=BytesIO(pdf_bytes),
            filename=filename,
            content_type="application/pdf",
        )

    def create_test_ca_and_cert(self, common_name, email, serial):
        if not hasattr(self, "_test_ca_key"):
            self._test_ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LabZenISO Test Root CA")])
            self._test_ca_cert = (
                x509.CertificateBuilder()
                .subject_name(ca_subject)
                .issuer_name(ca_subject)
                .public_key(self._test_ca_key.public_key())
                .serial_number(1000)
                .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
                .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(self._test_ca_key, hashes.SHA256())
            )
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, email),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self._test_ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(serial)
            .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=True,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(self._test_ca_key, hashes.SHA256())
        )
        return key, cert

    def write_test_trust_root(self):
        trust_dir = Path(self.temp_directory.name) / "signature-trust"
        trust_dir.mkdir(parents=True, exist_ok=True)
        root_path = trust_dir / "test-root.pem"
        root_path.write_bytes(self._test_ca_cert.public_bytes(serialization.Encoding.PEM))
        self.app.config["DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH"] = str(trust_dir)
        self.app.config["DOCUMENT_SIGNATURE_ALLOWED_ISSUERS_PATH"] = str(root_path)
        return root_path

    def cert_sha256(self, cert):
        return cert.fingerprint(hashes.SHA256()).hex()

    def embedded_signature_count(self, artifact):
        with resolve_document_path(artifact.storage_path).open("rb") as handle:
            from pyhanko.pdf_utils.reader import PdfFileReader

            return len(list(PdfFileReader(handle).embedded_signatures))

    def physical_page_count(self, artifact):
        from pypdf import PdfReader

        return len(PdfReader(str(resolve_document_path(artifact.storage_path))).pages)

    def embedded_signature_names(self, artifact):
        with resolve_document_path(artifact.storage_path).open("rb") as handle:
            from pyhanko.pdf_utils.reader import PdfFileReader

            return [signature.field_name for signature in PdfFileReader(handle).embedded_signatures]

    def signature_field_layouts(self, artifact):
        with resolve_document_path(artifact.storage_path).open("rb") as handle:
            from pyhanko.pdf_utils.reader import PdfFileReader

            reader = PdfFileReader(handle)
            page_count = int(reader.root["/Pages"]["/Count"])
            page_refs = [reader.find_page_for_modification(index)[0].reference for index in range(page_count)]
            fields = reader.root["/AcroForm"]["/Fields"]
            layouts = {}
            for field_ref in fields:
                field = field_ref.get_object()
                name = str(field["/T"])
                page_ref = field.raw_get("/P")
                page_index = next(
                    index for index, candidate in enumerate(page_refs)
                    if page_ref.reference == candidate
                )
                layouts[name] = {
                    "page_index": page_index,
                    "rect": tuple(float(item) for item in field["/Rect"]),
                }
            return layouts

    def assert_horizontal_procedure_layout(self, placements, *, page_index=1):
        self.assertEqual(list(placements), ["ELABORADOR", "REVISOR", "APROBADOR"])
        self.assertEqual({placement.page_index for placement in placements.values()}, {page_index})
        self.assertEqual(
            {role: placement.normalized_box for role, placement in placements.items()},
            {
                "ELABORADOR": (0.02, 0.18, 0.32, 0.28),
                "REVISOR": (0.35, 0.18, 0.65, 0.28),
                "APROBADOR": (0.68, 0.18, 0.98, 0.28),
            },
        )
        boxes = {role: placement.box for role, placement in placements.items()}
        self.assertLess(boxes["ELABORADOR"][0], boxes["REVISOR"][0])
        self.assertLess(boxes["REVISOR"][0], boxes["APROBADOR"][0])
        self.assertEqual(
            {box[1:4:2] for box in boxes.values()},
            {(36, 56)},
        )
        self.assertLessEqual(boxes["ELABORADOR"][2], boxes["REVISOR"][0])
        self.assertLessEqual(boxes["REVISOR"][2], boxes["APROBADOR"][0])
        self.assertEqual(boxes["ELABORADOR"], (4, 36, 64, 56))
        self.assertEqual(boxes["REVISOR"], (70, 36, 130, 56))
        self.assertEqual(boxes["APROBADOR"], (136, 36, 196, 56))
        for box in boxes.values():
            x1, y1, x2, y2 = box
            self.assertGreater(x2, x1)
            self.assertGreater(y2, y1)
            self.assertGreaterEqual(x1, 0)
            self.assertGreaterEqual(y1, 0)
            self.assertLessEqual(x2, 200)
            self.assertLessEqual(y2, 200)

    def update_identity_for_cert(self, user_id, cert):
        identity = UsuarioIdentidadFirma.query.filter_by(usuario_id=user_id).first()
        identity.certificado_fingerprint_sha256 = self.cert_sha256(cert)
        identity.emisor_certificado = cert.issuer.rfc4514_string()
        identity.metadata_json = {
            "certificate_fingerprint_sha256": self.cert_sha256(cert),
            "certificate_serial": str(cert.serial_number),
            "certificate_issuer": "Common Name: " + cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
            "certificate_email": cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)[0].value,
            "certificate_subject": "Email Address: "
            + cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)[0].value
            + ", Common Name: "
            + cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
        }
        db.session.commit()
        return identity

    def sign_pdf_with_test_cert(self, pdf_bytes, key, cert, field_name):
        return self.sign_pdf_with_cert_chain(pdf_bytes, key, cert, field_name, [self._test_ca_cert])

    def sign_pdf_with_cert_chain(self, pdf_bytes, key, cert, field_name, registry_certs=None):
        signing_cert = asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
        signing_key = asn1_keys.PrivateKeyInfo.load(key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        registry_certs = registry_certs or []
        store = SimpleCertificateStore.from_certs([
            asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
            for cert in registry_certs
        ])
        signer = signers.SimpleSigner(
            signing_cert=signing_cert,
            signing_key=signing_key,
            cert_registry=store,
        )
        writer = IncrementalPdfFileWriter(BytesIO(pdf_bytes))
        output = BytesIO()
        signers.sign_pdf(
            writer,
            signature_meta=signers.PdfSignatureMetadata(field_name=field_name, md_algorithm="sha256"),
            signer=signer,
            output=output,
        )
        return output.getvalue()

    def create_intermediate_chain(self, common_name, email, serial, *, signer_valid=True):
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        root_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LabZenISO Chain Root CA")])
        root_cert = (
            x509.CertificateBuilder()
            .subject_name(root_subject)
            .issuer_name(root_subject)
            .public_key(root_key.public_key())
            .serial_number(9000 + serial)
            .not_valid_before(datetime.now(timezone.utc) - timedelta(days=10))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(root_key, hashes.SHA256())
        )
        intermediate_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        intermediate_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LabZenISO Chain Intermediate CA")])
        intermediate_cert = (
            x509.CertificateBuilder()
            .subject_name(intermediate_subject)
            .issuer_name(root_cert.subject)
            .public_key(intermediate_key.public_key())
            .serial_number(9100 + serial)
            .not_valid_before(datetime.now(timezone.utc) - timedelta(days=5))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=120))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(root_key, hashes.SHA256())
        )
        signer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signer_subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, email),
        ])
        not_before = datetime.now(timezone.utc) - timedelta(days=1 if signer_valid else 30)
        not_after = datetime.now(timezone.utc) + timedelta(days=30 if signer_valid else -1)
        signer_cert = (
            x509.CertificateBuilder()
            .subject_name(signer_subject)
            .issuer_name(intermediate_cert.subject)
            .public_key(signer_key.public_key())
            .serial_number(serial)
            .not_valid_before(not_before)
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(intermediate_key, hashes.SHA256())
        )
        return root_cert, intermediate_cert, signer_key, signer_cert

    def configure_chain_trust(self, root_cert, intermediate_cert=None, *, allowed_issuer=None):
        trust_dir = Path(self.temp_directory.name) / f"chain-trust-{root_cert.serial_number}"
        trust_dir.mkdir(parents=True, exist_ok=True)
        root_path = trust_dir / "root.pem"
        root_path.write_bytes(root_cert.public_bytes(serialization.Encoding.PEM))
        self.app.config["DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH"] = str(root_path)
        if intermediate_cert:
            intermediate_dir = Path(self.temp_directory.name) / f"chain-intermediates-{intermediate_cert.serial_number}"
            intermediate_dir.mkdir(parents=True, exist_ok=True)
            (intermediate_dir / "intermediate.pem").write_bytes(intermediate_cert.public_bytes(serialization.Encoding.PEM))
            self.app.config["DOCUMENT_SIGNATURE_INTERMEDIATES_PATH"] = str(intermediate_dir)
        else:
            self.app.config["DOCUMENT_SIGNATURE_INTERMEDIATES_PATH"] = ""
        self.app.config["DOCUMENT_SIGNATURE_ALLOWED_ISSUERS_PATH"] = ""
        if allowed_issuer:
            allowed_path = trust_dir / "allowed.pem"
            allowed_path.write_bytes(allowed_issuer.public_bytes(serialization.Encoding.PEM))
            self.app.config["DOCUMENT_SIGNATURE_ALLOWED_ISSUERS_PATH"] = str(allowed_path)

    def test_start_process_creates_sequential_steps_without_changing_document_state(self):
        document = Documento.query.get(501)
        version = DocumentoVersion.query.get(1501)
        admin = Usuario.query.get(204)
        process = DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
            documento=document,
            version_doc=version,
            usuario=admin,
        )
        steps = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id).order_by(DocumentoFirmaPaso.orden).all()
        self.assertEqual(process.estado, FIRMA_PROCESO_EN_FIRMA)
        self.assertEqual([step.rol_firmante for step in steps], ["ELABORADOR", "REVISOR", "APROBADOR"])
        self.assertEqual(steps[0].estado, FIRMA_PASO_HABILITADO)
        self.assertEqual([step.estado for step in steps[1:]], ["PENDIENTE", "PENDIENTE"])
        self.assertEqual(document.estado, ESTADO_APROBADO)
        self.assertIsNone(document.version_vigente_id)

    def test_start_process_is_idempotent_for_double_request(self):
        service = DocumentSignatureService(provider=FakeSignatureProvider())
        document = Documento.query.get(501)
        version = DocumentoVersion.query.get(1501)
        admin = Usuario.query.get(204)
        first = service.start_process(documento=document, version_doc=version, usuario=admin)
        second = service.start_process(documento=document, version_doc=version, usuario=admin)
        self.assertEqual(first.id, second.id)
        self.assertEqual(DocumentoFirmaPaso.query.filter_by(proceso_id=first.id).count(), 3)

    def test_start_process_requires_approved_pdf(self):
        DocumentoArtefacto.query.filter_by(documento_version_id=1501, tipo=ARTEFACTO_PDF_APROBADO).delete()
        db.session.commit()
        with self.assertRaisesRegex(DocumentSignatureError, "No existe PDF aprobado"):
            DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
                documento=Documento.query.get(501),
                version_doc=DocumentoVersion.query.get(1501),
                usuario=Usuario.query.get(204),
            )

    def test_start_process_requires_approved_state(self):
        document = Documento.query.get(501)
        document.estado = "EN_REVISION"
        db.session.commit()
        with self.assertRaisesRegex(DocumentSignatureError, "APROBADOS"):
            DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
                documento=document,
                version_doc=DocumentoVersion.query.get(1501),
                usuario=Usuario.query.get(204),
            )

    def test_start_process_requires_signature_permission(self):
        with self.assertRaisesRegex(DocumentSignatureError, "permiso"):
            DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
                documento=Documento.query.get(501),
                version_doc=DocumentoVersion.query.get(1501),
                usuario=Usuario.query.get(205),
            )

    def test_detail_shows_start_signature_for_authorized_approved_document_with_pdf(self):
        self.make_current_version_visible_in_detail()
        response = self.login(204).get("/documentacion/501")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Firmas digitales", html)
        self.assertIn("Iniciar firma externa", html)
        self.assertIn("Páginas", html)
        self.assertIn("Tamaño", html)

    def test_detail_hides_start_signature_without_permission_and_post_is_forbidden(self):
        self.make_current_version_visible_in_detail()
        client = self.login(205)
        response = client.get("/documentacion/501")
        self.assertNotIn("Iniciar firma externa", response.get_data(as_text=True))
        post = client.post("/documentacion/501/versiones/1501/firmas/iniciar")
        self.assertEqual(post.status_code, 403)

    def test_identity_admin_lists_only_active_company_users(self):
        db.session.add_all([
            Usuario(id=207, empresa_id=101, nombre="In", apellido="Activo", email="inactivo@firma", username="inactivo", password_hash="x", activo=False),
            Usuario(id=208, empresa_id=102, nombre="Tenant", apellido="Ajeno", email="tenant@firma", username="tenant-ajeno", password_hash="x", activo=True),
        ])
        db.session.commit()
        response = self.login(204).get("/documentacion/firmas/identidades")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Identidades de firma", html)
        self.assertIn("Ela", html)
        self.assertIn("Re", html)
        self.assertIn("Apro", html)
        self.assertIn("Admin", html)
        self.assertNotIn("inactivo", html)
        self.assertNotIn("tenant-ajeno", html)

    def test_identity_admin_requires_permission(self):
        client = self.login(205)

        self.assertEqual(client.get("/documentacion/firmas/identidades").status_code, 403)
        self.assertEqual(client.post("/documentacion/firmas/identidades", data={
            "user_id": "201",
            "identificacion": "ID-201-X",
        }).status_code, 403)

    def test_create_identity_validates_required_fields_and_fingerprint(self):
        self.clear_identity(201)
        client = self.login(204)

        missing = client.post("/documentacion/firmas/identidades", data={
            "user_id": "201",
            "identificacion": "",
        }, follow_redirects=True)
        self.assertEqual(missing.status_code, 200)
        self.assertIsNone(UsuarioIdentidadFirma.query.filter_by(usuario_id=201).first())

        invalid = client.post("/documentacion/firmas/identidades", data={
            "user_id": "201",
            "identificacion": "ID-201-X",
            "certificado_fingerprint_sha256": "abc",
        }, follow_redirects=True)
        self.assertEqual(invalid.status_code, 200)
        self.assertIsNone(UsuarioIdentidadFirma.query.filter_by(usuario_id=201).first())

        valid = client.post("/documentacion/firmas/identidades", data={
            "user_id": "201",
            "identificacion": "ID-201-X",
            "nombre_certificado": "Certificado X",
            "emisor_certificado": "CA X",
            "certificado_fingerprint_sha256": "A" * 64,
        }, follow_redirects=True)
        identity = UsuarioIdentidadFirma.query.filter_by(usuario_id=201).one()
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(identity.estado, FIRMA_IDENTIDAD_PENDIENTE)
        self.assertEqual(identity.certificado_fingerprint_sha256, "a" * 64)

    def test_identity_service_rejects_inactive_and_cross_tenant_users(self):
        db.session.add_all([
            Usuario(id=207, empresa_id=101, nombre="In", apellido="Activo", email="inactivo@firma", username="inactivo", password_hash="x", activo=False),
            Usuario(id=208, empresa_id=102, nombre="Tenant", apellido="Ajeno", email="tenant@firma", username="tenant-ajeno", password_hash="x", activo=True),
        ])
        db.session.commit()
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)

        with self.assertRaisesRegex(DocumentSignatureIdentityError, "inactivo"):
            service.create_identity(actor=actor, user_id=207, identificacion="ID-207")
        with self.assertRaisesRegex(DocumentSignatureIdentityError, "otra empresa"):
            service.create_identity(actor=actor, user_id=208, identificacion="ID-208")

    def test_identity_service_prevents_duplicate_identity_for_user(self):
        self.clear_identity(201)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)

        service.create_identity(actor=actor, user_id=201, identificacion="ID-201-X")
        with self.assertRaisesRegex(DocumentSignatureIdentityError, "Ya existe"):
            service.create_identity(actor=actor, user_id=201, identificacion="ID-201-Y")

    def test_identity_service_allows_new_identity_after_revocation(self):
        self.clear_identity(201)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        first = service.create_identity(actor=actor, user_id=201, identificacion="ID-201-X")
        service.revoke_identity(actor=actor, identity_id=first.id)

        second = service.create_identity(actor=actor, user_id=201, identificacion="ID-201-Y")

        self.assertEqual(second.estado, FIRMA_IDENTIDAD_PENDIENTE)
        self.assertEqual(UsuarioIdentidadFirma.query.filter_by(usuario_id=201).count(), 2)

    def test_mock_verification_records_metadata_and_audit(self):
        self.clear_identity(201)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        identity = service.create_identity(
            actor=actor,
            user_id=201,
            identificacion="ID-201-X",
            certificado_fingerprint_sha256="B" * 64,
        )

        verified = service.verify_identity_mock(actor=actor, identity_id=identity.id)
        actions = [
            log.accion
            for log in AuditoriaLog.query
            .filter_by(tabla="usuario_identidades_firma", registro_id=identity.id)
            .order_by(AuditoriaLog.id)
            .all()
        ]

        self.assertEqual(verified.estado, FIRMA_IDENTIDAD_VERIFICADA)
        self.assertEqual(verified.verificado_por_id, 204)
        self.assertIsNotNone(verified.verificado_en)
        self.assertEqual(verified.metadata_json["verification_type"], "local_mock")
        self.assertEqual(actions, ["CREAR", "VERIFICAR"])

    def test_firmasegura_certified_identification_oid_is_used_exactly(self):
        from types import SimpleNamespace

        from app.services.document_signature_service import (
            PyHankoPdfSignatureValidator,
        )

        validator = PyHankoPdfSignatureValidator(self.app)
        oid = "1.3.6.1.4.1.61305.3.1"

        extension = {
            "extn_id": SimpleNamespace(dotted=oid),
            "extn_value": SimpleNamespace(
                parsed=SimpleNamespace(native="1711459816")
            ),
        }
        certificate = {
            "tbs_certificate": {
                "extensions": [extension],
            }
        }

        certified_id = validator._certificate_extension_value(
            certificate,
            oid,
        )

        self.assertEqual(certified_id, "1711459816")
        self.assertTrue(
            validator._identification_matches_cert(
                "1711459816",
                {
                    "certificate_identification": certified_id,
                    "certificate_subject": "Common Name: Ricardo",
                },
            )
        )

        # Si el certificado trae un identificador certificado, este manda:
        # no debe aceptarse un ID distinto aunque aparezca como texto en el CN.
        self.assertFalse(
            validator._identification_matches_cert(
                "1711459816",
                {
                    "certificate_identification": "9999999999",
                    "certificate_subject": "Common Name: Ricardo 1711459816",
                },
            )
        )

    def test_cryptographic_identity_verification_from_signed_enrollment_pdf(self):
        self.clear_identity(201)
        root_cert, intermediate_cert, signer_key, signer_cert = self.create_intermediate_chain("Ricardo ID-201", "ricardo@firma.test", 8801)
        self.configure_chain_trust(root_cert, intermediate_cert, allowed_issuer=intermediate_cert)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        identity = service.create_identity(actor=actor, user_id=201, identificacion="ID-201")
        signed_pdf = self.sign_pdf_with_cert_chain(self.minimal_pdf("enrollment"), signer_key, signer_cert, "Enrollment", [])

        verified = service.verify_identity_cryptographic_pdf(
            actor=actor,
            identity_id=identity.id,
            file_storage=self.real_signed_upload(signed_pdf, "enrollment.pdf"),
        )

        self.assertEqual(verified.estado, FIRMA_IDENTIDAD_VERIFICADA)
        self.assertEqual(verified.verificado_por_id, actor.id)
        self.assertEqual(verified.certificado_fingerprint_sha256, self.cert_sha256(signer_cert))
        self.assertEqual(verified.emisor_certificado, "Common Name: LabZenISO Chain Intermediate CA")
        self.assertEqual(verified.metadata_json["verification_type"], "cryptographic_signed_pdf")
        self.assertEqual(verified.metadata_json["certificate_serial"], str(signer_cert.serial_number))
        self.assertEqual(verified.metadata_json["certificate_email"], "ricardo@firma.test")

    def test_cryptographic_identity_verification_rejects_wrong_identification(self):
        self.clear_identity(201)
        root_cert, intermediate_cert, signer_key, signer_cert = self.create_intermediate_chain("Ricardo ID-999", "ricardo@firma.test", 8802)
        self.configure_chain_trust(root_cert, intermediate_cert, allowed_issuer=intermediate_cert)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        identity = service.create_identity(actor=actor, user_id=201, identificacion="ID-201")
        signed_pdf = self.sign_pdf_with_cert_chain(self.minimal_pdf("enrollment"), signer_key, signer_cert, "Enrollment-Wrong-ID", [])

        with self.assertRaisesRegex(DocumentSignatureIdentityError, "IDENTIFICACION_NO_COINCIDE"):
            service.verify_identity_cryptographic_pdf(
                actor=actor,
                identity_id=identity.id,
                file_storage=self.real_signed_upload(signed_pdf, "wrong-id.pdf"),
            )
        db.session.refresh(identity)
        self.assertEqual(identity.estado, FIRMA_IDENTIDAD_PENDIENTE)

    def test_cryptographic_identity_verification_rejects_untrusted_chain(self):
        self.clear_identity(201)
        root_cert, intermediate_cert, signer_key, signer_cert = self.create_intermediate_chain("Ricardo ID-201", "ricardo@firma.test", 8803)
        self.configure_chain_trust(root_cert, None)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        identity = service.create_identity(actor=actor, user_id=201, identificacion="ID-201")
        signed_pdf = self.sign_pdf_with_cert_chain(self.minimal_pdf("enrollment"), signer_key, signer_cert, "Enrollment-Untrusted", [])

        with self.assertRaisesRegex(DocumentSignatureIdentityError, "NO_CONFIABLE|INVALIDA"):
            service.verify_identity_cryptographic_pdf(
                actor=actor,
                identity_id=identity.id,
                file_storage=self.real_signed_upload(signed_pdf, "untrusted.pdf"),
            )

    def test_cryptographic_identity_verification_rejects_invalid_certificate(self):
        self.clear_identity(201)
        root_cert, intermediate_cert, signer_key, signer_cert = self.create_intermediate_chain("Ricardo ID-201", "ricardo@firma.test", 8804, signer_valid=False)
        self.configure_chain_trust(root_cert, intermediate_cert, allowed_issuer=intermediate_cert)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        identity = service.create_identity(actor=actor, user_id=201, identificacion="ID-201")
        signed_pdf = self.sign_pdf_with_cert_chain(self.minimal_pdf("enrollment"), signer_key, signer_cert, "Enrollment-Expired", [])

        with self.assertRaisesRegex(DocumentSignatureIdentityError, "CERTIFICADO_NO_VIGENTE|INVALIDA"):
            service.verify_identity_cryptographic_pdf(
                actor=actor,
                identity_id=identity.id,
                file_storage=self.real_signed_upload(signed_pdf, "expired.pdf"),
            )

    def test_dev_mode_is_disabled_by_default_and_blocked_in_production(self):
        self.assertFalse(self.app.config.get("DOCUMENT_SIGNATURES_DEV_TEST_MODE"))
        with self.assertRaisesRegex(RuntimeError, "produccion"):
            create_app({
                "TESTING": True,
                "APP_ENV": "production",
                "DOCUMENT_SIGNATURES_DEV_TEST_MODE": True,
                "DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD": "secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "SQLALCHEMY_ENGINE_OPTIONS": {},
            })

    def test_dev_cli_initializes_distinct_certificates_and_syncs_identities_idempotently(self):
        cert_dir = self.enable_dev_signature_mode()
        runner = self.app.test_cli_runner()

        first = runner.invoke(args=["firmas-dev", "inicializar"])
        second = runner.invoke(args=["firmas-dev", "inicializar"])

        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertTrue((cert_dir / "labzeniso-dev-ca.cert.pem").exists())
        self.assertTrue((cert_dir / "labzeniso-dev-ca.key.pem").exists())
        identities = {
            identity.usuario.username: identity
            for identity in UsuarioIdentidadFirma.query
            .filter(UsuarioIdentidadFirma.usuario_id.in_((201, 202, 204)))
            .all()
        }
        fingerprints = {identity.certificado_fingerprint_sha256 for identity in identities.values()}

        self.assertEqual(set(identities), {"tecnico_documental", "revisor_documental", "admin"})
        self.assertEqual(len(fingerprints), 3)
        self.assertEqual(UsuarioIdentidadFirma.query.filter_by(usuario_id=201).count(), 1)
        for identity in identities.values():
            self.assertEqual(identity.estado, FIRMA_IDENTIDAD_VERIFICADA)
            self.assertTrue(identity.metadata_json["dev_test_certificate"])
            self.assertTrue(identity.metadata_json["local_mock_verification"])
            cert_info = DocumentSignatureDevCertificateService(self.app).load_user_certificate_info(identity.usuario.username)
            self.assertEqual(identity.certificado_fingerprint_sha256, cert_info["fingerprint"])

    def test_dev_signature_action_visibility_and_wrong_user_guard(self):
        self.enable_dev_signature_mode()
        DocumentSignatureDevCertificateService(self.app).initialize()
        self.make_current_version_visible_in_detail()
        version = DocumentoVersion.query.get(1501)
        version.aprobado_por_id = 204
        version.aprobado_por = Usuario.query.get(204)
        db.session.commit()
        process = DocumentSignatureService().start_process(
            documento=Documento.query.get(501),
            version_doc=version,
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, orden=1).one()

        signer_client = self.login(201)
        signer_response = signer_client.get("/documentacion/501")
        with signer_client.session_transaction() as session:
            csrf_token = session[f"dev_signature_csrf:{step.public_id}"]
        missing_csrf = signer_client.post(f"/documentacion/firmas/pasos/{step.public_id}/firmar-dev")
        wrong_user = self.login(202).post(f"/documentacion/firmas/pasos/{step.public_id}/firmar-dev")
        self.app.config["DOCUMENT_SIGNATURES_DEV_TEST_MODE"] = False
        hidden_response = self.login(201).get("/documentacion/501")
        disabled_route = self.login(201).post(f"/documentacion/firmas/pasos/{step.public_id}/firmar-dev")

        self.assertIn("Firmar con certificado de prueba", signer_response.get_data(as_text=True))
        self.assertIn(csrf_token, signer_response.get_data(as_text=True))
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(wrong_user.status_code, 403)
        self.assertNotIn("Firmar con certificado de prueba", hidden_response.get_data(as_text=True))
        self.assertEqual(disabled_route.status_code, 404)

    def test_dev_signature_preview_prepares_qr_without_signing_or_duplication(self):
        self.enable_dev_signature_mode()
        self.make_current_version_visible_in_detail()
        before_processes = DocumentoFirmaProceso.query.count()
        before_qr_artifacts = DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_APROBADO_CON_QR).count()

        client = self.login(201)
        detail = client.get("/documentacion/501")
        response = client.get("/documentacion/501/firmas-dev/vista-previa", follow_redirects=True)
        second_response = client.get("/documentacion/501/firmas-dev/vista-previa", follow_redirects=True)

        self.assertIn("Vista previa de QR y firmas", detail.get_data(as_text=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        from pyhanko.pdf_utils.reader import PdfFileReader

        preview_reader = PdfFileReader(BytesIO(response.get_data()))
        self.assertEqual(len(list(preview_reader.embedded_signatures)), 0)
        self.assertIn(b"PREVISUALIZACION", response.get_data())
        self.assertIn(b"SIN FIRMAS", response.get_data())
        self.assertEqual(DocumentoFirmaProceso.query.count(), before_processes)
        self.assertEqual(
            DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_APROBADO_CON_QR).count(),
            before_qr_artifacts + 1,
        )

        self.app.config["DOCUMENT_SIGNATURES_DEV_TEST_MODE"] = False
        disabled = client.get("/documentacion/501/firmas-dev/vista-previa")
        self.assertEqual(disabled.status_code, 404)

    def test_procedure_signature_profile_uses_horizontal_last_page_layout(self):
        self.enable_dev_signature_mode()
        document = Documento.query.get(501)
        original_pdf = DocumentoArtefacto.query.filter_by(documento_version_id=1501, tipo=ARTEFACTO_PDF_APROBADO).one()
        original_pdf_path = resolve_document_path(original_pdf.storage_path)
        os.chmod(original_pdf_path, 0o600)
        original_pdf_path.write_bytes(self.two_page_pdf())

        placements = DocumentSignatureDevCertificateService(self.app).signature_placements_for_pdf(
            original_pdf_path,
            documento=document,
        )

        self.assert_horizontal_procedure_layout(placements)

    def test_dev_signature_box_config_overrides_procedure_defaults(self):
        self.enable_dev_signature_mode()
        self.app.config.update(
            DOCUMENT_SIGNATURES_DEV_ELABORADOR_BOX="0.10,0.04,0.30,0.14",
            DOCUMENT_SIGNATURES_DEV_REVISOR_BOX="0.40,0.04,0.60,0.14",
            DOCUMENT_SIGNATURES_DEV_APROBADOR_BOX="0.70,0.04,0.90,0.14",
        )
        document = Documento.query.get(501)
        original_pdf = DocumentoArtefacto.query.filter_by(documento_version_id=1501, tipo=ARTEFACTO_PDF_APROBADO).one()
        original_pdf_path = resolve_document_path(original_pdf.storage_path)
        os.chmod(original_pdf_path, 0o600)
        original_pdf_path.write_bytes(self.two_page_pdf())

        placements = DocumentSignatureDevCertificateService(self.app).signature_placements_for_pdf(
            original_pdf_path,
            documento=document,
        )

        self.assertEqual(placements["ELABORADOR"].normalized_box, (0.10, 0.04, 0.30, 0.14))
        self.assertEqual(placements["REVISOR"].normalized_box, (0.40, 0.04, 0.60, 0.14))
        self.assertEqual(placements["APROBADOR"].normalized_box, (0.70, 0.04, 0.90, 0.14))
        self.assertEqual(placements["ELABORADOR"].box, (20, 8, 60, 28))
        self.assertEqual(placements["REVISOR"].box, (80, 8, 120, 28))
        self.assertEqual(placements["APROBADOR"].box, (140, 8, 180, 28))

    def test_invalid_dev_signature_box_blocks_signature_without_advancing_step(self):
        self.enable_dev_signature_mode()
        self.app.config["DOCUMENT_SIGNATURES_DEV_REVISOR_BOX"] = "0.03,0.19,0.31,0.27"
        DocumentSignatureDevCertificateService(self.app).initialize()
        self.make_current_version_visible_in_detail()
        version = DocumentoVersion.query.get(1501)
        version.aprobado_por_id = 204
        version.aprobado_por = Usuario.query.get(204)
        db.session.commit()
        process = DocumentSignatureService().start_process(
            documento=Documento.query.get(501),
            version_doc=version,
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, orden=1).one()

        with self.assertRaises(DocumentSignatureError) as raised:
            DocumentSignatureService().sign_step_with_dev_certificate(
                paso=step,
                usuario=Usuario.query.get(201),
            )

        db.session.refresh(step)
        db.session.refresh(process)
        self.assertIn("se superponen", str(raised.exception))
        self.assertEqual(step.estado, FIRMA_PASO_HABILITADO)
        self.assertEqual(process.estado, FIRMA_PROCESO_EN_FIRMA)
        self.assertEqual(DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(), 0)

    def test_dev_pades_flow_signs_three_distinct_certificates_and_completes_process(self):
        self.enable_dev_signature_mode()
        DocumentSignatureDevCertificateService(self.app).initialize()
        self.make_current_version_visible_in_detail()
        document = Documento.query.get(501)
        version = DocumentoVersion.query.get(1501)
        version.aprobado_por_id = 204
        version.aprobado_por = Usuario.query.get(204)
        original_pdf = DocumentoArtefacto.query.filter_by(documento_version_id=1501, tipo=ARTEFACTO_PDF_APROBADO).one()
        original_pdf_path = resolve_document_path(original_pdf.storage_path)
        os.chmod(original_pdf_path, 0o600)
        original_pdf_path.write_bytes(self.two_page_pdf())
        validation = DocumentPdfService().validate_pdf_file(original_pdf_path)
        original_pdf.archivo_sha256 = validation.sha256
        original_pdf.archivo_size = validation.size
        original_pdf.page_count = validation.page_count
        original_state = (document.estado, version.version, original_pdf.archivo_sha256, original_pdf.storage_path)
        db.session.commit()
        dev_service = DocumentSignatureDevCertificateService(self.app)
        placements = dev_service.signature_placements_for_pdf(original_pdf_path, documento=document)
        self.assert_horizontal_procedure_layout(placements)

        process = DocumentSignatureService().start_process(
            documento=document,
            version_doc=version,
            usuario=Usuario.query.get(204),
        )
        for order, user_id, expected_next_state in (
            (1, 201, FIRMA_PASO_HABILITADO),
            (2, 202, FIRMA_PASO_HABILITADO),
            (3, 204, None),
        ):
            step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, orden=order).one()
            artifact = DocumentSignatureService().sign_step_with_dev_certificate(
                paso=step,
                usuario=Usuario.query.get(user_id),
            )
            db.session.refresh(step)
            db.session.refresh(process)
            self.assertIsNotNone(artifact.id)
            self.assertEqual(step.estado, FIRMA_PASO_FIRMADO)
            self.assertEqual(step.signature_count_after, order)
            self.assertEqual(self.embedded_signature_count(step.artifact_salida), order)
            self.assertEqual(step.artifact_salida.page_count, 2)
            self.assertEqual(self.physical_page_count(step.artifact_salida), 2)
            if expected_next_state:
                next_step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, orden=order + 1).one()
                self.assertEqual(next_step.estado, expected_next_state)

        db.session.refresh(process)
        db.session.refresh(document)
        db.session.refresh(version)
        db.session.refresh(original_pdf)
        steps = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id).order_by(DocumentoFirmaPaso.orden).all()
        fingerprints = {step.identidad_firma.certificado_fingerprint_sha256 for step in steps}
        dev_events = [
            event.tipo_evento
            for event in process.eventos
            if event.tipo_evento == DEV_TEST_SIGNATURE_VALIDATED
        ]

        self.assertEqual(process.estado, FIRMA_PROCESO_COMPLETADO)
        self.assertIsNotNone(process.pdf_final_id)
        self.assertEqual(self.embedded_signature_count(process.pdf_final), 3)
        self.assertEqual(process.pdf_final.page_count, 2)
        self.assertEqual(self.physical_page_count(process.pdf_final), 2)
        self.assertEqual(
            self.embedded_signature_names(process.pdf_final),
            ["LabZenISO_Elaborador", "LabZenISO_Revisor", "LabZenISO_Aprobador"],
        )
        layouts = self.signature_field_layouts(process.pdf_final)
        self.assertEqual(set(layouts), {"LabZenISO_Elaborador", "LabZenISO_Revisor", "LabZenISO_Aprobador"})
        self.assertEqual({layout["page_index"] for layout in layouts.values()}, {1})
        self.assertEqual(
            layouts,
            {
                "LabZenISO_Elaborador": {"page_index": 1, "rect": (4.0, 36.0, 64.0, 56.0)},
                "LabZenISO_Revisor": {"page_index": 1, "rect": (70.0, 36.0, 130.0, 56.0)},
                "LabZenISO_Aprobador": {"page_index": 1, "rect": (136.0, 36.0, 196.0, 56.0)},
            },
        )
        final_bytes = resolve_document_path(process.pdf_final.storage_path).read_bytes()
        self.assertIn(b"CERTIFICADO DE DESARROLLO", final_bytes)
        self.assertIn(b"SIN VALIDEZ LEGAL", final_bytes)
        self.assertIn(b"Firmado digitalmente", final_bytes)
        self.assertNotIn(b"Digitally signed by", final_bytes)
        self.assertEqual(len(fingerprints), 3)
        self.assertEqual(DocumentoFirmaProceso.query.count(), 1)
        self.assertEqual(DocumentoFirmaPaso.query.filter_by(proceso_id=process.id).count(), 3)
        self.assertEqual((document.estado, version.version, original_pdf.archivo_sha256, original_pdf.storage_path), original_state)
        self.assertEqual(len(dev_events), 3)

    def test_dev_signature_preserves_one_page_physical_count_in_artifact_metadata(self):
        self.enable_dev_signature_mode()
        DocumentSignatureDevCertificateService(self.app).initialize()
        process = DocumentSignatureService().start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, orden=1).one()

        artifact = DocumentSignatureService().sign_step_with_dev_certificate(
            paso=step,
            usuario=Usuario.query.get(201),
        )

        self.assertEqual(artifact.tipo, ARTEFACTO_PDF_FIRMADO_PARCIAL)
        self.assertEqual(artifact.signature_count, 1)
        self.assertEqual(artifact.page_count, 1)
        self.assertEqual(self.physical_page_count(artifact), 1)
        self.assertEqual(
            DocumentPdfService().validate_pdf_file(
                resolve_document_path(artifact.storage_path),
                allow_signature_forms=True,
            ).page_count,
            1,
        )

    def test_detail_hides_start_signature_without_pdf_and_post_does_not_create_process(self):
        self.make_current_version_visible_in_detail()
        DocumentoArtefacto.query.filter_by(documento_version_id=1501, tipo=ARTEFACTO_PDF_APROBADO).delete()
        db.session.commit()
        client = self.login(204)
        response = client.get("/documentacion/501")
        self.assertNotIn("Iniciar firma externa", response.get_data(as_text=True))
        post = client.post("/documentacion/501/versiones/1501/firmas/iniciar", follow_redirects=True)
        self.assertEqual(post.status_code, 200)
        self.assertEqual(DocumentoFirmaPaso.query.count(), 0)

    def test_detail_hides_start_signature_for_unapproved_document(self):
        self.make_current_version_visible_in_detail()
        document = Documento.query.get(501)
        document.estado = "EN_REVISION"
        db.session.commit()
        response = self.login(204).get("/documentacion/501")
        self.assertNotIn("Iniciar firma externa", response.get_data(as_text=True))

    def test_cross_tenant_start_route_returns_not_found(self):
        self.make_current_version_visible_in_detail()
        response = self.login(206).post("/documentacion/501/versiones/1501/firmas/iniciar")
        self.assertEqual(response.status_code, 404)

    def test_start_route_creates_one_process_and_hides_button_afterward(self):
        self.make_current_version_visible_in_detail()
        client = self.login(204)
        first = client.post("/documentacion/501/versiones/1501/firmas/iniciar", follow_redirects=True)
        second = client.post("/documentacion/501/versiones/1501/firmas/iniciar", follow_redirects=True)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        html = second.get_data(as_text=True)
        self.assertIn("Firmas digitales", html)
        self.assertNotIn("Iniciar firma externa", html)
        self.assertEqual(DocumentoFirmaProceso.query.count(), 1)
        processes = DocumentoFirmaPaso.query.order_by(DocumentoFirmaPaso.orden).all()
        self.assertEqual(len(processes), 3)
        self.assertEqual([step.rol_firmante for step in processes], ["ELABORADOR", "REVISOR", "APROBADOR"])
        self.assertEqual(processes[0].estado, FIRMA_PASO_HABILITADO)
        self.assertEqual([step.estado for step in processes[1:]], ["PENDIENTE", "PENDIENTE"])
        self.assertEqual(Documento.query.get(501).estado, ESTADO_APROBADO)

    def test_detail_shows_final_signed_pdf_after_all_steps_complete(self):
        self.make_current_version_visible_in_detail()
        service = DocumentSignatureService(provider=FakeSignatureProvider())
        process = service.start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        for user_id in (201, 202, 203):
            step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
            service.upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(user_id),
                file_storage=self.signed_upload(f"firmado-ui-{user_id}"),
            )
        response = self.login(204).get("/documentacion/501")
        html = response.get_data(as_text=True)
        self.assertIn("Descargar PDF final firmado", html)
        self.assertIn("PDF_FIRMADO_FINAL", html)

    def test_missing_verified_identity_blocks_start(self):
        UsuarioIdentidadFirma.query.filter_by(usuario_id=202).delete()
        db.session.commit()
        with self.assertRaises(DocumentSignatureError):
            DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
                documento=Documento.query.get(501),
                version_doc=DocumentoVersion.query.get(1501),
                usuario=Usuario.query.get(204),
            )

    def test_pending_identity_blocks_start_button_and_service_start(self):
        self.make_current_version_visible_in_detail()
        self.clear_identity(202)
        db.session.add(UsuarioIdentidadFirma(
            empresa_id=101,
            usuario_id=202,
            identificacion="ID-202-P",
            estado=FIRMA_IDENTIDAD_PENDIENTE,
        ))
        db.session.commit()

        response = self.login(204).get("/documentacion/501")
        html = response.get_data(as_text=True)
        self.assertIn("Faltan identidades de firma verificadas", html)
        self.assertNotIn("Iniciar firma externa", html)
        with self.assertRaisesRegex(DocumentSignatureError, "Faltan identidades"):
            DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
                documento=Documento.query.get(501),
                version_doc=DocumentoVersion.query.get(1501),
                usuario=Usuario.query.get(204),
            )

    def test_revoked_identity_blocks_start(self):
        self.clear_identity(202)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        identity = service.create_identity(actor=actor, user_id=202, identificacion="ID-202-R")
        service.revoke_identity(actor=actor, identity_id=identity.id)
        db.session.refresh(identity)

        self.assertEqual(identity.estado, FIRMA_IDENTIDAD_REVOCADA)
        with self.assertRaisesRegex(DocumentSignatureError, "Faltan identidades"):
            DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
                documento=Documento.query.get(501),
                version_doc=DocumentoVersion.query.get(1501),
                usuario=Usuario.query.get(204),
            )

    def test_verifying_three_identities_shows_start_button_without_starting_process(self):
        self.make_current_version_visible_in_detail()
        for user_id in (201, 202, 203):
            self.clear_identity(user_id)
        service = DocumentSignatureIdentityService()
        actor = Usuario.query.get(204)
        document = Documento.query.get(501)
        version = DocumentoVersion.query.get(1501)
        artifact = DocumentoArtefacto.query.filter_by(documento_version_id=1501, tipo=ARTEFACTO_PDF_APROBADO).one()
        original_state = (document.estado, version.estado, artifact.archivo_sha256, artifact.storage_path)

        for user_id in (201, 202, 203):
            identity = service.create_identity(actor=actor, user_id=user_id, identificacion=f"ID-{user_id}-OK")
            service.verify_identity_mock(actor=actor, identity_id=identity.id)

        response = self.login(204).get("/documentacion/501")
        html = response.get_data(as_text=True)
        db.session.refresh(document)
        db.session.refresh(version)
        db.session.refresh(artifact)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Faltan identidades de firma verificadas", html)
        self.assertIn("Iniciar firma externa", html)
        self.assertEqual(DocumentoFirmaProceso.query.count(), 0)
        self.assertEqual((document.estado, version.estado, artifact.archivo_sha256, artifact.storage_path), original_state)

    def test_uploads_preserve_partial_and_final_immutable_artifacts(self):
        service = DocumentSignatureService(provider=FakeSignatureProvider())
        process = service.start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        for user_id in (201, 202, 203):
            step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
            artifact = service.upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(user_id),
                file_storage=self.signed_upload(f"firmado-{user_id}"),
            )
            self.assertTrue(artifact.inmutable)
            self.assertEqual(step.estado, FIRMA_PASO_FIRMADO)

        db.session.refresh(process)
        self.assertEqual(process.estado, FIRMA_PROCESO_COMPLETADO)
        self.assertEqual(
            DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(),
            2,
        )
        self.assertEqual(
            DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_FINAL).count(),
            1,
        )
        final_artifact = DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_FINAL).first()
        self.assertEqual(final_artifact.signature_count, 3)
        self.assertEqual(Documento.query.get(501).estado, ESTADO_APROBADO)
        self.assertIsNone(Documento.query.get(501).version_vigente_id)

    def test_strict_provider_without_crypto_library_rejects_upload(self):
        process = DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        with self.assertRaises(DocumentSignatureError):
            DocumentSignatureService().upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(201),
                file_storage=self.signed_upload("sin-validador-real"),
            )
        self.assertEqual(DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(), 0)

    def test_real_pyhanko_three_signature_sequence_completes_process(self):
        self.assertTrue(PyHankoPdfSignatureValidator().library_available())
        signer_material = {
            201: self.create_test_ca_and_cert("Elaborador Test ID-201", "ela@test.local", 201001),
            202: self.create_test_ca_and_cert("Revisor Test ID-202", "rev@test.local", 202001),
            203: self.create_test_ca_and_cert("Aprobador Test ID-203", "apr@test.local", 203001),
        }
        self.write_test_trust_root()
        for user_id, (_key, cert) in signer_material.items():
            self.update_identity_for_cert(user_id, cert)

        service = DocumentSignatureService()
        process = service.start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        current_pdf = resolve_document_path(process.pdf_origen.storage_path).read_bytes()
        observed_counts = []
        for order, user_id in enumerate((201, 202, 203), start=1):
            step = DocumentoFirmaPaso.query.filter_by(
                proceso_id=process.id,
                estado=FIRMA_PASO_HABILITADO,
            ).first()
            self.assertEqual(step.orden, order)
            key, cert = signer_material[user_id]
            signed_pdf = self.sign_pdf_with_test_cert(current_pdf, key, cert, f"Signature-{order}")
            artifact = service.upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(user_id),
                file_storage=self.real_signed_upload(signed_pdf, f"signed-{order}.pdf"),
            )
            observed_counts.append(artifact.signature_count)
            current_pdf = signed_pdf

        db.session.refresh(process)
        self.assertEqual(observed_counts, [1, 2, 3])
        self.assertEqual(process.estado, FIRMA_PROCESO_COMPLETADO)
        self.assertIsNotNone(process.pdf_final_id)
        final_artifact = DocumentoArtefacto.query.get(process.pdf_final_id)
        self.assertEqual(final_artifact.tipo, ARTEFACTO_PDF_FIRMADO_FINAL)
        self.assertEqual(final_artifact.signature_count, 3)
        self.assertTrue(final_artifact.inmutable)
        self.assertEqual(Documento.query.get(501).estado, ESTADO_APROBADO)
        self.assertEqual(DocumentoVersion.query.get(1501).estado, ESTADO_APROBADO)
        self.assertIsNone(Documento.query.get(501).version_vigente_id)

    def test_real_pyhanko_rejects_empty_trust_store_in_strict_mode(self):
        key, cert = self.create_test_ca_and_cert("Elaborador Test ID-201", "ela@test.local", 201001)
        self.update_identity_for_cert(201, cert)
        process = DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        source_pdf = resolve_document_path(process.pdf_origen.storage_path).read_bytes()
        signed_pdf = self.sign_pdf_with_test_cert(source_pdf, key, cert, "Signature-No-Trust")
        with self.assertRaisesRegex(DocumentSignatureError, "NO_CONFIABLE"):
            DocumentSignatureService().upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(201),
                file_storage=self.real_signed_upload(signed_pdf, "no-trust.pdf"),
            )
        db.session.refresh(step)
        self.assertEqual(step.estado, FIRMA_PASO_HABILITADO)
        self.assertEqual(DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(), 0)

    def test_real_pyhanko_rejects_wrong_fingerprint_identity(self):
        key, cert = self.create_test_ca_and_cert("Elaborador Test ID-201", "ela@test.local", 201001)
        self.write_test_trust_root()
        identity = self.update_identity_for_cert(201, cert)
        identity.certificado_fingerprint_sha256 = "0" * 64
        identity.metadata_json = {"certificate_fingerprint_sha256": "0" * 64}
        db.session.commit()
        process = DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        source_pdf = resolve_document_path(process.pdf_origen.storage_path).read_bytes()
        signed_pdf = self.sign_pdf_with_test_cert(source_pdf, key, cert, "Signature-Wrong-Fingerprint")
        with self.assertRaisesRegex(DocumentSignatureError, "IDENTIDAD_NO_COINCIDE"):
            DocumentSignatureService().upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(201),
                file_storage=self.real_signed_upload(signed_pdf, "wrong-fingerprint.pdf"),
            )
        db.session.refresh(step)
        self.assertEqual(step.estado, FIRMA_PASO_HABILITADO)
        self.assertEqual(DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(), 0)

    def test_real_pyhanko_rejects_corrupt_trust_root(self):
        key, cert = self.create_test_ca_and_cert("Elaborador Test ID-201", "ela@test.local", 201001)
        trust_dir = Path(self.temp_directory.name) / "corrupt-trust"
        trust_dir.mkdir(parents=True, exist_ok=True)
        (trust_dir / "corrupt.pem").write_text("not a certificate", encoding="utf-8")
        self.app.config["DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH"] = str(trust_dir)
        self.update_identity_for_cert(201, cert)
        process = DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        signed_pdf = self.sign_pdf_with_test_cert(resolve_document_path(process.pdf_origen.storage_path).read_bytes(), key, cert, "Signature-Corrupt-Trust")
        with self.assertRaisesRegex(DocumentSignatureError, "NO_CONFIABLE"):
            DocumentSignatureService().upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(201),
                file_storage=self.real_signed_upload(signed_pdf, "corrupt-trust.pdf"),
            )
        db.session.refresh(step)
        self.assertEqual(step.estado, FIRMA_PASO_HABILITADO)

    def test_real_pyhanko_requires_configured_intermediate_for_signer_chain(self):
        root_cert, intermediate_cert, signer_key, signer_cert = self.create_intermediate_chain("Elaborador Test ID-201", "ela@test.local", 8810)
        self.configure_chain_trust(root_cert, None, allowed_issuer=intermediate_cert)
        self.update_identity_for_cert(201, signer_cert)
        process = DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        source_pdf = resolve_document_path(process.pdf_origen.storage_path).read_bytes()
        signed_pdf = self.sign_pdf_with_cert_chain(source_pdf, signer_key, signer_cert, "Signature-Needs-Intermediate", [])

        with self.assertRaisesRegex(DocumentSignatureError, "NO_CONFIABLE|INVALIDA"):
            DocumentSignatureService().upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(201),
                file_storage=self.real_signed_upload(signed_pdf, "needs-intermediate.pdf"),
            )

        self.configure_chain_trust(root_cert, intermediate_cert, allowed_issuer=intermediate_cert)
        artifact = DocumentSignatureService().upload_signed_pdf(
            paso=step,
            usuario=Usuario.query.get(201),
            file_storage=self.real_signed_upload(signed_pdf, "with-intermediate.pdf"),
        )
        self.assertEqual(artifact.signature_count, 1)

    def test_real_pyhanko_accepts_auxiliary_tsa_style_intermediate_chain(self):
        root_cert, intermediate_cert, signer_key, signer_cert = self.create_intermediate_chain("TSA Auxiliar ID-201", "tsa@firma.test", 8811)
        self.configure_chain_trust(root_cert, intermediate_cert, allowed_issuer=intermediate_cert)
        self.update_identity_for_cert(201, signer_cert)
        process = DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        signed_pdf = self.sign_pdf_with_cert_chain(
            resolve_document_path(process.pdf_origen.storage_path).read_bytes(),
            signer_key,
            signer_cert,
            "Signature-Aux-Intermediate",
            [],
        )

        artifact = DocumentSignatureService().upload_signed_pdf(
            paso=step,
            usuario=Usuario.query.get(201),
            file_storage=self.real_signed_upload(signed_pdf, "aux-intermediate.pdf"),
        )

        self.assertEqual(artifact.validation_state, "VALIDA")

    def test_duplicate_upload_is_rejected_after_step_signed(self):
        service = DocumentSignatureService(provider=FakeSignatureProvider())
        process = service.start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        service.upload_signed_pdf(
            paso=step,
            usuario=Usuario.query.get(201),
            file_storage=self.signed_upload("signed-once"),
        )
        with self.assertRaisesRegex(DocumentSignatureError, "No puedes operar"):
            service.upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(201),
                file_storage=self.signed_upload("signed-twice"),
            )
        self.assertEqual(DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(), 1)

    def test_only_enabled_signer_can_upload(self):
        service = DocumentSignatureService(provider=FakeSignatureProvider())
        process = service.start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        with self.assertRaisesRegex(DocumentSignatureError, "No puedes operar"):
            service.upload_signed_pdf(
                paso=step,
                usuario=Usuario.query.get(202),
                file_storage=self.signed_upload("wrong-user"),
            )
        self.assertEqual(DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(), 0)

    def test_cross_tenant_step_is_not_operable(self):
        other_user = Usuario(
            empresa_id=102,
            nombre="Otro",
            apellido="Tenant",
            email="otro@firma",
            username="otro-firma",
            password_hash="x",
            activo=True,
        )
        db.session.add(other_user)
        db.session.commit()
        service = DocumentSignatureService(provider=FakeSignatureProvider())
        process = service.start_process(
            documento=Documento.query.get(501),
            version_doc=DocumentoVersion.query.get(1501),
            usuario=Usuario.query.get(204),
        )
        step = DocumentoFirmaPaso.query.filter_by(proceso_id=process.id, estado=FIRMA_PASO_HABILITADO).first()
        with self.assertRaisesRegex(DocumentSignatureError, "No puedes operar"):
            service.upload_signed_pdf(
                paso=step,
                usuario=other_user,
                file_storage=self.signed_upload("other-tenant"),
            )
        self.assertEqual(DocumentoArtefacto.query.filter_by(tipo=ARTEFACTO_PDF_FIRMADO_PARCIAL).count(), 0)


if __name__ == "__main__":
    unittest.main()
