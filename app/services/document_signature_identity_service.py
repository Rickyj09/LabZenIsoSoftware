import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.extensions import db
from app.models.auditoria import AuditoriaLog
from app.models.documentos import (
    FIRMA_IDENTIDAD_PENDIENTE,
    FIRMA_IDENTIDAD_REVOCADA,
    FIRMA_IDENTIDAD_VERIFICADA,
    UsuarioIdentidadFirma,
)
from app.models.seguridad import Usuario
from app.security.permissions import user_has_permission
from app.services.document_pdf_service import DocumentPdfService
from app.services.document_signature_service import PyHankoPdfSignatureValidator


SIGNATURE_IDENTITY_PERMISSION = "documentos.firmas.identidades.gestionar"


class DocumentSignatureIdentityError(ValueError):
    pass


def can_manage_signature_identities(user):
    return user_has_permission(user, SIGNATURE_IDENTITY_PERMISSION)


class DocumentSignatureIdentityService:
    def _now(self):
        return datetime.now(timezone.utc)

    def _snapshot(self, identity):
        if not identity:
            return None
        return {
            "id": identity.id,
            "usuario_id": identity.usuario_id,
            "identificacion": identity.identificacion,
            "nombre_certificado": identity.nombre_certificado,
            "emisor_certificado": identity.emisor_certificado,
            "certificado_fingerprint_sha256": identity.certificado_fingerprint_sha256,
            "estado": identity.estado,
            "verificado_por_id": identity.verificado_por_id,
            "verificado_en": identity.verificado_en.isoformat() if identity.verificado_en else None,
            "metadata_json": identity.metadata_json or {},
        }

    def _audit(self, *, actor, accion, identity, antes=None, despues=None, ip=None, user_agent=None):
        db.session.add(AuditoriaLog(
            empresa_id=actor.empresa_id,
            usuario_id=actor.id,
            tabla="usuario_identidades_firma",
            registro_id=identity.id,
            accion=accion,
            datos_antes=antes,
            datos_despues=despues,
            ip=ip,
            user_agent=user_agent,
        ))

    def _assert_permission(self, actor):
        if not can_manage_signature_identities(actor):
            raise DocumentSignatureIdentityError("No tienes permiso para gestionar identidades de firma.")

    def _user_for_actor(self, *, actor, user_id):
        user = Usuario.query.filter_by(id=user_id).first()
        if not user:
            raise DocumentSignatureIdentityError("El usuario no existe.")
        if user.empresa_id != actor.empresa_id:
            raise DocumentSignatureIdentityError("El usuario pertenece a otra empresa.")
        if not user.activo:
            raise DocumentSignatureIdentityError("El usuario esta inactivo.")
        return user

    def _identity_for_actor(self, *, actor, identity_id):
        identity = UsuarioIdentidadFirma.query.filter_by(id=identity_id, empresa_id=actor.empresa_id).first()
        if not identity:
            raise DocumentSignatureIdentityError("La identidad no existe o pertenece a otra empresa.")
        return identity

    def _normalize_identification(self, value):
        normalized = (value or "").strip()
        if not normalized:
            raise DocumentSignatureIdentityError("La identificacion es obligatoria.")
        if len(normalized) > 50:
            raise DocumentSignatureIdentityError("La identificacion no puede superar 50 caracteres.")
        return normalized

    def _normalize_text(self, value, max_length):
        normalized = (value or "").strip()
        if len(normalized) > max_length:
            raise DocumentSignatureIdentityError("Uno de los campos supera la longitud permitida.")
        return normalized or None

    def _normalize_fingerprint(self, value):
        normalized = (value or "").strip().lower()
        if not normalized:
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise DocumentSignatureIdentityError("El fingerprint SHA-256 debe tener exactamente 64 caracteres hexadecimales.")
        return normalized

    def list_company_users_with_identities(self, *, actor):
        self._assert_permission(actor)
        users = (
            Usuario.query
            .filter_by(empresa_id=actor.empresa_id, activo=True)
            .order_by(Usuario.nombre.asc(), Usuario.apellido.asc(), Usuario.username.asc(), Usuario.id.asc())
            .all()
        )
        identities = (
            UsuarioIdentidadFirma.query
            .filter_by(empresa_id=actor.empresa_id)
            .order_by(UsuarioIdentidadFirma.id.desc())
            .all()
        )
        identity_by_user = {}
        for identity in identities:
            identity_by_user.setdefault(identity.usuario_id, identity)
        return [(user, identity_by_user.get(user.id)) for user in users]

    def create_identity(self, *, actor, user_id, identificacion, nombre_certificado=None, emisor_certificado=None, certificado_fingerprint_sha256=None, ip=None, user_agent=None):
        self._assert_permission(actor)
        user = self._user_for_actor(actor=actor, user_id=user_id)
        active_identity = (
            UsuarioIdentidadFirma.query
            .filter(
                UsuarioIdentidadFirma.empresa_id == actor.empresa_id,
                UsuarioIdentidadFirma.usuario_id == user.id,
                UsuarioIdentidadFirma.estado != FIRMA_IDENTIDAD_REVOCADA,
            )
            .first()
        )
        if active_identity:
            raise DocumentSignatureIdentityError("Ya existe una identidad no revocada para este usuario.")
        identity = UsuarioIdentidadFirma(
            empresa_id=actor.empresa_id,
            usuario_id=user.id,
            identificacion=self._normalize_identification(identificacion),
            nombre_certificado=self._normalize_text(nombre_certificado, 255),
            emisor_certificado=self._normalize_text(emisor_certificado, 255),
            certificado_fingerprint_sha256=self._normalize_fingerprint(certificado_fingerprint_sha256),
            estado=FIRMA_IDENTIDAD_PENDIENTE,
            metadata_json={},
        )
        db.session.add(identity)
        db.session.flush()
        self._audit(actor=actor, accion="CREAR", identity=identity, despues=self._snapshot(identity), ip=ip, user_agent=user_agent)
        db.session.commit()
        return identity

    def verify_identity_cryptographic_pdf(self, *, actor, identity_id, file_storage, ip=None, user_agent=None):
        self._assert_permission(actor)
        identity = self._identity_for_actor(actor=actor, identity_id=identity_id)
        self._user_for_actor(actor=actor, user_id=identity.usuario_id)
        if identity.estado != FIRMA_IDENTIDAD_PENDIENTE:
            raise DocumentSignatureIdentityError("La identidad no puede verificarse en su estado actual.")
        if not file_storage or not file_storage.filename:
            raise DocumentSignatureIdentityError("Debes cargar un PDF firmado de enrolamiento.")
        if not file_storage.filename.lower().endswith(".pdf"):
            raise DocumentSignatureIdentityError("Solo se admite PDF firmado.")

        temp_path = self._save_enrollment_upload_temporarily(file_storage)
        try:
            DocumentPdfService().validate_pdf_file(temp_path, allow_signature_forms=True)
            validation = PyHankoPdfSignatureValidator().validate_enrollment_pdf(
                signed_pdf_path=temp_path,
                identificacion=identity.identificacion,
            )
        finally:
            temp_path.unlink(missing_ok=True)
        if not validation.valid:
            raise DocumentSignatureIdentityError(
                "El PDF de enrolamiento no supero la verificacion criptografica: "
                f"{validation.state}."
            )

        before = self._snapshot(identity)
        identity.estado = FIRMA_IDENTIDAD_VERIFICADA
        identity.verificado_por_id = actor.id
        identity.verificado_en = self._now()
        identity.certificado_fingerprint_sha256 = validation.certificate_fingerprint_sha256
        identity.nombre_certificado = validation.certificate_common_name or validation.signer_identifier
        identity.emisor_certificado = validation.certificate_issuer
        identity.metadata_json = {
            **(identity.metadata_json or {}),
            "verification_type": "cryptographic_signed_pdf",
            "certificate_subject": validation.certificate_subject,
            "certificate_serial": validation.certificate_serial,
            "certificate_issuer": validation.certificate_issuer,
            "certificate_email": validation.certificate_email,
            "certificate_identification": validation.certificate_identification,
            "certificate_fingerprint_sha256": validation.certificate_fingerprint_sha256,
        }
        db.session.flush()
        self._audit(actor=actor, accion="VERIFICAR_CRIPTOGRAFICA", identity=identity, antes=before, despues=self._snapshot(identity), ip=ip, user_agent=user_agent)
        db.session.commit()
        return identity

    def update_identity(self, *, actor, identity_id, identificacion, nombre_certificado=None, emisor_certificado=None, certificado_fingerprint_sha256=None, ip=None, user_agent=None):
        self._assert_permission(actor)
        identity = self._identity_for_actor(actor=actor, identity_id=identity_id)
        self._user_for_actor(actor=actor, user_id=identity.usuario_id)
        if identity.estado == FIRMA_IDENTIDAD_VERIFICADA:
            raise DocumentSignatureIdentityError("Una identidad verificada no puede modificarse.")
        before = self._snapshot(identity)
        identity.identificacion = self._normalize_identification(identificacion)
        identity.nombre_certificado = self._normalize_text(nombre_certificado, 255)
        identity.emisor_certificado = self._normalize_text(emisor_certificado, 255)
        identity.certificado_fingerprint_sha256 = self._normalize_fingerprint(certificado_fingerprint_sha256)
        db.session.flush()
        self._audit(actor=actor, accion="ACTUALIZAR", identity=identity, antes=before, despues=self._snapshot(identity), ip=ip, user_agent=user_agent)
        db.session.commit()
        return identity

    def _save_enrollment_upload_temporarily(self, file_storage):
        handle = tempfile.NamedTemporaryFile(prefix="labzeniso-enrolamiento-", suffix=".pdf", delete=False)
        temp_path = Path(handle.name)
        try:
            with handle:
                file_storage.save(handle)
            if temp_path.stat().st_size <= 0:
                raise DocumentSignatureIdentityError("El PDF firmado esta vacio.")
            return temp_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def verify_identity_mock(self, *, actor, identity_id, ip=None, user_agent=None):
        self._assert_permission(actor)
        identity = self._identity_for_actor(actor=actor, identity_id=identity_id)
        self._user_for_actor(actor=actor, user_id=identity.usuario_id)
        if identity.estado != FIRMA_IDENTIDAD_PENDIENTE:
            raise DocumentSignatureIdentityError("La identidad no puede verificarse en su estado actual.")
        before = self._snapshot(identity)
        identity.estado = FIRMA_IDENTIDAD_VERIFICADA
        identity.verificado_por_id = actor.id
        identity.verificado_en = self._now()
        identity.metadata_json = {
            **(identity.metadata_json or {}),
            "verification_type": "local_mock",
            "verification_note": "Verificacion local/mock para desarrollo y pruebas; no representa certificacion criptografica real.",
        }
        db.session.flush()
        self._audit(actor=actor, accion="VERIFICAR", identity=identity, antes=before, despues=self._snapshot(identity), ip=ip, user_agent=user_agent)
        db.session.commit()
        return identity

    def revoke_identity(self, *, actor, identity_id, ip=None, user_agent=None):
        self._assert_permission(actor)
        identity = self._identity_for_actor(actor=actor, identity_id=identity_id)
        self._user_for_actor(actor=actor, user_id=identity.usuario_id)
        if identity.estado == FIRMA_IDENTIDAD_REVOCADA:
            raise DocumentSignatureIdentityError("La identidad ya esta revocada.")
        before = self._snapshot(identity)
        identity.estado = FIRMA_IDENTIDAD_REVOCADA
        identity.metadata_json = {**(identity.metadata_json or {}), "revoked_locally": True, "revoked_at": self._now().isoformat()}
        db.session.flush()
        self._audit(actor=actor, accion="REVOCAR", identity=identity, antes=before, despues=self._snapshot(identity), ip=ip, user_agent=user_agent)
        db.session.commit()
        return identity
