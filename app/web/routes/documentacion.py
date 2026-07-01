import os
from datetime import datetime, timezone

from flask import (
    abort,
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    send_file,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.models.documentos import (
    Documento,
    DocumentoVersion,
    DocumentoAprobacion,
    ESTADOS_DOCUMENTO,
)
from app.services.document_versioning_service import (
    DocumentVersioningError,
    approve_version as approve_document_version,
    can_edit_document,
    create_draft_version,
    create_initial_version,
    get_current_version,
    get_preparation_version,
    send_to_review,
)
from app.services.storage_service import (
    apply_stored_file_metadata,
    DocumentStorageError,
    delete_document_file,
    resolve_document_path,
    resolve_legacy_document_path,
    store_document_file,
    validate_document_file,
)

bp = Blueprint("documentacion", __name__, url_prefix="/documentacion")

TIPOS_DOCUMENTO = [
    "POLITICA",
    "PROCEDIMIENTO",
    "INSTRUCTIVO",
    "FORMATO",
    "REGISTRO",
    "MANUAL",
    "OTRO",
]

PREVIEWABLE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


def ruta_archivo_legacy(version_doc):
    """Compatibilidad temporal: retirar cuando los archivos históricos sean migrados."""
    try:
        return resolve_legacy_document_path(version_doc.archivo_url)
    except DocumentStorageError:
        return None


def extension_desde_url(archivo_url):
    if not archivo_url:
        return None
    nombre = archivo_url.split("/")[-1]
    if "." not in nombre:
        return None
    return nombre.rsplit(".", 1)[1].lower()


def extension_version(version_doc):
    nombre = (
        version_doc.archivo_nombre_original
        or version_doc.archivo_nombre_guardado
        or version_doc.archivo_url
    )
    return extension_desde_url(nombre)


@bp.route("/")
@login_required
def index():
    tipo = request.args.get("tipo", "").strip()
    estado = request.args.get("estado", "").strip()
    q = request.args.get("q", "").strip()

    query = Documento.query.filter_by(empresa_id=current_user.empresa_id)
    query = query.filter(Documento.tipo_documento != "REGISTRO")

    if tipo:
        query = query.filter(Documento.tipo_documento == tipo)

    if estado:
        query = query.filter(Documento.estado == estado)
    else:
        query = query.filter(Documento.estado != "OBSOLETO")

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Documento.codigo.ilike(like),
                Documento.titulo.ilike(like),
                Documento.proceso.ilike(like),
            )
        )

    documentos = query.order_by(Documento.codigo.asc()).all()

    return render_template(
        "documentacion/index.html",
        documentos=documentos,
        titulo_modulo="Gestión Documental",
        tipo=tipo,
        estado=estado,
        q=q,
        tipos_documento=TIPOS_DOCUMENTO,
        vista="documentos",
    )


@bp.route("/registros")
@login_required
def registros():
    estado = request.args.get("estado", "").strip()
    q = request.args.get("q", "").strip()

    query = Documento.query.filter_by(
        empresa_id=current_user.empresa_id,
        tipo_documento="REGISTRO"
    )

    if estado:
        query = query.filter(Documento.estado == estado)

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Documento.codigo.ilike(like),
                Documento.titulo.ilike(like),
                Documento.proceso.ilike(like),
            )
        )

    documentos = query.order_by(Documento.codigo.asc()).all()

    return render_template(
        "documentacion/index.html",
        documentos=documentos,
        titulo_modulo="Registros",
        tipo="REGISTRO",
        estado=estado,
        q=q,
        tipos_documento=TIPOS_DOCUMENTO,
        vista="registros",
    )


