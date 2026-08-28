import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from flask import current_app

from app.extensions import db
from app.models.documentos import (
    ARTEFACTO_DISPONIBLE,
    ARTEFACTO_PDF_APROBADO,
    ARTEFACTO_PDF_APROBADO_CON_QR,
    ARTEFACTO_PDF_FIRMADO_FINAL,
    ARTEFACTO_PDF_FIRMADO_PARCIAL,
    ESTADO_APROBADO,
    FIRMA_EVENTO_CANCELADO,
    FIRMA_EVENTO_ERROR,
    FIRMA_EVENTO_PASO_FIRMADO,
    FIRMA_EVENTO_PASO_HABILITADO,
    FIRMA_EVENTO_PDF_DESCARGADO,
    FIRMA_EVENTO_PDF_SUBIDO,
    FIRMA_EVENTO_PROCESO_COMPLETADO,
    FIRMA_EVENTO_PROCESO_CREADO,
    FIRMA_EVENTO_RECHAZADO,
    FIRMA_EVENTO_VALIDACION_ERROR,
    FIRMA_EVENTO_VALIDACION_OK,
    FIRMA_IDENTIDAD_VERIFICADA,
    FIRMA_PASO_CANCELADO,
    FIRMA_PASO_ERROR,
    FIRMA_PASO_FIRMADO,
    FIRMA_PASO_HABILITADO,
    FIRMA_PASO_PENDIENTE,
    FIRMA_PASO_RECHAZADO,
    FIRMA_PROCESO_CANCELADO,
    FIRMA_PROCESO_COMPLETADO,
    FIRMA_PROCESO_EN_FIRMA,
    FIRMA_PROCESO_PENDIENTE,
    FIRMA_PROCESO_RECHAZADO,
    FIRMA_PROVEEDOR_EXTERNO_CONTROLADO,
    FIRMA_ROL_APROBADOR,
    FIRMA_ROL_ELABORADOR,
    FIRMA_ROL_REVISOR,
    DocumentoArtefacto,
    DocumentoFirmaEvento,
    DocumentoFirmaPaso,
    DocumentoFirmaProceso,
    DocumentoSnapshot,
    SNAPSHOT_APROBADO,
    SNAPSHOT_DISPONIBLE,
    UsuarioIdentidadFirma,
)
from app.security.permissions import user_has_permission
from app.services.document_pdf_service import DocumentPdfError, DocumentPdfService, PDF_MIME
from app.services.document_publication_service import DocumentPublicationError, DocumentPublicationService
from app.services.office_document_profile import get_onlyoffice_document_profile
from app.services.storage_service import (
    DocumentStorageError,
    delete_pdf_artifact_file,
    file_digest_and_size,
    resolve_document_path,
    store_signed_pdf_artifact_copy,
)


class DocumentSignatureError(ValueError):
    pass


START_SIGNATURE_PERMISSION = "documentos.firmas.iniciar"
FIRMASEGURA_IDENTIFICATION_OID = "1.3.6.1.4.1.61305.3.1"


@dataclass(frozen=True)
class SignatureValidationResult:
    is_valid: bool
    status: str
    integrity_valid: bool = False
    trusted: bool = False
    identity_match: bool = False
    certificate_valid_at_signing: bool = False
    revocation_checked: bool = False
    revocation_status: str = "NO_VERIFICADA"
    previous_signatures_valid: bool = False
    modification_level: str = "UNKNOWN"
    new_signature_count: int = 0
    total_signature_count: int = 0
    signer_identifier: str | None = None
    certificate_fingerprint_sha256: str | None = None
    certificate_serial: str | None = None
    certificate_subject: str | None = None
    certificate_issuer: str | None = None
    certificate_common_name: str | None = None
    certificate_email: str | None = None
    certificate_identification: str | None = None
    certificate_valid_from: datetime | None = None
    certificate_valid_to: datetime | None = None
    signing_time: datetime | None = None
    covered_revision: int | None = None
    latest_revision: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sanitized_details: str = ""
    provider: str = FIRMA_PROVEEDOR_EXTERNO_CONTROLADO
    metadata: dict | None = None
    error_code: str | None = None

    @property
    def valid(self):
        return self.is_valid

    @property
    def state(self):
        return self.status

    @property
    def signature_count(self):
        return self.total_signature_count

    @property
    def summary(self):
        return self.sanitized_details or self.status


def _now():
    return datetime.now(timezone.utc)


def _normalized_sha256(value):
    value = (value or "").strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else None


