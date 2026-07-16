import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

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
    ARTEFACTO_PDF_FIRMADO_FINAL,
    ARTEFACTO_PDF_FIRMADO_PARCIAL,
    ESTADO_APROBADO,
    FIRMA_IDENTIDAD_VERIFICADA,
    FIRMA_PASO_FIRMADO,
    FIRMA_PASO_HABILITADO,
    FIRMA_PROCESO_COMPLETADO,
    FIRMA_PROCESO_EN_FIRMA,
    Documento,
    DocumentoArtefacto,
    DocumentoFirmaPaso,
    DocumentoSnapshot,
    DocumentoVersion,
    UsuarioIdentidadFirma,
)
from app.models.empresa import Empresa
from app.models.seguridad import Usuario
from app.services.document_pdf_service import DocumentPdfService
from app.services.document_signature_service import (
    DocumentSignatureError,
    DocumentSignatureService,
    PyHankoPdfSignatureValidator,
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
        self.seed_data()

    def tearDown(self):
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

    def seed_data(self):
        db.session.add(Empresa(id=101, nombre="Empresa firma"))
        users = [
            Usuario(id=201, empresa_id=101, nombre="Ela", apellido="Borador", email="ela@firma", username="ela", password_hash="x", activo=True),
            Usuario(id=202, empresa_id=101, nombre="Re", apellido="Visor", email="rev@firma", username="rev", password_hash="x", activo=True),
            Usuario(id=203, empresa_id=101, nombre="Apro", apellido="Bador", email="apr@firma", username="apr", password_hash="x", activo=True),
            Usuario(id=204, empresa_id=101, nombre="Admin", apellido="Calidad", email="admin@firma", username="admin", password_hash="x", activo=True),
        ]
        db.session.add_all(users)
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

    def update_identity_for_cert(self, user_id, cert):
        identity = UsuarioIdentidadFirma.query.filter_by(usuario_id=user_id).first()
        identity.certificado_fingerprint_sha256 = self.cert_sha256(cert)
        identity.emisor_certificado = self._test_ca_cert.subject.rfc4514_string()
        identity.metadata_json = {
            "certificate_fingerprint_sha256": self.cert_sha256(cert),
            "certificate_serial": str(cert.serial_number),
            "certificate_issuer": "Common Name: LabZenISO Test Root CA",
            "certificate_email": cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)[0].value,
            "certificate_subject": "Email Address: "
            + cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)[0].value
            + ", Common Name: "
            + cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
        }
        db.session.commit()
        return identity

    def sign_pdf_with_test_cert(self, pdf_bytes, key, cert, field_name):
        signing_cert = asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
        signing_key = asn1_keys.PrivateKeyInfo.load(key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        ca_cert = asn1_x509.Certificate.load(self._test_ca_cert.public_bytes(serialization.Encoding.DER))
        store = SimpleCertificateStore.from_certs([ca_cert])
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

    def test_missing_verified_identity_blocks_start(self):
        UsuarioIdentidadFirma.query.filter_by(usuario_id=202).delete()
        db.session.commit()
        with self.assertRaises(DocumentSignatureError):
            DocumentSignatureService(provider=FakeSignatureProvider()).start_process(
                documento=Documento.query.get(501),
                version_doc=DocumentoVersion.query.get(1501),
                usuario=Usuario.query.get(204),
            )

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
