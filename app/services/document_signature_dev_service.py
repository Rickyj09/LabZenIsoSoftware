import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models.auditoria import AuditoriaLog
from app.models.documentos import (
    FIRMA_IDENTIDAD_VERIFICADA,
    FIRMA_PROCESO_EN_FIRMA,
    DocumentoFirmaProceso,
    UsuarioIdentidadFirma,
)
from app.models.seguridad import Usuario
from app.services.storage_service import resolve_document_path


DEV_CERTIFICATES_INITIALIZED = "DEV_CERTIFICATES_INITIALIZED"
DEV_IDENTITY_SYNCHRONIZED = "DEV_IDENTITY_SYNCHRONIZED"
DEV_TEST_SIGNATURE_REQUESTED = "DEV_TEST_SIGNATURE_REQUESTED"
DEV_TEST_SIGNATURE_VALIDATED = "DEV_TEST_SIGNATURE_VALIDATED"
DEV_TEST_SIGNATURE_REJECTED = "DEV_TEST_SIGNATURE_REJECTED"


@dataclass(frozen=True)
class DevSignatureTarget:
    username: str
    role: str
    identification: str
    common_name: str


@dataclass(frozen=True)
class PdfPageGeometry:
    page_index: int
    page_count: int
    media_box: tuple
    crop_box: tuple
    rotation: int
    width: float
    height: float


@dataclass(frozen=True)
class SignatureAppearancePlacement:
    role: str
    field_name: str
    normalized_box: tuple
    box: tuple
    page_index: int


DEV_SIGNATURE_TARGETS = (
    DevSignatureTarget("tecnico_documental", "ELABORADOR", "DEV-TEC-001", "Usuario Tecnico"),
    DevSignatureTarget("revisor_documental", "REVISOR", "DEV-REV-001", "Usuario Revisor"),
    DevSignatureTarget("admin", "APROBADOR", "DEV-ADM-001", "Ricardo Admin"),
)

FIELD_NAMES = {
    "ELABORADOR": "LabZenISO_Elaborador",
    "REVISOR": "LabZenISO_Revisor",
    "APROBADOR": "LabZenISO_Aprobador",
}

ROLE_ORDER = ("ELABORADOR", "REVISOR", "APROBADOR")

ROLE_CONFIG_KEYS = {
    "ELABORADOR": "DOCUMENT_SIGNATURES_DEV_ELABORADOR_BOX",
    "REVISOR": "DOCUMENT_SIGNATURES_DEV_REVISOR_BOX",
    "APROBADOR": "DOCUMENT_SIGNATURES_DEV_APROBADOR_BOX",
}

DEV_SIGNATURE_LAYOUT_PROFILES = {
    "DEFAULT": {
        "page": "last",
        "boxes": {
            "ELABORADOR": (0.62, 0.205, 0.93, 0.255),
            "REVISOR": (0.62, 0.145, 0.93, 0.195),
            "APROBADOR": (0.62, 0.085, 0.93, 0.135),
        },
    },
    "PROCEDIMIENTO": {
        "page": "last",
        "boxes": {
            "ELABORADOR": (0.02, 0.18, 0.32, 0.28),
            "REVISOR": (0.35, 0.18, 0.65, 0.28),
            "APROBADOR": (0.68, 0.18, 0.98, 0.28),
        },
    },
}

SIGNATURE_REASONS = {
    "ELABORADOR": "Elaboracion del documento. MODO DESARROLLO: certificado local de prueba sin validez legal.",
    "REVISOR": "Revision tecnica del documento. MODO DESARROLLO: certificado local de prueba sin validez legal.",
    "APROBADOR": "Aprobacion del documento. MODO DESARROLLO: certificado local de prueba sin validez legal.",
}


class DocumentSignatureDevError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _environment(app):
    return (app.config.get("APP_ENV") or os.getenv("FLASK_ENV") or "development").strip().lower()


def dev_signature_mode_enabled(app=None):
    app = app or current_app
    return bool(app.config.get("DOCUMENT_SIGNATURES_DEV_TEST_MODE")) and _environment(app) in {"development", "testing"}


def assert_dev_signature_mode(app=None):
    app = app or current_app
    if not dev_signature_mode_enabled(app):
        raise DocumentSignatureDevError("El modo de firma de prueba no esta habilitado.")
    if not (app.config.get("DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD") or "").strip():
        raise DocumentSignatureDevError("La contrasena local de claves de desarrollo es obligatoria.")


