from datetime import datetime, timezone
from uuid import uuid4

from app.extensions import db
from app.models.auditoria import AuditoriaLog
from app.models.documentos import CarpetaDocumental, Documento
from app.security.permissions import user_has_permission


FOLDER_CREATE_PERMISSION = "documentos.carpetas.crear"
FOLDER_EDIT_PERMISSION = "documentos.carpetas.editar"
FOLDER_DELETE_PERMISSION = "documentos.carpetas.eliminar"
FOLDER_MOVE_DOCUMENTS_PERMISSION = "documentos.carpetas.mover_documentos"
FOLDER_ADMIN_PERMISSION = "documentos.ver_historial"


class DocumentFolderError(ValueError):
    pass


def can_manage_document_folders(user, permission_code):
    return user_has_permission(user, permission_code) or user_has_permission(user, FOLDER_ADMIN_PERMISSION)


def can_create_document_folder(user):
    return can_manage_document_folders(user, FOLDER_CREATE_PERMISSION)


def can_edit_document_folder(user):
    return can_manage_document_folders(user, FOLDER_EDIT_PERMISSION)


def can_delete_document_folder(user):
    return can_manage_document_folders(user, FOLDER_DELETE_PERMISSION)


def can_move_document_to_folder(user):
    return can_manage_document_folders(user, FOLDER_MOVE_DOCUMENTS_PERMISSION)