@bp.route("/archivo")
@login_required
def archivo():
    q = request.args.get("q", "").strip()

    query = Documento.query.filter_by(empresa_id=current_user.empresa_id)
    query = query.filter(Documento.estado == "OBSOLETO")

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Documento.codigo.ilike(like),
                Documento.titulo.ilike(like),
                Documento.proceso.ilike(like),
            )
        )

    documentos = query.order_by(Documento.codigo.asc()).all()

    return render_template(
        "documentacion/index.html",
        documentos=documentos,
        titulo_modulo="Archivo Documental",
        tipo="",
        estado="",
        q=q,
        tipos_documento=TIPOS_DOCUMENTO,
        vista="archivo",
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip().upper()
        titulo = request.form.get("titulo", "").strip()
        tipo_documento = request.form.get("tipo_documento", "").strip()
        proceso = request.form.get("proceso", "").strip()
        version = request.form.get("version", "").strip() or "1"
        contenido = request.form.get("contenido", "").strip()
        cambios = request.form.get("cambios", "").strip() or "Versión inicial del documento"

        archivo = request.files.get("archivo")
        try:
            validate_document_file(archivo)
        except DocumentStorageError as exc:
            flash(str(exc), "danger")
            return render_template(
                "documentacion/form.html",
                item=None,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        if not codigo or not titulo or not tipo_documento or not version:
            flash("Código, título, tipo de documento y versión son obligatorios.", "danger")
            return render_template(
                "documentacion/form.html",
                item=None,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        existente = Documento.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo=codigo
        ).first()

        if existente:
            flash("Ya existe un documento con ese código.", "danger")
            return render_template(
                "documentacion/form.html",
                item=None,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        stored_file = None
        try:
            documento = Documento(
                empresa_id=current_user.empresa_id,
                codigo=codigo,
                titulo=titulo,
                tipo_documento=tipo_documento,
                proceso=proceso or None,
                estado="BORRADOR",
                version_actual=version,
                elaborado_por_id=current_user.id,
            )
            db.session.add(documento)
            db.session.flush()

            stored_file = store_document_file(
                archivo,
                empresa_id=current_user.empresa_id,
                documento_id=documento.id,
                version=version,
            )
            version_doc = create_initial_version(
                documento=documento,
                version=version,
                cambios=cambios,
                contenido=contenido,
                user_id=current_user.id,
            )
            apply_stored_file_metadata(version_doc, stored_file)

            db.session.commit()
        except (DocumentStorageError, DocumentVersioningError) as exc:
            db.session.rollback()
            delete_document_file(stored_file.storage_path if stored_file else None)
            flash(str(exc), "danger")
            return render_template(
                "documentacion/form.html",
                item=None,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )
        except Exception:
            db.session.rollback()
            delete_document_file(stored_file.storage_path if stored_file else None)
            current_app.logger.exception("No se pudo crear el documento")
            flash("No se pudo guardar el documento. Inténtalo nuevamente.", "danger")
            return render_template(
                "documentacion/form.html",
                item=None,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        flash("Documento creado correctamente.", "success")
        return redirect(url_for("documentacion.detalle", item_id=documento.id))

    return render_template(
        "documentacion/form.html",
        item=None,
        version_item=None,
        tipos_documento=TIPOS_DOCUMENTO,
        estados_documento=ESTADOS_DOCUMENTO,
    )


@bp.route("/<int:item_id>")
@login_required
def detalle(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    versiones = (
        DocumentoVersion.query
        .filter_by(documento_id=item.id, empresa_id=current_user.empresa_id)
        .order_by(DocumentoVersion.fecha_version.desc(), DocumentoVersion.id.desc())
        .all()
    )

    version_vigente = get_current_version(item)
    version_preparacion = get_preparation_version(item)
    version_mostrada = version_vigente or version_preparacion or (versiones[0] if versiones else None)

    preview_url = None
    preview_tipo = None
    if version_mostrada and (version_mostrada.archivo_storage_path or version_mostrada.archivo_url):
        preview_tipo = extension_version(version_mostrada)
        if preview_tipo in PREVIEWABLE_EXTENSIONS:
            preview_url = url_for(
                "documentacion.descargar_version",
                version_id=version_mostrada.id,
                inline=1,
            )

    return render_template(
        "documentacion/detalle.html",
        item=item,
        versiones=versiones,
        version_trazabilidad=version_mostrada,
        version_vigente=version_vigente,
        version_preparacion=version_preparacion,
        preview_url=preview_url,
        preview_tipo=preview_tipo,
    )


@bp.route("/version/<int:version_id>/descargar")
@login_required
def descargar_version(version_id):
    version_doc = (
        DocumentoVersion.query
        .join(Documento, DocumentoVersion.documento_id == Documento.id)
        .filter(
            DocumentoVersion.id == version_id,
            DocumentoVersion.empresa_id == current_user.empresa_id,
            Documento.empresa_id == current_user.empresa_id,
        )
        .first_or_404()
    )

    try:
        if version_doc.archivo_storage_path:
            physical_path = resolve_document_path(version_doc.archivo_storage_path)
        else:
            # Compatibilidad temporal hasta migrar físicamente los archivos históricos.
            legacy_path = ruta_archivo_legacy(version_doc)
            physical_path = None if legacy_path is None else legacy_path
    except DocumentStorageError:
        current_app.logger.warning(
            "Ruta documental inválida para la versión %s", version_doc.id
        )
        abort(404)

    if not physical_path or not os.path.isfile(physical_path):
        abort(404)

    download_name = (
        version_doc.archivo_nombre_original
        or os.path.basename(str(physical_path))
    )
    return send_file(
        physical_path,
        as_attachment=request.args.get("inline") != "1",
        download_name=download_name,
        mimetype=version_doc.archivo_mime or None,
        conditional=True,
    )


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if not can_edit_document(item):
        flash(
            "Solo los documentos en borrador pueden editarse directamente. Para un documento aprobado debes crear una nueva versión.",
            "warning",
        )
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip().upper()
        titulo = request.form.get("titulo", "").strip()
        tipo_documento = request.form.get("tipo_documento", "").strip()
        proceso = request.form.get("proceso", "").strip()

        if not codigo or not titulo or not tipo_documento:
            flash("Código, título y tipo de documento son obligatorios.", "danger")
            return render_template(
                "documentacion/form.html",
                item=item,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        existente = Documento.query.filter(
            Documento.empresa_id == current_user.empresa_id,
            Documento.codigo == codigo,
            Documento.id != item.id
        ).first()

        if existente:
            flash("Ya existe otro documento con ese código.", "danger")
            return render_template(
                "documentacion/form.html",
                item=item,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        item.codigo = codigo
        item.titulo = titulo
        item.tipo_documento = tipo_documento
        item.proceso = proceso or None
        db.session.commit()
        flash("Documento actualizado correctamente.", "success")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    return render_template(
        "documentacion/form.html",
        item=item,
        version_item=None,
        tipos_documento=TIPOS_DOCUMENTO,
        estados_documento=ESTADOS_DOCUMENTO,
    )


@bp.route("/<int:item_id>/nueva-version", methods=["GET", "POST"])
@login_required
def nueva_version(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if request.method == "POST":
        version = request.form.get("version", "").strip()
        contenido = request.form.get("contenido", "").strip()
        cambios = request.form.get("cambios", "").strip()

        archivo = request.files.get("archivo")
        try:
            validate_document_file(archivo)
        except DocumentStorageError as exc:
            flash(str(exc), "danger")
            return render_template(
                "documentacion/version_form.html",
                item=item,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        if not version or not cambios:
            flash("La versión y la descripción de cambios son obligatorias.", "danger")
            return render_template(
                "documentacion/version_form.html",
                item=item,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        stored_file = None
        try:
            stored_file = store_document_file(
                archivo,
                empresa_id=current_user.empresa_id,
                documento_id=item.id,
                version=version,
            )
            nueva = create_draft_version(
                documento=item,
                version=version,
                cambios=cambios,
                contenido=contenido,
                user_id=current_user.id,
            )
            apply_stored_file_metadata(nueva, stored_file)

            db.session.commit()
        except (DocumentStorageError, DocumentVersioningError) as exc:
            db.session.rollback()
            delete_document_file(stored_file.storage_path if stored_file else None)
            flash(str(exc), "danger")
            return render_template(
                "documentacion/version_form.html",
                item=item,
                estados_documento=ESTADOS_DOCUMENTO,
            )
        except Exception:
            db.session.rollback()
            delete_document_file(stored_file.storage_path if stored_file else None)
            current_app.logger.exception("No se pudo crear la versión documental")
            flash("No se pudo guardar la versión. Inténtalo nuevamente.", "danger")
            return render_template(
                "documentacion/version_form.html",
                item=item,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        flash("Nueva versión registrada correctamente.", "success")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    return render_template(
        "documentacion/version_form.html",
        item=item,
        estados_documento=ESTADOS_DOCUMENTO,
    )


@bp.route("/<int:item_id>/aprobar-version/<int:version_id>", methods=["POST"])
@login_required
def aprobar_version(item_id, version_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    version = DocumentoVersion.query.filter_by(
        id=version_id,
        documento_id=item.id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    try:
        approve_document_version(
            documento=item,
            version_doc=version,
            user_id=current_user.id,
        )
    except DocumentVersioningError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    aprobacion = DocumentoAprobacion(
        empresa_id=current_user.empresa_id,
        documento_version_id=version.id,
        usuario_id=current_user.id,
        accion="APROBADO",
        fecha_accion=datetime.now(timezone.utc),
        comentario="Documento aprobado desde el flujo documental",
    )
    db.session.add(aprobacion)
    db.session.commit()

    flash("Versión aprobada correctamente.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/enviar-revision", methods=["POST"])
@login_required
def enviar_revision(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    version_actual = get_preparation_version(item)

    if not version_actual:
        flash("No se encontró una versión en preparación para el documento.", "danger")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    try:
        send_to_review(
            documento=item,
            version_doc=version_actual,
            user_id=current_user.id,
        )
    except DocumentVersioningError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    movimiento = DocumentoAprobacion(
        empresa_id=current_user.empresa_id,
        documento_version_id=version_actual.id,
        usuario_id=current_user.id,
        accion="EN_REVISION",
        fecha_accion=datetime.now(timezone.utc),
        comentario="Documento enviado a revisión",
    )
    db.session.add(movimiento)
    db.session.commit()

    flash("Documento enviado a revisión correctamente.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/obsoletar", methods=["POST"])
@login_required
def obsoletar(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    item.estado = "OBSOLETO"

    version_actual = get_current_version(item)
    version_preparacion = get_preparation_version(item)

    if version_actual:
        version_actual.estado = "OBSOLETO"
        version_actual.fecha_obsolescencia = datetime.now(timezone.utc)

        movimiento = DocumentoAprobacion(
            empresa_id=current_user.empresa_id,
            documento_version_id=version_actual.id,
            usuario_id=current_user.id,
            accion="OBSOLETO",
            fecha_accion=datetime.now(timezone.utc),
            comentario="Documento marcado como obsoleto",
        )
        db.session.add(movimiento)

    if version_preparacion:
        version_preparacion.estado = "OBSOLETO"
        version_preparacion.fecha_obsolescencia = datetime.now(timezone.utc)

    item.version_vigente_id = None
    item.version_vigente = None

    db.session.commit()
    flash("Documento marcado como obsoleto.", "warning")
    return redirect(url_for("documentacion.detalle", item_id=item.id))