class DocumentSignatureDevCertificateService:
    ca_cert_name = "labzeniso-dev-ca.cert.pem"
    ca_key_name = "labzeniso-dev-ca.key.pem"

    def __init__(self, app=None):
        self.app = app or current_app

    @property
    def cert_dir(self):
        configured = Path(self.app.config.get("DOCUMENT_SIGNATURES_DEV_CERT_DIR") or "instance/dev_signature_certificates")
        if configured.is_absolute():
            return configured
        return Path(self.app.root_path).parent / configured

    @property
    def password(self):
        return (self.app.config.get("DOCUMENT_SIGNATURES_DEV_KEY_PASSWORD") or "").encode("utf-8")

    @property
    def ca_cert_path(self):
        return self.cert_dir / self.ca_cert_name

    @property
    def ca_key_path(self):
        return self.cert_dir / self.ca_key_name

    def initialize(self, *, regenerate=False, confirm_active_process=False, reporter=None):
        assert_dev_signature_mode(self.app)
        if regenerate:
            active_count = DocumentoFirmaProceso.query.filter_by(estado=FIRMA_PROCESO_EN_FIRMA).count()
            if active_count and not confirm_active_process:
                raise DocumentSignatureDevError(
                    "Existen procesos de firma activos; usa confirmacion explicita para regenerar certificados."
                )
            self._remove_known_certificate_files()

        self.cert_dir.mkdir(parents=True, exist_ok=True)
        self._restrict_path(self.cert_dir, directory=True)
        created = []
        ca_cert, ca_key = self._ensure_ca(created)
        certs = {}
        for target in DEV_SIGNATURE_TARGETS:
            certs[target.username] = self._ensure_user_certificate(target, ca_cert, ca_key, created)

        synchronized = self.sync_identities(certs=certs)
        self._audit_system(DEV_CERTIFICATES_INITIALIZED, {
            "created": created,
            "certificate_dir": str(self.cert_dir),
            "fingerprints": {username: item["fingerprint"] for username, item in certs.items()},
            "synchronized": synchronized,
            "environment": _environment(self.app),
            "regenerate": regenerate,
        })
        db.session.commit()
        if reporter:
            reporter(f"Directorio: {self.cert_dir}")
            reporter(f"CA publica: {self.ca_cert_path.name}")
            for target in DEV_SIGNATURE_TARGETS:
                cert = certs[target.username]
                reporter(
                    f"{target.username} {target.role} identificacion={target.identification} "
                    f"fingerprint={cert['fingerprint']}"
                )
            reporter(f"Identidades sincronizadas: {len(synchronized)}")
        return {
            "created": created,
            "certificates": certs,
            "synchronized": synchronized,
            "certificate_dir": str(self.cert_dir),
            "ca_certificate": str(self.ca_cert_path),
        }

    def sync_identities(self, *, certs=None):
        certs = certs or {target.username: self.load_user_certificate_info(target.username) for target in DEV_SIGNATURE_TARGETS}
        synchronized = []
        for target in DEV_SIGNATURE_TARGETS:
            cert_info = certs.get(target.username)
            if not cert_info:
                continue
            users = Usuario.query.filter_by(username=target.username, activo=True).all()
            for user in users:
                identity = self._identity_for_user(user)
                before = self._identity_snapshot(identity)
                if identity is None:
                    identity = UsuarioIdentidadFirma(
                        empresa_id=user.empresa_id,
                        usuario_id=user.id,
                        identificacion=target.identification,
                        nombre_certificado=cert_info["subject"],
                        emisor_certificado=cert_info["issuer"],
                        certificado_fingerprint_sha256=cert_info["fingerprint"],
                        estado=FIRMA_IDENTIDAD_VERIFICADA,
                        verificado_por_id=self._verifier_for_user(user).id,
                        verificado_en=_now(),
                        metadata_json={},
                    )
                    db.session.add(identity)
                identity.identificacion = target.identification
                identity.nombre_certificado = cert_info["subject"]
                identity.emisor_certificado = cert_info["issuer"]
                identity.certificado_fingerprint_sha256 = cert_info["fingerprint"]
                identity.estado = FIRMA_IDENTIDAD_VERIFICADA
                identity.verificado_por_id = self._verifier_for_user(user).id
                identity.verificado_en = _now()
                identity.metadata_json = {
                    **(identity.metadata_json or {}),
                    "dev_test_certificate": True,
                    "local_mock_verification": True,
                    "certificate_serial": cert_info["serial"],
                    "certificate_subject": cert_info["subject"],
                    "certificate_issuer": cert_info["issuer"],
                    "certificate_email": cert_info["email"],
                    "certificate_path": cert_info["logical_certificate_path"],
                    "generated_at": cert_info["generated_at"],
                    "entorno": _environment(self.app),
                    "role": target.role,
                }
                db.session.flush()
                self._audit_identity(
                    user=user,
                    identity=identity,
                    before=before,
                    after=self._identity_snapshot(identity),
                )
                synchronized.append({
                    "empresa_id": user.empresa_id,
                    "usuario_id": user.id,
                    "username": user.username,
                    "identificacion": identity.identificacion,
                    "fingerprint": identity.certificado_fingerprint_sha256,
                })
        return synchronized

    def certificate_for_user(self, user):
        assert_dev_signature_mode(self.app)
        target = self._target_for_username(user.username)
        if not target:
            return None
        cert_info = self.load_user_certificate_info(user.username)
        identity = self._identity_for_user(user)
        if not identity or identity.estado != FIRMA_IDENTIDAD_VERIFICADA:
            return None
        if (identity.certificado_fingerprint_sha256 or "").lower() != cert_info["fingerprint"]:
            return None
        return cert_info

    def sign_step_pdf(self, paso):
        assert_dev_signature_mode(self.app)
        user = paso.usuario
        target = self._target_for_username(user.username if user else "")
        if not target:
            raise DocumentSignatureDevError("No existe certificado de prueba para el usuario firmante.")
        cert_info = self.certificate_for_user(user)
        if not cert_info:
            raise DocumentSignatureDevError("La identidad verificada no coincide con el certificado de prueba.")
        input_artifact = paso.artifact_entrada or paso.proceso.pdf_origen
        input_path = resolve_document_path(input_artifact.storage_path)
        placements = self.signature_placements_for_pdf(input_path, documento=paso.documento)
        placement = placements[target.role]
        output = tempfile.NamedTemporaryFile(prefix="labzeniso-dev-pades-", suffix=".pdf", delete=False)
        output_path = Path(output.name)
        output.close()
        try:
            signer = self._pyhanko_signer(user.username)
            from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
            from pyhanko.sign import fields, signers

            with input_path.open("rb") as source, output_path.open("wb") as destination:
                writer = IncrementalPdfFileWriter(source)
                pdf_signer = signers.PdfSigner(
                    signature_meta=signers.PdfSignatureMetadata(
                        field_name=placement.field_name,
                        md_algorithm="sha256",
                        reason=SIGNATURE_REASONS[target.role],
                        location="LabZenISO desarrollo",
                        name=target.common_name,
                    ),
                    signer=signer,
                    new_field_spec=fields.SigFieldSpec(
                        sig_field_name=placement.field_name,
                        on_page=placement.page_index,
                        box=placement.box,
                    ),
                    stamp_style=self._signature_stamp_style(),
                )
                pdf_signer.sign_pdf(
                    writer,
                    output=destination,
                    appearance_text_params={
                        "signer": target.common_name,
                        "role": target.role,
                    },
                )
            return output_path
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

    def preview_signature_locations(self, input_path, *, documento=None):
        assert_dev_signature_mode(self.app)
        input_path = Path(input_path)
        output = tempfile.NamedTemporaryFile(prefix="labzeniso-dev-preview-", suffix=".pdf", delete=False)
        output_path = Path(output.name)
        output.close()
        try:
            placements = self.signature_placements_for_pdf(input_path, documento=documento)
            from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
            from pyhanko.pdf_utils.layout import BoxConstraints
            from pyhanko.stamp import TextStamp, TextStampStyle
            from pyhanko.pdf_utils.text import TextBoxStyle

            with input_path.open("rb") as source, output_path.open("wb") as destination:
                writer = IncrementalPdfFileWriter(source)
                style = TextStampStyle(
                    border_width=1,
                    border_color=(0.85, 0.18, 0.10),
                    background_opacity=0.08,
                    text_box_style=TextBoxStyle(font_size=8, text_color=(0.70, 0.05, 0.03)),
                    stamp_text="%(role)s\nPREVISUALIZACION - SIN FIRMAS",
                    timestamp_format="%Y-%m-%d %H:%M",
                )
                for role in ROLE_ORDER:
                    placement = placements[role]
                    x1, y1, x2, y2 = placement.box
                    stamp = TextStamp(
                        writer=writer,
                        style=style,
                        box=BoxConstraints(width=x2 - x1, height=y2 - y1),
                        text_params={"role": role},
                    )
                    stamp.apply(placement.page_index, x1, y1)
                writer.write(destination)
            return output_path
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

    def signature_placements_for_pdf(self, input_path, *, documento=None):
        assert_dev_signature_mode(self.app)
        input_path = Path(input_path)
        geometry = self._page_geometry(input_path, self._configured_page_value(documento))
        placements = {}
        for role in ROLE_ORDER:
            normalized_box = self._normalized_box_for_role(role, documento)
            placements[role] = SignatureAppearancePlacement(
                role=role,
                field_name=FIELD_NAMES[role],
                normalized_box=normalized_box,
                box=self._normalised_to_pdf_box(normalized_box, geometry),
                page_index=geometry.page_index,
            )
        self._validate_placements(placements, geometry)
        return placements

    def load_user_certificate_info(self, username):
        target = self._target_for_username(username)
        if not target:
            raise DocumentSignatureDevError("Usuario sin certificado de desarrollo configurado.")
        cert_path = self._user_cert_path(username)
        if not cert_path.exists():
            raise DocumentSignatureDevError(f"No existe certificado de desarrollo para {username}.")
        cert = self._load_crypto_certificate(cert_path)
        subject = cert.subject.rfc4514_string()
        issuer = cert.issuer.rfc4514_string()
        email = self._certificate_email(cert)
        return {
            "username": username,
            "role": target.role,
            "identification": target.identification,
            "fingerprint": self._fingerprint(cert),
            "serial": str(cert.serial_number),
            "subject": subject,
            "issuer": issuer,
            "email": email,
            "certificate_path": str(cert_path),
            "logical_certificate_path": f"dev_signature_certificates/{cert_path.name}",
            "generated_at": datetime.fromtimestamp(cert_path.stat().st_mtime, tz=timezone.utc).isoformat(),
        }

    def _ensure_ca(self, created):
        if self.ca_cert_path.exists() and self.ca_key_path.exists():
            return self._load_crypto_certificate(self.ca_cert_path), self._load_private_key(self.ca_key_path)

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "LabZenISO Development Test CA"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - timedelta(days=1))
            .not_valid_after(_now() + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ), critical=True)
            .sign(key, hashes.SHA256())
        )
        self._write_public_cert(self.ca_cert_path, cert)
        self._write_private_key(self.ca_key_path, key, serialization)
        created.extend([self.ca_cert_path.name, self.ca_key_path.name])
        return cert, key

    def _ensure_user_certificate(self, target, ca_cert, ca_key, created):
        cert_path = self._user_cert_path(target.username)
        key_path = self._user_key_path(target.username)
        if cert_path.exists() and key_path.exists():
            return self.load_user_certificate_info(target.username)

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

        user = Usuario.query.filter_by(username=target.username, activo=True).order_by(Usuario.id.asc()).first()
        email = user.email if user and user.email else f"{target.username}@dev.labzeniso.local"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, f"{target.common_name} {target.identification}"),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, email),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LabZenISO Development"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, target.role),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - timedelta(days=1))
            .not_valid_after(_now() + timedelta(days=120))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.RFC822Name(email)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .add_extension(x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        self._write_public_cert(cert_path, cert)
        self._write_private_key(key_path, key, serialization)
        created.extend([cert_path.name, key_path.name])
        return self.load_user_certificate_info(target.username)

    def _pyhanko_signer(self, username):
        from asn1crypto import keys as asn1_keys
        from asn1crypto import x509 as asn1_x509
        from cryptography.hazmat.primitives import serialization
        from pyhanko.sign import signers
        from pyhanko_certvalidator.registry import SimpleCertificateStore

        cert = self._load_crypto_certificate(self._user_cert_path(username))
        key = self._load_private_key(self._user_key_path(username))
        ca_cert = self._load_crypto_certificate(self.ca_cert_path)
        signing_cert = asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
        signing_key = asn1_keys.PrivateKeyInfo.load(key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        ca_asn1 = asn1_x509.Certificate.load(ca_cert.public_bytes(serialization.Encoding.DER))
        return signers.SimpleSigner(
            signing_cert=signing_cert,
            signing_key=signing_key,
            cert_registry=SimpleCertificateStore.from_certs([ca_asn1]),
        )

    def _load_crypto_certificate(self, path):
        from cryptography import x509

        return x509.load_pem_x509_certificate(path.read_bytes())

    def _load_private_key(self, path):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_private_key(path.read_bytes(), password=self.password)

    def _write_public_cert(self, path, cert):
        from cryptography.hazmat.primitives import serialization

        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self._restrict_path(path)

    def _write_private_key(self, path, key, serialization):
        path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(self.password),
        ))
        self._restrict_path(path)

    def _restrict_path(self, path, directory=False):
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if directory else 0))
        except OSError:
            pass

    def _remove_known_certificate_files(self):
        if self.cert_dir.exists():
            for path in self.cert_dir.iterdir():
                if path.is_file() and path.suffix.lower() == ".pem":
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)

    def _user_cert_path(self, username):
        return self.cert_dir / f"{username}.cert.pem"

    def _user_key_path(self, username):
        return self.cert_dir / f"{username}.key.pem"

    def _target_for_username(self, username):
        return next((target for target in DEV_SIGNATURE_TARGETS if target.username == username), None)

    def _identity_for_user(self, user):
        return (
            UsuarioIdentidadFirma.query
            .filter_by(empresa_id=user.empresa_id, usuario_id=user.id)
            .order_by(
                (UsuarioIdentidadFirma.identificacion.in_(("MOCK-TEC-001", "MOCK-REV-001", "MOCK-ADM-001"))).desc(),
                UsuarioIdentidadFirma.verificado_en.desc().nullslast(),
                UsuarioIdentidadFirma.id.desc(),
            )
            .first()
        )

    def _verifier_for_user(self, user):
        admin = Usuario.query.filter_by(empresa_id=user.empresa_id, username="admin", activo=True).first()
        return admin or user

    def _certificate_email(self, cert):
        from cryptography.x509.oid import NameOID

        values = cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
        return values[0].value if values else None

    def _fingerprint(self, cert):
        from cryptography.hazmat.primitives import hashes

        return cert.fingerprint(hashes.SHA256()).hex()

    def _signature_stamp_style(self):
        from pyhanko.pdf_utils.text import TextBoxStyle
        from pyhanko.stamp import TextStampStyle

        return TextStampStyle(
            border_width=1,
            border_color=(0.22, 0.36, 0.48),
            background_opacity=0.04,
            text_box_style=TextBoxStyle(font_size=7, text_color=(0.05, 0.10, 0.14)),
            stamp_text=(
                "%(signer)s\n"
                "%(role)s\n"
                "Firmado digitalmente\n"
                "%(ts)s\n"
                "CERTIFICADO DE DESARROLLO\n"
                "SIN VALIDEZ LEGAL"
            ),
            timestamp_format="%Y-%m-%d %H:%M",
        )

    def _layout_profile_name(self, documento=None):
        explicit = (self.app.config.get("DOCUMENT_SIGNATURES_DEV_LAYOUT_PROFILE") or "").strip().upper()
        if explicit:
            return explicit if explicit in DEV_SIGNATURE_LAYOUT_PROFILES else "DEFAULT"
        tipo = ((getattr(documento, "tipo", None) or getattr(documento, "tipo_documento", None) or "")).strip().upper()
        return "PROCEDIMIENTO" if tipo == "PROCEDIMIENTO" else "DEFAULT"

    def _layout_profile(self, documento=None):
        return DEV_SIGNATURE_LAYOUT_PROFILES[self._layout_profile_name(documento)]

    def _configured_page_value(self, documento=None):
        return (
            self.app.config.get("DOCUMENT_SIGNATURES_DEV_APPEARANCE_PAGE")
            or self._layout_profile(documento)["page"]
            or "last"
        )

    def _normalized_box_for_role(self, role, documento=None):
        configured = (self.app.config.get(ROLE_CONFIG_KEYS[role]) or "").strip()
        if configured:
            return self._parse_normalized_box(configured, ROLE_CONFIG_KEYS[role])
        return tuple(self._layout_profile(documento)["boxes"][role])

    def _parse_normalized_box(self, value, key):
        try:
            parts = tuple(float(part.strip()) for part in value.split(","))
        except ValueError as exc:
            raise DocumentSignatureDevError(f"{key} debe tener cuatro numeros separados por coma.") from exc
        if len(parts) != 4:
            raise DocumentSignatureDevError(f"{key} debe tener el formato x1,y1,x2,y2.")
        if any(part < 0 or part > 1 for part in parts):
            raise DocumentSignatureDevError(f"{key} debe usar coordenadas normalizadas entre 0.0 y 1.0.")
        return parts

    def _page_geometry(self, input_path, page_value):
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.pdf_utils.rw_common import find_inherited_value_in_tree

        with Path(input_path).open("rb") as source:
            reader = PdfFileReader(source)
            page_count = int(reader.root["/Pages"]["/Count"])
            page_index = self._resolve_page_index(page_value, page_count)
            page_ref, _resources = reader.find_page_for_modification(page_index)
            page_obj = page_ref.get_object()
            media_box = self._pdf_box_tuple(find_inherited_value_in_tree(page_obj, "/MediaBox", "/Parent"))
            crop_box = self._pdf_box_tuple(
                find_inherited_value_in_tree(page_obj, "/CropBox", "/Parent") or media_box
            )
            rotation = int(find_inherited_value_in_tree(page_obj, "/Rotate", "/Parent") or 0) % 360
            width = crop_box[2] - crop_box[0]
            height = crop_box[3] - crop_box[1]
            if width <= 0 or height <= 0:
                raise DocumentSignatureDevError("La pagina de firma tiene CropBox invalido.")
            return PdfPageGeometry(
                page_index=page_index,
                page_count=page_count,
                media_box=media_box,
                crop_box=crop_box,
                rotation=rotation,
                width=width,
                height=height,
            )

    def _resolve_page_index(self, page_value, page_count):
        value = str(page_value or "last").strip().lower()
        if value == "last":
            return page_count - 1
        try:
            page_index = int(value)
        except ValueError as exc:
            raise DocumentSignatureDevError("DOCUMENT_SIGNATURES_DEV_APPEARANCE_PAGE debe ser 'last' o un indice numerico.") from exc
        if not 0 <= page_index < page_count:
            raise DocumentSignatureDevError("La pagina configurada para firmas no existe en el PDF.")
        return page_index

    def _pdf_box_tuple(self, box):
        if box is None or len(box) != 4:
            raise DocumentSignatureDevError("La pagina de firma no tiene MediaBox/CropBox valido.")
        return tuple(float(item) for item in box)

    def _normalised_to_pdf_box(self, normalized_box, geometry):
        x1, y1, x2, y2 = normalized_box
        left, bottom, _right, _top = geometry.crop_box
        return (
            int(round(left + x1 * geometry.width)),
            int(round(bottom + y1 * geometry.height)),
            int(round(left + x2 * geometry.width)),
            int(round(bottom + y2 * geometry.height)),
        )

    def _validate_placements(self, placements, geometry):
        for placement in placements.values():
            x1, y1, x2, y2 = placement.box
            left, bottom, right, top = geometry.crop_box
            if placement.page_index < 0 or placement.page_index >= geometry.page_count:
                raise DocumentSignatureDevError("La pagina configurada para firmas no existe en el PDF.")
            if x2 <= x1 or y2 <= y1:
                raise DocumentSignatureDevError(f"La caja de firma {placement.role} tiene ancho o alto invalido.")
            if x1 < left or y1 < bottom or x2 > right or y2 > top:
                raise DocumentSignatureDevError(f"La caja de firma {placement.role} queda fuera del CropBox de la pagina.")

        roles = list(placements)
        for index, role in enumerate(roles):
            for other_role in roles[index + 1:]:
                if self._boxes_overlap(placements[role].box, placements[other_role].box):
                    raise DocumentSignatureDevError(
                        f"Las cajas de firma {role} y {other_role} se superponen."
                    )

    def _boxes_overlap(self, first, second):
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1

    def _identity_snapshot(self, identity):
        if not identity:
            return None
        return {
            "id": identity.id,
            "usuario_id": identity.usuario_id,
            "identificacion": identity.identificacion,
            "estado": identity.estado,
            "fingerprint": identity.certificado_fingerprint_sha256,
            "metadata_json": identity.metadata_json or {},
        }

    def _audit_identity(self, *, user, identity, before, after):
        db.session.add(AuditoriaLog(
            empresa_id=user.empresa_id,
            usuario_id=identity.verificado_por_id,
            tabla="usuario_identidades_firma",
            registro_id=identity.id,
            accion=DEV_IDENTITY_SYNCHRONIZED,
            datos_antes=before,
            datos_despues=after,
        ))

    def _audit_system(self, action, data):
        for empresa_id in {item["empresa_id"] for item in data.get("synchronized", [])} or {None}:
            db.session.add(AuditoriaLog(
                empresa_id=empresa_id,
                usuario_id=None,
                tabla="dev_signature_certificates",
                registro_id=0,
                accion=action,
                datos_antes=None,
                datos_despues=data,
            ))