class DocumentFolderService:
    def _now(self):
        return datetime.now(timezone.utc)

    def _normalize_name(self, nombre):
        normalized = (nombre or "").strip()
        if not normalized:
            raise DocumentFolderError("El nombre de la carpeta es obligatorio.")
        if len(normalized) > 150:
            raise DocumentFolderError("El nombre de la carpeta no puede superar 150 caracteres.")
        return normalized

    def _folder_for_user(self, folder_id, user, *, active_only=True):
        if not folder_id:
            return None
        query = CarpetaDocumental.query.filter_by(id=folder_id, empresa_id=user.empresa_id)
        if active_only:
            query = query.filter_by(activa=True)
        folder = query.first()
        if not folder:
            raise DocumentFolderError("La carpeta no existe o no esta disponible.")
        return folder

    def _document_for_user(self, document_id, user):
        document = Documento.query.filter_by(id=document_id, empresa_id=user.empresa_id).first()
        if not document:
            raise DocumentFolderError("El documento no existe o no esta disponible.")
        return document

    def _ensure_parent(self, parent_id, user):
        return self._folder_for_user(parent_id, user, active_only=True) if parent_id else None

    def _ensure_no_duplicate_name(self, *, user, nombre, parent_id, ignore_id=None):
        query = CarpetaDocumental.query.filter_by(
            empresa_id=user.empresa_id,
            padre_id=parent_id,
            nombre=nombre,
            activa=True,
        )
        if ignore_id:
            query = query.filter(CarpetaDocumental.id != ignore_id)
        if query.first():
            raise DocumentFolderError("Ya existe una carpeta activa con ese nombre en esta ubicacion.")

    def _is_descendant(self, *, folder, possible_descendant):
        current = possible_descendant
        while current:
            if int(current.id) == int(folder.id):
                return True
            current = current.padre
        return False

    def _audit(self, *, user, accion, registro_id, tabla="carpetas_documentales", antes=None, despues=None, ip=None, user_agent=None):
        db.session.add(AuditoriaLog(
            empresa_id=user.empresa_id,
            usuario_id=user.id,
            tabla=tabla,
            registro_id=registro_id,
            accion=accion,
            datos_antes=antes,
            datos_despues=despues,
            ip=ip,
            user_agent=user_agent,
        ))

    def create_folder(self, *, user, nombre, descripcion=None, parent_id=None, orden=0, ip=None, user_agent=None):
        if not can_create_document_folder(user):
            raise DocumentFolderError("No tiene permiso para crear carpetas documentales.")
        parent = self._ensure_parent(parent_id, user)
        nombre = self._normalize_name(nombre)
        self._ensure_no_duplicate_name(user=user, nombre=nombre, parent_id=getattr(parent, "id", None))
        folder = CarpetaDocumental(
            empresa_id=user.empresa_id,
            public_id=uuid4().hex,
            padre_id=getattr(parent, "id", None),
            nombre=nombre,
            descripcion=(descripcion or "").strip() or None,
            orden=int(orden or 0),
            activa=True,
            creada_por_id=user.id,
            actualizada_por_id=user.id,
        )
        db.session.add(folder)
        db.session.flush()
        self._audit(
            user=user,
            accion="CREAR_CARPETA",
            registro_id=folder.id,
            despues={"carpeta_id": folder.id, "padre_id": folder.padre_id, "nombre": folder.nombre},
            ip=ip,
            user_agent=user_agent,
        )
        return folder

    def update_folder(self, *, user, folder_id, nombre, descripcion=None, ip=None, user_agent=None):
        if not can_edit_document_folder(user):
            raise DocumentFolderError("No tiene permiso para editar carpetas documentales.")
        folder = self._folder_for_user(folder_id, user)
        nombre = self._normalize_name(nombre)
        self._ensure_no_duplicate_name(user=user, nombre=nombre, parent_id=folder.padre_id, ignore_id=folder.id)
        before = {"nombre": folder.nombre, "descripcion": folder.descripcion}
        folder.nombre = nombre
        folder.descripcion = (descripcion or "").strip() or None
        folder.actualizada_por_id = user.id
        self._audit(
            user=user,
            accion="RENOMBRAR_CARPETA",
            registro_id=folder.id,
            antes=before,
            despues={"nombre": folder.nombre, "descripcion": folder.descripcion},
            ip=ip,
            user_agent=user_agent,
        )
        return folder

    def move_folder(self, *, user, folder_id, parent_id=None, ip=None, user_agent=None):
        if not can_edit_document_folder(user):
            raise DocumentFolderError("No tiene permiso para mover carpetas documentales.")
        folder = self._folder_for_user(folder_id, user)
        parent = self._ensure_parent(parent_id, user)
        if parent and int(parent.id) == int(folder.id):
            raise DocumentFolderError("Una carpeta no puede ser su propio padre.")
        if parent and self._is_descendant(folder=folder, possible_descendant=parent):
            raise DocumentFolderError("No se puede mover una carpeta dentro de una de sus subcarpetas.")
        new_parent_id = getattr(parent, "id", None)
        self._ensure_no_duplicate_name(user=user, nombre=folder.nombre, parent_id=new_parent_id, ignore_id=folder.id)
        before = {"padre_id": folder.padre_id}
        folder.padre_id = new_parent_id
        folder.actualizada_por_id = user.id
        self._audit(
            user=user,
            accion="MOVER_CARPETA",
            registro_id=folder.id,
            antes=before,
            despues={"padre_id": folder.padre_id},
            ip=ip,
            user_agent=user_agent,
        )
        return folder

    def deactivate_folder(self, *, user, folder_id, ip=None, user_agent=None):
        if not can_delete_document_folder(user):
            raise DocumentFolderError("No tiene permiso para eliminar carpetas documentales.")
        folder = self._folder_for_user(folder_id, user)
        has_subfolders = CarpetaDocumental.query.filter_by(
            empresa_id=user.empresa_id,
            padre_id=folder.id,
            activa=True,
        ).first()
        has_documents = Documento.query.filter_by(empresa_id=user.empresa_id, carpeta_id=folder.id).first()
        if has_subfolders or has_documents:
            raise DocumentFolderError("La carpeta contiene documentos o subcarpetas y no puede eliminarse.")
        folder.activa = False
        folder.actualizada_por_id = user.id
        self._audit(
            user=user,
            accion="DESACTIVAR_CARPETA",
            registro_id=folder.id,
            antes={"activa": True},
            despues={"activa": False},
            ip=ip,
            user_agent=user_agent,
        )
        return folder

    def assign_document(self, *, user, document_id, folder_id=None, ip=None, user_agent=None):
        if not can_move_document_to_folder(user):
            raise DocumentFolderError("No tiene permiso para mover documentos entre carpetas.")
        document = self._document_for_user(document_id, user)
        folder = self._ensure_parent(folder_id, user)
        before = {"carpeta_id": document.carpeta_id, "estado": document.estado, "version_actual": document.version_actual}
        document.carpeta_id = getattr(folder, "id", None)
        after = {"carpeta_id": document.carpeta_id, "estado": document.estado, "version_actual": document.version_actual}
        action = "QUITAR_DOCUMENTO_CARPETA" if folder is None else (
            "ASIGNAR_DOCUMENTO_CARPETA" if before["carpeta_id"] is None else "MOVER_DOCUMENTO_CARPETA"
        )
        self._audit(
            user=user,
            accion=action,
            registro_id=document.id,
            tabla="documentos",
            antes=before,
            despues=after,
            ip=ip,
            user_agent=user_agent,
        )
        return document
