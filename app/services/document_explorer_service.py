from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.documentos import (
    ANEXO_ESTADO_ELIMINADO,
    CarpetaDocumental,
    Documento,
    DocumentoVersionAnexo,
)


UNCATEGORIZED_KEY = "sin-clasificar"


@dataclass(frozen=True)
class FolderOption:
    id: int | None
    label: str
    depth: int = 0


class DocumentExplorerError(ValueError):
    pass


class DocumentExplorerService:
    def get_folder(self, *, user, folder_id):
        if not folder_id:
            return None
        folder = CarpetaDocumental.query.filter_by(
            id=folder_id,
            empresa_id=user.empresa_id,
            activa=True,
        ).first()
        if not folder:
            raise DocumentExplorerError("La carpeta no existe o no esta disponible.")
        return folder

    def breadcrumb(self, *, folder):
        if not folder:
            return []
        nodes = []
        current = folder
        while current:
            nodes.append(current)
            current = current.padre if current.padre and current.padre.activa else None
        return list(reversed(nodes))

    def folder_tree(self, *, user):
        folders = (
            CarpetaDocumental.query
            .filter_by(empresa_id=user.empresa_id, activa=True)
            .order_by(CarpetaDocumental.orden.asc(), CarpetaDocumental.nombre.asc())
            .all()
        )
        by_parent = {}
        for folder in folders:
            by_parent.setdefault(folder.padre_id, []).append(folder)

        def build(parent_id=None, depth=0):
            return [
                {
                    "folder": folder,
                    "depth": depth,
                    "children": build(folder.id, depth + 1),
                }
                for folder in by_parent.get(parent_id, [])
            ]

        return build(None)

    def folder_options(self, *, user, exclude_folder_id=None):
        tree = self.folder_tree(user=user)
        options = [FolderOption(id=None, label="Raiz", depth=0)]

        def add_nodes(nodes):
            for node in nodes:
                folder = node["folder"]
                if exclude_folder_id and int(folder.id) == int(exclude_folder_id):
                    continue
                options.append(FolderOption(id=folder.id, label=folder.nombre, depth=node["depth"] + 1))
                add_nodes(node["children"])

        add_nodes(tree)
        return options

    def _active_document_query(self, *, user):
        return (
            Documento.query
            .filter_by(empresa_id=user.empresa_id)
            .options(joinedload(Documento.version_vigente), joinedload(Documento.elaborado_por))
        )

    def _apply_filters(self, query, *, q=None, estado=None, tipo=None, proceso=None):
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(db.or_(Documento.codigo.ilike(like), Documento.titulo.ilike(like)))
        if estado:
            query = query.filter(Documento.estado == estado)
        if tipo:
            query = query.filter(Documento.tipo_documento == tipo)
        if proceso:
            query = query.filter(Documento.proceso == proceso)
        return query

    def list_content(self, *, user, folder=None, uncategorized=False, q=None, estado=None, tipo=None, proceso=None):
        folder_id = getattr(folder, "id", None)
        subfolders = []
        if not uncategorized:
            subfolders = (
                CarpetaDocumental.query
                .filter_by(empresa_id=user.empresa_id, padre_id=folder_id, activa=True)
                .order_by(CarpetaDocumental.orden.asc(), CarpetaDocumental.nombre.asc())
                .all()
            )

        query = self._active_document_query(user=user)
        if uncategorized:
            query = query.filter(Documento.carpeta_id.is_(None))
        else:
            query = query.filter(Documento.carpeta_id == folder_id)
        documents = (
            self._apply_filters(query, q=q, estado=estado, tipo=tipo, proceso=proceso)
            .order_by(Documento.codigo.asc())
            .all()
        )
        return {
            "subfolders": subfolders,
            "documents": documents,
            "document_counts": self.document_counts(user=user),
            "subfolder_counts": self.subfolder_counts(user=user),
            "attachment_counts": self.attachment_counts(user=user, documents=documents),
        }

    def document_counts(self, *, user):
        rows = (
            db.session.query(Documento.carpeta_id, func.count(Documento.id))
            .filter(Documento.empresa_id == user.empresa_id)
            .group_by(Documento.carpeta_id)
            .all()
        )
        return {row[0]: row[1] for row in rows}

    def subfolder_counts(self, *, user):
        rows = (
            db.session.query(CarpetaDocumental.padre_id, func.count(CarpetaDocumental.id))
            .filter(CarpetaDocumental.empresa_id == user.empresa_id, CarpetaDocumental.activa.is_(True))
            .group_by(CarpetaDocumental.padre_id)
            .all()
        )
        return {row[0]: row[1] for row in rows}

    def attachment_counts(self, *, user, documents):
        document_ids = [document.id for document in documents]
        if not document_ids:
            return {}
        rows = (
            db.session.query(DocumentoVersionAnexo.documento_id, func.count(DocumentoVersionAnexo.id))
            .filter(
                DocumentoVersionAnexo.empresa_id == user.empresa_id,
                DocumentoVersionAnexo.documento_id.in_(document_ids),
                DocumentoVersionAnexo.estado != ANEXO_ESTADO_ELIMINADO,
            )
            .group_by(DocumentoVersionAnexo.documento_id)
            .all()
        )
        return {row[0]: row[1] for row in rows}

    def filter_options(self, *, user):
        tipos = [
            row[0]
            for row in db.session.query(Documento.tipo_documento)
            .filter(Documento.empresa_id == user.empresa_id, Documento.tipo_documento.isnot(None))
            .distinct()
            .order_by(Documento.tipo_documento.asc())
            .all()
        ]
        procesos = [
            row[0]
            for row in db.session.query(Documento.proceso)
            .filter(Documento.empresa_id == user.empresa_id, Documento.proceso.isnot(None), Documento.proceso != "")
            .distinct()
            .order_by(Documento.proceso.asc())
            .all()
        ]
        return {"tipos": tipos, "procesos": procesos}