def _normalize_identity_value(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


class PyHankoPdfSignatureValidator:
    """Adaptador real de validacion PDF/PAdES basado en pyHanko."""

    def __init__(self, app=None):
        self.app = app or current_app

    def library_available(self):
        try:
            import pyhanko  # noqa: F401
            import pyhanko_certvalidator  # noqa: F401
            return True
        except Exception:
            return False

    def validate_pdf(self, *, signed_pdf_path: Path, input_artifact, expected_step, identidad) -> SignatureValidationResult:
        if not self.library_available():
            return self._result(
                False,
                "LIBRERIA_NO_DISPONIBLE",
                errors=["pyHanko o pyhanko-certvalidator no estan disponibles."],
                error_code="PDF_SIGNATURE_LIBRARY_UNAVAILABLE",
            )
        try:
            trust_roots = self._load_trust_roots()
            intermediate_certs = self._load_intermediate_certs()
            allowed_issuers = self._load_allowed_issuers()
        except DocumentSignatureError as exc:
            return self._result(
                False,
                "NO_CONFIABLE",
                errors=[str(exc)],
                error_code="SIGNATURE_TRUST_STORE_INVALID",
            )

        try:
            from pyhanko.pdf_utils.reader import PdfFileReader
            from pyhanko.sign.validation import validate_pdf_signature
            from pyhanko_certvalidator import ValidationContext
        except Exception as exc:
            return self._result(
                False,
                "LIBRERIA_NO_DISPONIBLE",
                errors=[self._sanitize_error(exc)],
                error_code="PDF_SIGNATURE_LIBRARY_UNAVAILABLE",
            )

        try:
            with signed_pdf_path.open("rb") as handle:
                reader = PdfFileReader(handle, strict=False)
                signatures = list(getattr(reader, "embedded_signatures", []) or [])
                if not signatures:
                    return self._result(
                        False,
                        "FIRMA_FALTANTE",
                        errors=["El PDF no contiene firmas digitales embebidas."],
                        total_signature_count=0,
                        error_code="PDF_WITHOUT_SIGNATURES",
                    )

                statuses = []
                for signature in signatures:
                    vc = ValidationContext(
                        trust_roots=trust_roots,
                        other_certs=intermediate_certs,
                        allow_fetching=False,
                        revocation_mode=self.app.config.get("DOCUMENT_SIGNATURE_REVOCATION_MODE", "soft-fail"),
                    )
                    statuses.append(validate_pdf_signature(signature, signer_validation_context=vc, skip_diff=False))
        except Exception as exc:
            return self._result(
                False,
                "PDF_INVALIDO",
                errors=[self._sanitize_error(exc)],
                error_code="PDF_SIGNATURE_VALIDATION_FAILED",
            )

        expected_previous = int(getattr(input_artifact, "signature_count", 0) or 0)
        total_count = len(signatures)
        new_count = total_count - expected_previous
        latest_signature = signatures[-1]
        latest_status = statuses[-1]
        cert_info = self._certificate_info(getattr(latest_signature, "signer_cert", None))
        previous_ok = all(bool(getattr(status, "bottom_line", False)) for status in statuses[:expected_previous])
        all_ok = all(bool(getattr(status, "bottom_line", False)) for status in statuses)
        trusted = all(bool(getattr(status, "trusted", False)) for status in statuses)
        modification_level = self._status_name(getattr(latest_status, "modification_level", None))
        identity_match = self._identity_matches(identidad, cert_info)
        issuer_allowed = self._issuer_allowed(allowed_issuers, cert_info)
        errors = []
        warnings = []

        if new_count <= 0:
            errors.append("El PDF no agrega una firma nueva.")
        if new_count > 1:
            errors.append("El PDF agrega mas de una firma nueva.")
        if expected_step.orden != total_count:
            errors.append("El numero de firmas no coincide con el orden esperado.")
        if expected_previous and not previous_ok:
            errors.append("Una firma anterior dejo de ser valida.")
        if not all_ok:
            errors.append("Una o mas firmas no superan la validacion criptografica.")
        if not trusted:
            errors.append("La cadena de confianza no llega a un trust root configurado.")
        if not issuer_allowed:
            errors.append("El emisor del certificado no esta permitido por politica.")
        if not identity_match:
            errors.append("La identidad del firmante no coincide con la identidad configurada.")

        revoked = any(bool(getattr(status, "revoked", False)) for status in statuses)
        revocation_mode = self.app.config.get("DOCUMENT_SIGNATURE_REVOCATION_MODE", "soft-fail")
        revocation_checked = revocation_mode not in {"none"}
        if revoked:
            errors.append("El certificado aparece como revocado.")
        elif revocation_mode == "require" and not revocation_checked:
            warnings.append("La revocacion no fue verificada de forma estricta.")

        certificate_valid = self._certificate_valid_at_signing(cert_info)
        if not certificate_valid:
            errors.append("El certificado no estaba vigente al momento de firma evaluado.")

        if new_count <= 0:
            status = "FIRMA_DUPLICADA"
        elif new_count > 1:
            status = "MAS_DE_UNA_FIRMA_NUEVA"
        elif expected_step.orden != total_count:
            status = "ORDEN_INCORRECTO"
        elif expected_previous and not previous_ok:
            status = "FIRMAS_ANTERIORES_INVALIDAS"
        elif not all_ok:
            status = "INVALIDA"
        elif not trusted or not issuer_allowed:
            status = "NO_CONFIABLE"
        elif not identity_match:
            status = "IDENTIDAD_NO_COINCIDE"
        elif revoked:
            status = "CERTIFICADO_REVOCADO"
        elif not certificate_valid:
            status = "CERTIFICADO_NO_VIGENTE"
        elif warnings:
            status = "VALIDA_CON_ADVERTENCIAS"
        else:
            status = "VALIDA"

        return self._result(
            status == "VALIDA",
            status,
            integrity_valid=all_ok,
            trusted=trusted and issuer_allowed,
            identity_match=identity_match,
            certificate_valid_at_signing=certificate_valid,
            revocation_checked=revocation_checked,
            revocation_status="REVOCADO" if revoked else ("VERIFICADA" if revocation_checked else "NO_VERIFICADA"),
            previous_signatures_valid=previous_ok or expected_previous == 0,
            modification_level=modification_level,
            new_signature_count=new_count,
            total_signature_count=total_count,
            warnings=warnings,
            errors=errors,
            error_code=None if status == "VALIDA" else status,
            metadata={
                "signature_statuses": [self._status_name(getattr(status_obj, "summary", None)) for status_obj in statuses],
                "expected_previous_signature_count": expected_previous,
                "step_order": expected_step.orden,
            },
            **cert_info,
        )

    def validate_enrollment_pdf(self, *, signed_pdf_path: Path, identificacion) -> SignatureValidationResult:
        if not self.library_available():
            return self._result(
                False,
                "LIBRERIA_NO_DISPONIBLE",
                errors=["pyHanko o pyhanko-certvalidator no estan disponibles."],
                error_code="PDF_SIGNATURE_LIBRARY_UNAVAILABLE",
            )
        try:
            trust_roots = self._load_trust_roots()
            intermediate_certs = self._load_intermediate_certs()
            allowed_issuers = self._load_allowed_issuers()
        except DocumentSignatureError as exc:
            return self._result(False, "NO_CONFIABLE", errors=[str(exc)], error_code="SIGNATURE_TRUST_STORE_INVALID")

        try:
            from pyhanko.pdf_utils.reader import PdfFileReader
            from pyhanko.sign.validation import validate_pdf_signature
            from pyhanko_certvalidator import ValidationContext
        except Exception as exc:
            return self._result(False, "LIBRERIA_NO_DISPONIBLE", errors=[self._sanitize_error(exc)], error_code="PDF_SIGNATURE_LIBRARY_UNAVAILABLE")

        try:
            with signed_pdf_path.open("rb") as handle:
                reader = PdfFileReader(handle, strict=False)
                signatures = list(getattr(reader, "embedded_signatures", []) or [])
                if not signatures:
                    return self._result(False, "FIRMA_FALTANTE", errors=["El PDF no contiene firmas digitales embebidas."], total_signature_count=0, error_code="PDF_WITHOUT_SIGNATURES")
                statuses = []
                for signature in signatures:
                    vc = ValidationContext(
                        trust_roots=trust_roots,
                        other_certs=intermediate_certs,
                        allow_fetching=False,
                        revocation_mode=self.app.config.get("DOCUMENT_SIGNATURE_REVOCATION_MODE", "soft-fail"),
                    )
                    statuses.append(validate_pdf_signature(signature, signer_validation_context=vc, skip_diff=False))
        except Exception as exc:
            return self._result(False, "PDF_INVALIDO", errors=[self._sanitize_error(exc)], error_code="PDF_SIGNATURE_VALIDATION_FAILED")

        latest_signature = signatures[-1]
        signer_cert = getattr(latest_signature, "signer_cert", None)
        cert_info = self._certificate_info(signer_cert)
        cert_info["certificate_identification"] = self._certificate_extension_value(
            signer_cert,
            FIRMASEGURA_IDENTIFICATION_OID,
        )
        all_ok = all(bool(getattr(status, "bottom_line", False)) for status in statuses)
        trusted = all(bool(getattr(status, "trusted", False)) for status in statuses)
        issuer_allowed = self._issuer_allowed(allowed_issuers, cert_info)
        identity_match = self._identification_matches_cert(identificacion, cert_info)
        certificate_valid = self._certificate_valid_at_signing(cert_info)
        errors = []
        if not all_ok:
            errors.append("Una o mas firmas no superan la validacion criptografica.")
        if not trusted:
            errors.append("La cadena de confianza no llega a un trust root configurado.")
        if not issuer_allowed:
            errors.append("El emisor del certificado no esta permitido por politica.")
        if not identity_match:
            errors.append("La identificacion declarada no coincide con el certificado firmante.")
        if not certificate_valid:
            errors.append("El certificado no estaba vigente al momento de firma evaluado.")

        revoked = any(bool(getattr(status, "revoked", False)) for status in statuses)
        if revoked:
            errors.append("El certificado aparece como revocado.")

        if not all_ok:
            status = "INVALIDA"
        elif not trusted or not issuer_allowed:
            status = "NO_CONFIABLE"
        elif not identity_match:
            status = "IDENTIFICACION_NO_COINCIDE"
        elif revoked:
            status = "CERTIFICADO_REVOCADO"
        elif not certificate_valid:
            status = "CERTIFICADO_NO_VIGENTE"
        else:
            status = "VALIDA"

        return self._result(
            status == "VALIDA",
            status,
            integrity_valid=all_ok,
            trusted=trusted and issuer_allowed,
            identity_match=identity_match,
            certificate_valid_at_signing=certificate_valid,
            revocation_checked=self.app.config.get("DOCUMENT_SIGNATURE_REVOCATION_MODE", "soft-fail") not in {"none"},
            revocation_status="REVOCADO" if revoked else "VERIFICADA",
            previous_signatures_valid=True,
            total_signature_count=len(signatures),
            new_signature_count=len(signatures),
            errors=errors,
            error_code=None if status == "VALIDA" else status,
            metadata={"verification_type": "cryptographic_signed_pdf"},
            **cert_info,
        )

    def _load_trust_roots(self):
        from pyhanko.keys import load_cert_from_pemder

        try:
            from app.services.document_signature_dev_service import dev_signature_mode_enabled, DocumentSignatureDevCertificateService

            if dev_signature_mode_enabled(self.app):
                ca_path = DocumentSignatureDevCertificateService(self.app).ca_cert_path
                if not ca_path.exists():
                    raise DocumentSignatureError("La CA de desarrollo no existe; ejecuta firmas-dev inicializar.")
                return [load_cert_from_pemder(str(ca_path))]
        except DocumentSignatureError:
            raise

        paths = self._collect_paths(self.app.config.get("DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH") or self.app.config.get("DOCUMENT_SIGNATURE_TRUST_ROOTS_DIR"))
        if not paths:
            raise DocumentSignatureError("DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH es obligatorio en modo strict.")
        certs = []
        for path in paths:
            try:
                certs.append(load_cert_from_pemder(str(path)))
            except Exception as exc:
                raise DocumentSignatureError(f"Trust root invalida: {path.name}") from exc
        return certs

    def _load_intermediate_certs(self):
        from pyhanko.keys import load_cert_from_pemder

        configured = self.app.config.get("DOCUMENT_SIGNATURE_INTERMEDIATES_PATH")
        if not configured:
            return []
        certs = []
        for path in self._collect_paths(configured):
            try:
                certs.append(load_cert_from_pemder(str(path)))
            except Exception as exc:
                raise DocumentSignatureError(f"Certificado intermedio invalido: {path.name}") from exc
        return certs

    def _load_allowed_issuers(self):
        from pyhanko.keys import load_cert_from_pemder

        try:
            from app.services.document_signature_dev_service import dev_signature_mode_enabled, DocumentSignatureDevCertificateService

            if dev_signature_mode_enabled(self.app):
                ca_path = DocumentSignatureDevCertificateService(self.app).ca_cert_path
                if not ca_path.exists():
                    raise DocumentSignatureError("La CA de desarrollo no existe; ejecuta firmas-dev inicializar.")
                cert = load_cert_from_pemder(str(ca_path))
                return [_normalize_identity_value(cert.subject.human_friendly)]
        except DocumentSignatureError:
            raise

        configured = self.app.config.get("DOCUMENT_SIGNATURE_ALLOWED_ISSUERS_PATH")
        if not configured:
            return []
        issuers = []
        for path in self._collect_paths(configured):
            try:
                cert = load_cert_from_pemder(str(path))
                issuers.append(_normalize_identity_value(cert.subject.human_friendly))
            except Exception as exc:
                raise DocumentSignatureError(f"Emisor permitido invalido: {path.name}") from exc
        return issuers

    def _collect_paths(self, configured):
        configured = str(configured or "").strip()
        if not configured:
            return []
        root = Path(configured).expanduser()
        if not root.exists():
            raise DocumentSignatureError(f"La ruta de confianza no existe: {root}")
        if root.is_file():
            return [root]
        if not root.is_dir():
            raise DocumentSignatureError(f"La ruta de confianza no es archivo ni directorio: {root}")
        allowed = {".pem", ".cer", ".crt", ".der"}
        return sorted(path for path in root.iterdir() if path.is_file() and path.suffix.lower() in allowed)

    def _certificate_info(self, cert):
        if cert is None:
            return {}
        subject = cert.subject.human_friendly
        issuer = cert.issuer.human_friendly
        native_subject = cert.subject.native or {}
        email = native_subject.get("email_address")
        common_name = native_subject.get("common_name")
        return {
            "signer_identifier": subject,
            "certificate_fingerprint_sha256": hashlib.sha256(cert.dump()).hexdigest(),
            "certificate_serial": str(cert.serial_number),
            "certificate_subject": subject,
            "certificate_issuer": issuer,
            "certificate_common_name": common_name,
            "certificate_email": email,
            "certificate_valid_from": cert["tbs_certificate"]["validity"]["not_before"].native,
            "certificate_valid_to": cert["tbs_certificate"]["validity"]["not_after"].native,
            "signing_time": None,
        }

    def _identity_matches(self, identidad, cert_info):
        if not identidad:
            return False
        metadata = identidad.metadata_json or {}
        expected_fp = _normalized_sha256(identidad.certificado_fingerprint_sha256 or metadata.get("certificate_fingerprint_sha256"))
        if expected_fp:
            return expected_fp == cert_info.get("certificate_fingerprint_sha256")
        expected_id = _normalize_identity_value(identidad.identificacion)
        cert_subject = _normalize_identity_value(cert_info.get("certificate_subject"))
        if expected_id and expected_id in cert_subject:
            return True
        expected_serial = _normalize_identity_value(metadata.get("certificate_serial"))
        expected_issuer = _normalize_identity_value(metadata.get("certificate_issuer") or identidad.emisor_certificado)
        if expected_serial and expected_issuer:
            if expected_serial == _normalize_identity_value(cert_info.get("certificate_serial")) and expected_issuer == _normalize_identity_value(cert_info.get("certificate_issuer")):
                return True
        expected_email = _normalize_identity_value(metadata.get("certificate_email"))
        if expected_email and expected_email == _normalize_identity_value(cert_info.get("certificate_email")):
            return True
        expected_subject = _normalize_identity_value(metadata.get("certificate_subject"))
        return bool(expected_subject and expected_subject == cert_subject)

    def _certificate_extension_value(self, cert, oid):
        if cert is None:
            return None
        try:
            extensions = cert["tbs_certificate"]["extensions"]
            for extension in extensions:
                extension_oid = getattr(extension["extn_id"], "dotted", None)
                if extension_oid != oid:
                    continue
                value = extension["extn_value"].parsed.native
                if value is None:
                    return None
                return str(value).strip()
        except Exception:
            return None
        return None

    def _identification_matches_cert(self, identificacion, cert_info):
        expected_id = _normalize_identity_value(identificacion)
        if not expected_id:
            return False

        certified_id = _normalize_identity_value(
            cert_info.get("certificate_identification")
        )
        if certified_id:
            return expected_id == certified_id

        candidates = (
            cert_info.get("certificate_subject"),
            cert_info.get("certificate_common_name"),
            cert_info.get("certificate_email"),
            cert_info.get("signer_identifier"),
        )
        return any(
            expected_id in _normalize_identity_value(candidate)
            for candidate in candidates
        )

    def _issuer_allowed(self, allowed_issuers, cert_info):
        if not allowed_issuers:
            return True
        return _normalize_identity_value(cert_info.get("certificate_issuer")) in allowed_issuers

    def _certificate_valid_at_signing(self, cert_info):
        valid_from = cert_info.get("certificate_valid_from")
        valid_to = cert_info.get("certificate_valid_to")
        signing_time = cert_info.get("signing_time") or _now()
        if valid_from and valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if valid_to and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        return bool(valid_from and valid_to and valid_from <= signing_time <= valid_to)

    def _status_name(self, value):
        return getattr(value, "name", str(value or "UNKNOWN"))

    def _sanitize_error(self, exc):
        return str(exc).replace(os.getcwd(), "<workspace>")[:500]

    def _result(self, is_valid, status, **kwargs):
        errors = kwargs.pop("errors", [])
        warnings = kwargs.pop("warnings", [])
        details = "; ".join([*errors, *warnings]) or status
        metadata = kwargs.pop("metadata", {}) or {}
        return SignatureValidationResult(
            is_valid=is_valid,
            status=status,
            sanitized_details=details[:1000],
            warnings=warnings,
            errors=errors,
            metadata=metadata,
            **kwargs,
        )


class ExternalControlledSignatureProvider:
    """Proveedor externo controlado: el usuario firma fuera y LabZenISO solo valida el PDF recibido."""

    provider_name = FIRMA_PROVEEDOR_EXTERNO_CONTROLADO

    def __init__(self, app=None):
        self.app = app or current_app
        self.validator = PyHankoPdfSignatureValidator(self.app)

    def validate_signed_pdf(self, *, signed_pdf_path: Path, input_artifact, paso, identidad) -> SignatureValidationResult:
        mode = (self.app.config.get("DOCUMENT_SIGNATURE_VALIDATION_MODE") or "strict").strip().lower()
        basic = DocumentPdfService().validate_pdf_file(signed_pdf_path, allow_signature_forms=True)
        metadata = {
            "pdf_sha256": basic.sha256,
            "pdf_size": basic.size,
            "page_count": basic.page_count,
            "validation_mode": mode,
        }
        if mode == "testing":
            marker = self.app.config.get("DOCUMENT_SIGNATURE_TESTING_ACCEPT_MARKER")
            if marker and marker.encode("utf-8") not in signed_pdf_path.read_bytes():
                return SignatureValidationResult(
                    is_valid=False,
                    status="INVALIDA",
                    total_signature_count=0,
                    sanitized_details="El PDF de prueba no contiene el marcador de firma controlada.",
                    metadata=metadata,
                    error_code="TEST_SIGNATURE_MARKER_MISSING",
                )
            return SignatureValidationResult(
                is_valid=True,
                status="VALIDA",
                integrity_valid=True,
                trusted=True,
                identity_match=True,
                certificate_valid_at_signing=True,
                previous_signatures_valid=True,
                new_signature_count=1,
                total_signature_count=max(1, int(getattr(input_artifact, "signature_count", 0) or 0) + 1),
                sanitized_details="Validacion de prueba aceptada por configuracion controlada.",
                metadata={**metadata, "testing_provider": True},
            )
        result = self.validator.validate_pdf(
            signed_pdf_path=signed_pdf_path,
            input_artifact=input_artifact,
            expected_step=paso,
            identidad=identidad,
        )
        return SignatureValidationResult(
            **{
                **result.__dict__,
                "metadata": {**metadata, **(result.metadata or {})},
            }
        )


class DocumentSignatureService:
    def __init__(self, provider=None, app=None):
        self.app = app or current_app
        self.provider = provider or ExternalControlledSignatureProvider(self.app)
        self.pdf_service = DocumentPdfService()

    def signatures_enabled(self):
        return bool(self.app.config.get("DOCUMENT_SIGNATURES_ENABLED"))

    def latest_process_for_version(self, version_doc):
        return (
            DocumentoFirmaProceso.query
            .filter_by(empresa_id=version_doc.empresa_id, documento_version_id=version_doc.id)
            .order_by(DocumentoFirmaProceso.solicitado_en.desc(), DocumentoFirmaProceso.id.desc())
            .first()
        )

    def required_identity_statuses(self, version_doc):
        assignments = [
            (1, FIRMA_ROL_ELABORADOR, version_doc.elaborado_por),
            (2, FIRMA_ROL_REVISOR, version_doc.revisado_por),
            (3, FIRMA_ROL_APROBADOR, version_doc.aprobado_por),
        ]
        statuses = []
        for order, role, user in assignments:
            identity = self._verified_identity_for_user(user) if user else None
            statuses.append({
                "order": order,
                "role": role,
                "user": user,
                "identity": identity,
                "verified": bool(identity),
            })
        return statuses

    def _principal_docx_profile(self, version_doc):
        profile = get_onlyoffice_document_profile(version_doc)
        if profile:
            return profile if profile.extension == "docx" else None
        snapshot = (
            DocumentoSnapshot.query
            .filter_by(
                empresa_id=version_doc.empresa_id,
                documento_version_id=version_doc.id,
                tipo=SNAPSHOT_APROBADO,
                estado=SNAPSHOT_DISPONIBLE,
            )
            .order_by(DocumentoSnapshot.ciclo_revision.desc(), DocumentoSnapshot.id.desc())
            .first()
        )
        snapshot_profile = get_onlyoffice_document_profile(snapshot)
        return snapshot_profile if snapshot_profile and snapshot_profile.extension == "docx" else None

    def start_process(self, *, documento, version_doc, usuario, ip=None, user_agent=None):
        if not self.signatures_enabled():
            raise DocumentSignatureError("Las firmas digitales no estan habilitadas.")
        if not user_has_permission(usuario, START_SIGNATURE_PERMISSION):
            raise DocumentSignatureError("No tienes permiso para iniciar firmas digitales externas.")
        if documento.empresa_id != usuario.empresa_id or version_doc.empresa_id != usuario.empresa_id:
            raise DocumentSignatureError("No puedes iniciar firmas para documentos de otra empresa.")
        if version_doc.documento_id != documento.id:
            raise DocumentSignatureError("La version no corresponde al documento indicado.")
        if version_doc.estado != ESTADO_APROBADO or documento.estado != ESTADO_APROBADO:
            raise DocumentSignatureError("Solo se puede iniciar firma sobre documentos APROBADOS.")
        if not self._principal_docx_profile(version_doc):
            raise DocumentSignatureError("La firma corresponde solo al documento principal DOCX aprobado.")
        existing = (
            DocumentoFirmaProceso.query
            .filter(
                DocumentoFirmaProceso.empresa_id == documento.empresa_id,
                DocumentoFirmaProceso.documento_version_id == version_doc.id,
                DocumentoFirmaProceso.estado.in_((FIRMA_PROCESO_PENDIENTE, FIRMA_PROCESO_EN_FIRMA, FIRMA_PROCESO_COMPLETADO)),
            )
            .order_by(DocumentoFirmaProceso.solicitado_en.desc(), DocumentoFirmaProceso.id.desc())
            .first()
        )
        if existing:
            return existing
        try:
            prepared_publication = DocumentPublicationService(app=self.app).prepare_publication_for_signature(
                documento=documento,
                version_doc=version_doc,
                usuario=usuario,
            )
            pdf_origen = prepared_publication.artifact
        except DocumentPublicationError as exc:
            raise DocumentSignatureError(str(exc)) from exc
        if not pdf_origen:
            raise DocumentSignatureError("No existe PDF aprobado disponible para iniciar la firma.")
        self._validate_available_pdf_artifact(pdf_origen)
        if pdf_origen.tipo != ARTEFACTO_PDF_APROBADO_CON_QR:
            raise DocumentSignatureError("La firma debe iniciar desde PDF_APROBADO_CON_QR.")

        assignments = self._required_assignments(version_doc)
        proceso = DocumentoFirmaProceso(
            empresa_id=documento.empresa_id,
            public_id=uuid4().hex,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            pdf_origen_id=pdf_origen.id,
            provider=self.provider.provider_name,
            estado=FIRMA_PROCESO_EN_FIRMA,
            solicitado_por_id=usuario.id,
            solicitado_en=_now(),
            iniciado_en=_now(),
            vence_en=_now() + timedelta(days=int(self.app.config.get("DOCUMENT_SIGNATURE_PROCESS_TTL_DAYS", 15))),
            metadata_json={
                "document_state_preserved": ESTADO_APROBADO,
                "publication_id": prepared_publication.publicacion.id,
                "publication_public_id": prepared_publication.publicacion.public_id,
                "qr_sha256": prepared_publication.qr_sha256,
                "pdf_origen_tipo": pdf_origen.tipo,
            },
        )
        db.session.add(proceso)
        db.session.flush()

        previous_input = pdf_origen
        for order, role, signer in assignments:
            identity = self._verified_identity_for_user(signer)
            step = DocumentoFirmaPaso(
                empresa_id=documento.empresa_id,
                public_id=uuid4().hex,
                proceso_id=proceso.id,
                documento_id=documento.id,
                documento_version_id=version_doc.id,
                orden=order,
                rol_firmante=role,
                usuario_id=signer.id,
                identidad_firma_id=identity.id if identity else None,
                estado=FIRMA_PASO_HABILITADO if order == 1 else FIRMA_PASO_PENDIENTE,
                artifact_entrada_id=previous_input.id if order == 1 else None,
                habilitado_en=_now() if order == 1 else None,
                vence_en=proceso.vence_en,
                metadata_json={},
            )
            db.session.add(step)
        db.session.flush()
        self._record_event(proceso, None, usuario, FIRMA_EVENTO_PROCESO_CREADO, "Proceso de firma externa iniciado.", ip, user_agent)
        first_step = self._current_enabled_step(proceso)
        if first_step:
            self._record_event(proceso, first_step, usuario, FIRMA_EVENTO_PASO_HABILITADO, "Primer firmante habilitado.", ip, user_agent)
        db.session.commit()
        return proceso

    def downloadable_artifact_for_step(self, *, paso, usuario, ip=None, user_agent=None):
        self._assert_step_owner_enabled(paso, usuario)
        artifact = paso.artifact_entrada or self._input_artifact_for_step(paso)
        if artifact.tipo not in (ARTEFACTO_PDF_APROBADO, ARTEFACTO_PDF_APROBADO_CON_QR, ARTEFACTO_PDF_FIRMADO_PARCIAL):
            raise DocumentSignatureError("El artefacto de entrada no es valido para firma.")
        self._validate_available_pdf_artifact(artifact)
        if paso.artifact_entrada_id != artifact.id:
            paso.artifact_entrada_id = artifact.id
            db.session.flush()
        self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_PDF_DESCARGADO, "PDF entregado al firmante externo.", ip, user_agent)
        db.session.commit()
        return artifact, resolve_document_path(artifact.storage_path)

    def upload_signed_pdf(self, *, paso, usuario, file_storage, ip=None, user_agent=None):
        self._assert_step_owner_enabled(paso, usuario)
        if not file_storage or not file_storage.filename:
            raise DocumentSignatureError("Debes cargar un PDF firmado.")
        if not file_storage.filename.lower().endswith(".pdf"):
            raise DocumentSignatureError("Solo se admite PDF firmado.")

        input_artifact = paso.artifact_entrada or self._input_artifact_for_step(paso)
        self._validate_available_pdf_artifact(input_artifact)
        temp_path = self._save_upload_temporarily(file_storage)
        stored = None
        try:
            validation = self.provider.validate_signed_pdf(
                signed_pdf_path=temp_path,
                input_artifact=input_artifact,
                paso=paso,
                identidad=paso.identidad_firma,
            )
            self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_PDF_SUBIDO, "PDF firmado recibido para validacion.", ip, user_agent)
            if not validation.valid:
                paso.error_codigo = (validation.error_code or "SIGNATURE_VALIDATION_FAILED")[:80]
                paso.error_mensaje = validation.summary[:1000]
                paso.validation_state = validation.state
                paso.validation_summary = validation.summary[:1000]
                self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_VALIDACION_ERROR, validation.summary, ip, user_agent, validation.metadata)
                db.session.commit()
                raise DocumentSignatureError(
                    "El PDF firmado no supero la validacion controlada: "
                    f"{validation.state}."
                )

            pdf_basic = self.pdf_service.validate_pdf_file(temp_path, allow_signature_forms=True)
            expected_input_count = int(input_artifact.signature_count or 0)
            if int(validation.signature_count or 0) <= expected_input_count:
                paso.estado = FIRMA_PASO_ERROR
                paso.error_codigo = "SIGNATURE_COUNT_NOT_INCREMENTED"
                paso.error_mensaje = "El PDF no contiene una nueva firma respecto al artefacto anterior."
                self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_VALIDACION_ERROR, paso.error_mensaje, ip, user_agent, validation.metadata)
                db.session.commit()
                raise DocumentSignatureError("El PDF firmado no agrega una firma nueva.")

            is_final = self._is_last_step(paso)
            stored = store_signed_pdf_artifact_copy(
                source_path=temp_path,
                documento=paso.documento,
                version_doc=paso.documento_version,
                source_artifact=input_artifact,
                signed_revision=paso.orden,
                final=is_final,
                expected_sha256=pdf_basic.sha256,
            )
            artifact = DocumentoArtefacto(
                empresa_id=paso.empresa_id,
                public_id=uuid4().hex,
                documento_id=paso.documento_id,
                documento_version_id=paso.documento_version_id,
                source_snapshot_id=input_artifact.source_snapshot_id,
                source_artifact_id=input_artifact.id,
                firma_proceso_id=paso.proceso_id,
                firma_paso_id=paso.id,
                tipo=ARTEFACTO_PDF_FIRMADO_FINAL if is_final else ARTEFACTO_PDF_FIRMADO_PARCIAL,
                estado=ARTEFACTO_DISPONIBLE,
                storage_path=stored.storage_path,
                archivo_nombre_interno=stored.stored_name,
                archivo_nombre_visible=f"{paso.documento.codigo}_v{paso.documento_version.version}_{'firmado_final' if is_final else 'firmado_parcial_' + str(paso.orden)}.pdf",
                archivo_mime=PDF_MIME,
                archivo_size=stored.size,
                archivo_sha256=stored.sha256,
                source_snapshot_sha256=input_artifact.source_snapshot_sha256,
                source_artifact_sha256=input_artifact.archivo_sha256,
                page_count=pdf_basic.page_count,
                signature_count=validation.signature_count,
                validation_state=validation.state,
                signed_revision=paso.orden,
                signed_by_user_id=usuario.id,
                signed_at=_now(),
                provider=self.provider.provider_name,
                provider_version="external-controlled-v1",
                creado_por_id=usuario.id,
                creado_en=_now(),
                disponible_en=_now(),
                inmutable=True,
                metadata_json=validation.metadata or {},
            )
            db.session.add(artifact)
            db.session.flush()
            paso.estado = FIRMA_PASO_FIRMADO
            paso.artifact_entrada_id = input_artifact.id
            paso.artifact_salida_id = artifact.id
            paso.firmado_en = _now()
            paso.signature_count_after = validation.signature_count
            paso.validation_state = validation.state
            paso.validation_summary = validation.summary[:1000]
            paso.error_codigo = None
            paso.error_mensaje = None
            self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_VALIDACION_OK, validation.summary, ip, user_agent, validation.metadata)
            self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_PASO_FIRMADO, "Paso firmado correctamente.", ip, user_agent)

            if is_final:
                paso.proceso.estado = FIRMA_PROCESO_COMPLETADO
                paso.proceso.pdf_final_id = artifact.id
                paso.proceso.completado_en = _now()
                self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_PROCESO_COMPLETADO, "Proceso de firma completado. El documento permanece APROBADO.", ip, user_agent)
            else:
                next_step = self._next_step(paso)
                next_step.estado = FIRMA_PASO_HABILITADO
                next_step.artifact_entrada_id = artifact.id
                next_step.habilitado_en = _now()
                self._record_event(paso.proceso, next_step, usuario, FIRMA_EVENTO_PASO_HABILITADO, "Siguiente firmante habilitado.", ip, user_agent)
            db.session.commit()
            return artifact
        except Exception:
            db.session.rollback()
            if stored:
                delete_pdf_artifact_file(stored.storage_path)
            raise
        finally:
            temp_path.unlink(missing_ok=True)

    def sign_step_with_dev_certificate(self, *, paso, usuario, ip=None, user_agent=None):
        from werkzeug.datastructures import FileStorage

        from app.services.document_signature_dev_service import (
            DEV_TEST_SIGNATURE_REJECTED,
            DEV_TEST_SIGNATURE_REQUESTED,
            DEV_TEST_SIGNATURE_VALIDATED,
            DocumentSignatureDevCertificateService,
            DocumentSignatureDevError,
        )

        self._assert_step_owner_enabled(paso, usuario)
        input_artifact = paso.artifact_entrada or self._input_artifact_for_step(paso)
        before_count = int(input_artifact.signature_count or 0)
        metadata_base = {
            "dev_test_signature": True,
            "firma_paso_id": paso.id,
            "rol": paso.rol_firmante,
            "fingerprint": (paso.identidad_firma.certificado_fingerprint_sha256 if paso.identidad_firma else None),
            "signature_count_before": before_count,
        }
        self._record_event(
            paso.proceso,
            paso,
            usuario,
            DEV_TEST_SIGNATURE_REQUESTED,
            "Solicitud de firma PAdES con certificado local de desarrollo.",
            ip,
            user_agent,
            metadata_base,
        )
        db.session.commit()

        dev_service = DocumentSignatureDevCertificateService(self.app)
        signed_path = None
        try:
            signed_path = dev_service.sign_step_pdf(paso)
            with signed_path.open("rb") as stream:
                artifact = self.upload_signed_pdf(
                    paso=paso,
                    usuario=usuario,
                    file_storage=FileStorage(
                        stream=stream,
                        filename=f"{paso.documento.codigo}_dev_signed_{paso.orden}.pdf",
                        content_type=PDF_MIME,
                    ),
                    ip=ip,
                    user_agent=user_agent,
                )
            self._record_event(
                paso.proceso,
                paso,
                usuario,
                DEV_TEST_SIGNATURE_VALIDATED,
                "Firma PAdES de desarrollo validada por pyHanko.",
                ip,
                user_agent,
                {
                    **metadata_base,
                    "signature_count_after": int(artifact.signature_count or 0),
                    "artifact_id": artifact.id,
                    "result": "VALIDA",
                },
            )
            db.session.commit()
            return artifact
        except (DocumentSignatureError, DocumentSignatureDevError) as exc:
            db.session.rollback()
            self._record_event(
                paso.proceso,
                paso,
                usuario,
                DEV_TEST_SIGNATURE_REJECTED,
                str(exc),
                ip,
                user_agent,
                {**metadata_base, "result": "RECHAZADA", "error": str(exc)[:300]},
            )
            db.session.commit()
            raise DocumentSignatureError(str(exc)) from exc
        finally:
            if signed_path:
                signed_path.unlink(missing_ok=True)

    def reject_step(self, *, paso, usuario, comentario="", ip=None, user_agent=None):
        self._assert_step_owner_enabled(paso, usuario)
        paso.estado = FIRMA_PASO_RECHAZADO
        paso.proceso.estado = FIRMA_PROCESO_RECHAZADO
        self._record_event(paso.proceso, paso, usuario, FIRMA_EVENTO_RECHAZADO, comentario or "Firma rechazada por el firmante.", ip, user_agent)
        db.session.commit()
        return paso.proceso

    def cancel_process(self, *, proceso, usuario, comentario="", ip=None, user_agent=None):
        if proceso.estado not in (FIRMA_PROCESO_EN_FIRMA,):
            raise DocumentSignatureError("Solo se pueden cancelar procesos activos.")
        proceso.estado = FIRMA_PROCESO_CANCELADO
        for paso in proceso.pasos:
            if paso.estado in (FIRMA_PASO_PENDIENTE, FIRMA_PASO_HABILITADO):
                paso.estado = FIRMA_PASO_CANCELADO
        self._record_event(proceso, None, usuario, FIRMA_EVENTO_CANCELADO, comentario or "Proceso de firma cancelado.", ip, user_agent)
        db.session.commit()
        return proceso

    def expire_due_processes(self, *, now=None, reporter=None):
        now = now or _now()
        expired = (
            DocumentoFirmaProceso.query
            .filter(
                DocumentoFirmaProceso.estado == FIRMA_PROCESO_EN_FIRMA,
                DocumentoFirmaProceso.vence_en.isnot(None),
                DocumentoFirmaProceso.vence_en < now,
            )
            .all()
        )
        for proceso in expired:
            proceso.estado = "VENCIDO"
            for paso in proceso.pasos:
                if paso.estado in (FIRMA_PASO_PENDIENTE, FIRMA_PASO_HABILITADO):
                    paso.estado = "VENCIDO"
            self._record_event(proceso, None, None, "VENCIDO", "Proceso de firma vencido por TTL.", None, None)
            if reporter:
                reporter(f"{proceso.public_id} vencido")
        db.session.commit()
        return len(expired)

    def _required_assignments(self, version_doc):
        assignments = [
            (1, FIRMA_ROL_ELABORADOR, version_doc.elaborado_por),
            (2, FIRMA_ROL_REVISOR, version_doc.revisado_por),
            (3, FIRMA_ROL_APROBADOR, version_doc.aprobado_por),
        ]
        missing = [role for _order, role, user in assignments if user is None]
        if missing:
            raise DocumentSignatureError("Faltan responsables para firma: " + ", ".join(missing))
        missing_identity = [f"{role}: {user.nombre} {user.apellido}" for _order, role, user in assignments if not self._verified_identity_for_user(user)]
        if missing_identity:
            raise DocumentSignatureError("Faltan identidades de firma verificadas: " + "; ".join(missing_identity))
        return assignments

    def _verified_identity_for_user(self, user):
        return (
            UsuarioIdentidadFirma.query
            .filter_by(empresa_id=user.empresa_id, usuario_id=user.id, estado=FIRMA_IDENTIDAD_VERIFICADA)
            .order_by(UsuarioIdentidadFirma.verificado_en.desc().nullslast(), UsuarioIdentidadFirma.id.desc())
            .first()
        )

    def _current_enabled_step(self, proceso):
        return (
            DocumentoFirmaPaso.query
            .filter_by(empresa_id=proceso.empresa_id, proceso_id=proceso.id, estado=FIRMA_PASO_HABILITADO)
            .order_by(DocumentoFirmaPaso.orden.asc())
            .first()
        )

    def _assert_step_owner_enabled(self, paso, usuario):
        if not self.signatures_enabled():
            raise DocumentSignatureError("Las firmas digitales no estan habilitadas.")
        if paso.estado != FIRMA_PASO_HABILITADO or paso.usuario_id != usuario.id:
            raise DocumentSignatureError("No puedes operar este paso de firma.")
        if paso.proceso.estado != FIRMA_PROCESO_EN_FIRMA:
            raise DocumentSignatureError("El proceso de firma no esta activo.")

    def _input_artifact_for_step(self, paso):
        if paso.orden == 1:
            return paso.proceso.pdf_origen
        previous = (
            DocumentoFirmaPaso.query
            .filter_by(proceso_id=paso.proceso_id, orden=paso.orden - 1)
            .first()
        )
        if not previous or not previous.artifact_salida:
            raise DocumentSignatureError("No existe artefacto firmado previo para este paso.")
        return previous.artifact_salida

    def _validate_available_pdf_artifact(self, artifact):
        if artifact.estado != ARTEFACTO_DISPONIBLE or not artifact.inmutable:
            raise DocumentSignatureError("El PDF de entrada no esta disponible.")
        if artifact.tipo in (ARTEFACTO_PDF_APROBADO, ARTEFACTO_PDF_APROBADO_CON_QR):
            return self.pdf_service.validate_artifact_file(artifact)
        if artifact.tipo != ARTEFACTO_PDF_FIRMADO_PARCIAL:
            raise DocumentSignatureError("Tipo de artefacto de entrada no valido.")
        path = resolve_document_path(artifact.storage_path)
        result = self.pdf_service.validate_pdf_file(path, allow_signature_forms=True)
        if result.sha256 != artifact.archivo_sha256 or int(result.size) != int(artifact.archivo_size or 0):
            raise DocumentSignatureError("El PDF firmado de entrada no coincide con su registro.")
        return path

    def _is_last_step(self, paso):
        return not self._next_step(paso)

    def _next_step(self, paso):
        return (
            DocumentoFirmaPaso.query
            .filter_by(proceso_id=paso.proceso_id, orden=paso.orden + 1)
            .first()
        )

    def _save_upload_temporarily(self, file_storage):
        suffix = ".pdf"
        handle = tempfile.NamedTemporaryFile(prefix="labzeniso-firma-", suffix=suffix, delete=False)
        temp_path = Path(handle.name)
        try:
            with handle:
                file_storage.save(handle)
            size = temp_path.stat().st_size
            max_size = int(self.app.config.get("DOCUMENT_SIGNATURE_MAX_PDF_BYTES", self.app.config.get("ONLYOFFICE_PDF_MAX_BYTES", 50 * 1024 * 1024)))
            if size <= 0 or size > max_size:
                raise DocumentSignatureError("El PDF firmado supera el limite permitido o esta vacio.")
            file_digest_and_size(temp_path)
            return temp_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _record_event(self, proceso, paso, usuario, tipo, detalle="", ip=None, user_agent=None, metadata=None):
        db.session.add(DocumentoFirmaEvento(
            empresa_id=proceso.empresa_id,
            proceso_id=proceso.id,
            paso_id=paso.id if paso else None,
            documento_id=proceso.documento_id,
            documento_version_id=proceso.documento_version_id,
            usuario_id=usuario.id if usuario else None,
            tipo_evento=tipo,
            creado_en=_now(),
            ip=ip,
            user_agent=user_agent,
            detalle=detalle,
            metadata_json=metadata or {},
        ))
