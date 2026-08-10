from datetime import datetime, timezone

from app.extensions import db
from app.models.documentos import (
    CLASIFICACION_CONTROL_FORMATO,
    CLASIFICACION_CONTROL_INTERNO,
    DOCUMENTO_VIGOR_FORMATO,
    DOCUMENTO_VIGOR_INTERNO,
    ESTADO_VIGENTE,
    PUBLICACION_ACTIVA,
    DocumentoAprobacion,
    DocumentoVigorCatalogo,
)
from app.services.document_vigor_import_service import build_import_key


class DocumentCurrentCatalogSyncError(ValueError):
    pass


CATALOG_SOURCE_FILE = "PUBLICACION_AUTOMATICA"
CATALOG_SOURCE_SHEET = "publish_as_current"


def _now():
    return datetime.now(timezone.utc)


def _catalog_type_for_classification(clasificacion_control):
    if clasificacion_control == CLASIFICACION_CONTROL_INTERNO:
        return DOCUMENTO_VIGOR_INTERNO
    if clasificacion_control == CLASIFICACION_CONTROL_FORMATO:
        return DOCUMENTO_VIGOR_FORMATO
    raise DocumentCurrentCatalogSyncError(
        "El documento debe tener clasificacion de control INTERNO o FORMATO antes de publicarse como vigente."
    )


class DocumentCurrentCatalogSyncService:
    def __init__(self, session=None):
        self.session = session or db.session

    def sync_current_publication(self, *, documento, version_doc, publicacion, usuario):
        try:
            tipo_listado = self._validate(documento, version_doc, publicacion, usuario)
            row, action = self._upsert(
                documento=documento,
                version_doc=version_doc,
                publicacion=publicacion,
                usuario=usuario,
                tipo_listado=tipo_listado,
            )
            self._record_event(
                documento=documento,
                version_doc=version_doc,
                usuario=usuario,
                accion=action,
                comentario=(
                    f"Catalogo vigente sincronizado: {tipo_listado}; "
                    f"publicacion_id={publicacion.id}; registro_id={row.id}."
                ),
            )
            return row
        except DocumentCurrentCatalogSyncError as exc:
            self._record_event(
                documento=documento,
                version_doc=version_doc,
                usuario=usuario,
                accion="CATALOGO_VIGENTE_ERROR",
                comentario=str(exc),
            )
            raise

    def _validate(self, documento, version_doc, publicacion, usuario):
        if not usuario or usuario.empresa_id != documento.empresa_id:
            raise DocumentCurrentCatalogSyncError("El usuario no pertenece a la empresa del documento.")
        if version_doc.empresa_id != documento.empresa_id or version_doc.documento_id != documento.id:
            raise DocumentCurrentCatalogSyncError("La version vigente no pertenece al documento indicado.")
        if publicacion.empresa_id != documento.empresa_id:
            raise DocumentCurrentCatalogSyncError("La publicacion no pertenece a la empresa del documento.")
        if publicacion.documento_id != documento.id or publicacion.documento_version_id != version_doc.id:
            raise DocumentCurrentCatalogSyncError("La publicacion no corresponde al documento y version vigentes.")
        if documento.version_vigente_id != version_doc.id or version_doc.estado != ESTADO_VIGENTE:
            raise DocumentCurrentCatalogSyncError("La version indicada no es la version vigente del documento.")
        if publicacion.estado != PUBLICACION_ACTIVA or not publicacion.activa:
            raise DocumentCurrentCatalogSyncError("La publicacion indicada no esta activa.")
        return _catalog_type_for_classification(documento.clasificacion_control)

    def _upsert(self, *, documento, version_doc, publicacion, usuario, tipo_listado):
        now = _now()
        identidad_estable = f"DOCUMENTO:{documento.id}#1"
        clave_importacion = build_import_key(tipo_listado, identidad_estable)
        values = {
            "tipo_listado": tipo_listado,
            "clave_importacion": clave_importacion,
            "identidad_estable": identidad_estable,
            "ordinal_identidad": 1,
            "codigo": documento.codigo,
            "titulo": documento.titulo,
            "revision": version_doc.version,
            "fecha_vigencia": publicacion.vigente_desde.date() if publicacion.vigente_desde else None,
            "custodio": None,
            "acceso_documento": publicacion.qr_payload,
            "lugar_almacenamiento": publicacion.pdf_fuente_storage_key,
            "proteccion": publicacion.modo_acceso,
            "medio": "PDF",
            "destino_final": None,
            "seccion": documento.proceso or "DOCUMENTOS",
            "activo": True,
            "documento_id": documento.id,
            "documento_version_id": version_doc.id,
            "documento_publicacion_id": publicacion.id,
            "fuente_archivo": CATALOG_SOURCE_FILE,
            "fuente_hoja": CATALOG_SOURCE_SHEET,
            "fuente_fila": 1,
        }
        row = (
            self.session.query(DocumentoVigorCatalogo)
            .filter_by(
                empresa_id=documento.empresa_id,
                tipo_listado=tipo_listado,
                identidad_estable=identidad_estable,
            )
            .first()
        )
        if not row:
            row = DocumentoVigorCatalogo(
                empresa_id=documento.empresa_id,
                importado_por_id=usuario.id,
                importado_en=now,
                actualizado_por_id=usuario.id,
                actualizado_en=now,
                sincronizado_por_id=usuario.id,
                sincronizado_en=now,
                **values,
            )
            self.session.add(row)
            self.session.flush()
            self._deactivate_other_document_rows(row)
            return row, "CATALOGO_VIGENTE_ALTA"

        changed = False
        for field_name, value in values.items():
            if getattr(row, field_name) != value:
                setattr(row, field_name, value)
                changed = True
        row.sincronizado_por_id = usuario.id
        row.sincronizado_en = now
        if changed:
            row.actualizado_por_id = usuario.id
            row.actualizado_en = now
            action = "CATALOGO_VIGENTE_ACTUALIZADO"
        else:
            action = "CATALOGO_VIGENTE_SIN_CAMBIOS"
        self.session.flush()
        self._deactivate_other_document_rows(row)
        return row, action

    def _deactivate_other_document_rows(self, current_row):
        rows = (
            self.session.query(DocumentoVigorCatalogo)
            .filter(
                DocumentoVigorCatalogo.empresa_id == current_row.empresa_id,
                DocumentoVigorCatalogo.documento_id == current_row.documento_id,
                DocumentoVigorCatalogo.id != current_row.id,
                DocumentoVigorCatalogo.tipo_listado != "EXTERNO",
                DocumentoVigorCatalogo.activo.is_(True),
            )
            .all()
        )
        for row in rows:
            row.activo = False
            row.actualizado_en = current_row.sincronizado_en
            row.actualizado_por_id = current_row.sincronizado_por_id

    def _record_event(self, *, documento, version_doc, usuario, accion, comentario):
        self.session.add(DocumentoAprobacion(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            documento_version_id=version_doc.id,
            usuario_id=usuario.id,
            accion=accion,
            estado_anterior=version_doc.estado,
            estado_nuevo=version_doc.estado,
            fecha_accion=_now(),
            comentario=comentario,
        ))
