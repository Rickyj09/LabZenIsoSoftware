import os

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
from app.security.permissions import current_user_can, require_permission
from app.models.documentos import (
    Documento,
    DocumentoVersion,
    DocumentoAprobacion,
    ESTADOS_DOCUMENTO,
)
from app.services.document_versioning_service import (
    DocumentVersioningError,
    can_edit_document,
    create_draft_version,
    create_initial_version,
    get_current_version,
    get_preparation_version,
)
from app.services.document_workflow_service import (
    DocumentWorkflowError,
    approve_version as approve_workflow_version,
    get_latest_rejected_version,
    obsolete_document,
    record_document_event,
    reject_version as reject_workflow_version,
    return_to_draft,
    send_for_review,
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
from app.services.document_pending_service import get_pending_documents_for_user
from app.services.document_dashboard_service import get_document_dashboard_stats
from app.services.onlyoffice_document_view_service import (
    OnlyOfficeDocumentViewError,
    OnlyOfficeDocumentViewService,
    is_docx_version,
)
from app.services.onlyoffice_document_edit_service import (
    OnlyOfficeDocumentEditService,
    OnlyOfficeEditConflictError,
    OnlyOfficeEditError,
    OnlyOfficeEditSessionService,
    get_active_edit_info,
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


def workflow_request_metadata():
    return {
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
    }


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
@require_permission("documentos.ver")
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
@require_permission("documentos.ver")
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
@require_permission("documentos.ver")
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


@bp.route("/pendientes")
@login_required
@require_permission("documentos.ver_pendientes")
def pendientes():
    return render_template(
        "documentacion/pendientes.html",
        pendientes=get_pending_documents_for_user(current_user),
    )


@bp.route("/dashboard")
@login_required
@require_permission("documentos.ver")
def dashboard():
    return render_template(
        "documentacion/dashboard.html",
        stats=get_document_dashboard_stats(current_user),
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
@require_permission("documentos.crear")
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
                estado="EN_ELABORACION",
                version_actual=version,
                elaborado_por_id=current_user.id,
            )
            db.session.add(documento)
            db.session.flush()

            stored_file = store_document_file(
                archivo,
                documento=documento,
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
            db.session.flush()
            record_document_event(
                documento=documento,
                version_doc=version_doc,
                usuario=current_user,
                accion="CREAR_VERSION",
                estado_anterior=None,
                estado_nuevo="EN_ELABORACION",
                comentario=cambios,
                **workflow_request_metadata(),
            )

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
@require_permission("documentos.ver")
def detalle(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    can_view_history = current_user_can("documentos.ver_historial")
    versiones = []
    if can_view_history:
        versiones = (
            DocumentoVersion.query
            .filter_by(documento_id=item.id, empresa_id=current_user.empresa_id)
            .order_by(DocumentoVersion.fecha_version.desc(), DocumentoVersion.id.desc())
            .all()
        )

    version_vigente = get_current_version(item)
    version_preparacion = get_preparation_version(item)
    version_rechazada = get_latest_rejected_version(item)
    version_mostrada = version_vigente or version_preparacion or (versiones[0] if versiones else None)
    active_edit_info = get_active_edit_info(version_preparacion, current_user) if version_preparacion else None

    preview_url = None
    preview_tipo = None
    if (
        current_user_can("documentos.descargar")
        and version_mostrada
        and (version_mostrada.archivo_storage_path or version_mostrada.archivo_url)
    ):
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
        version_rechazada=version_rechazada,
        eventos=(
            DocumentoAprobacion.query
            .filter_by(documento_id=item.id, empresa_id=current_user.empresa_id)
            .order_by(DocumentoAprobacion.fecha_accion.desc(), DocumentoAprobacion.id.desc())
            .all()
        ) if can_view_history else [],
        can_view_history=can_view_history,
        preview_url=preview_url,
        preview_tipo=preview_tipo,
        onlyoffice_enabled=bool(current_app.config.get("ONLYOFFICE_ENABLED")),
        onlyoffice_edit_enabled=bool(current_app.config.get("ONLYOFFICE_EDIT_ENABLED")),
        is_docx_version=is_docx_version,
        active_edit_info=active_edit_info,
    )


@bp.route("/<int:item_id>/versiones/<int:version_id>/onlyoffice/ver")
@login_required
@require_permission("documentos.ver")
def ver_onlyoffice(item_id, version_id):
    try:
        context = OnlyOfficeDocumentViewService().build_context(
            documento_id=item_id,
            version_id=version_id,
            user=current_user,
        )
    except LookupError:
        abort(404)
    except FileNotFoundError:
        abort(404)
    except OnlyOfficeDocumentViewError as exc:
        abort(exc.status_code, description=str(exc))

    response = current_app.make_response(render_template(
        "documentacion/onlyoffice_viewer.html",
        item=context.documento,
        version=context.version,
        editor_config=context.editor_config,
        public_api_url=context.public_api_url,
    ))
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'unsafe-inline' {context.csp_origin}; "
        f"frame-src 'self' {context.csp_origin}; "
        f"connect-src 'self' {context.csp_origin}; "
        f"img-src 'self' data: {context.csp_origin}; "
        f"style-src 'self' 'unsafe-inline' {context.csp_origin}; "
        f"font-src 'self' data: {context.csp_origin}; "
        "object-src 'none'; base-uri 'self'"
    )
    return response


@bp.route("/<int:item_id>/versiones/<int:version_id>/onlyoffice/editar")
@login_required
@require_permission("documentos.editar")
def editar_onlyoffice(item_id, version_id):
    try:
        context = OnlyOfficeDocumentEditService().build_context(
            documento_id=item_id,
            version_id=version_id,
            user=current_user,
        )
    except LookupError:
        abort(404)
    except FileNotFoundError:
        abort(404)
    except OnlyOfficeEditConflictError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item_id))
    except OnlyOfficeEditError as exc:
        abort(exc.status_code, description=str(exc))
    except OnlyOfficeDocumentViewError as exc:
        abort(exc.status_code, description=str(exc))

    response = current_app.make_response(render_template(
        "documentacion/onlyoffice_editor.html",
        item=context.documento,
        version=context.version,
        edicion=context.edicion,
        editor_config=context.editor_config,
        public_api_url=context.public_api_url,
        heartbeat_seconds=context.heartbeat_seconds,
        force_save_debounce_seconds=context.force_save_debounce_seconds,
    ))
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'unsafe-inline' {context.csp_origin}; "
        f"frame-src 'self' {context.csp_origin}; "
        f"connect-src 'self' {context.csp_origin}; "
        f"img-src 'self' data: {context.csp_origin}; "
        f"style-src 'self' 'unsafe-inline' {context.csp_origin}; "
        f"font-src 'self' data: {context.csp_origin}; "
        "object-src 'none'; base-uri 'self'"
    )
    return response


@bp.route("/ediciones/<public_id>/heartbeat", methods=["POST"])
@login_required
def heartbeat_edicion(public_id):
    try:
        edicion = OnlyOfficeEditSessionService().heartbeat(public_id=public_id, user=current_user)
    except LookupError:
        abort(404)
    except OnlyOfficeEditError as exc:
        return {"ok": False, "message": str(exc)}, exc.status_code
    return {
        "ok": True,
        "estado": edicion.estado,
        "fecha_expiracion": edicion.fecha_expiracion.isoformat(),
    }


@bp.route("/ediciones/<public_id>/forcesave", methods=["POST"])
@login_required
def forcesave_edicion(public_id):
    try:
        result = OnlyOfficeEditSessionService().force_save(public_id=public_id, user=current_user)
    except LookupError:
        abort(404)
    except OnlyOfficeEditError as exc:
        return {"ok": False, "message": str(exc)}, exc.status_code
    return {"ok": True, "result": result}


@bp.route("/ediciones/<public_id>/estado", methods=["GET"])
@login_required
def estado_edicion(public_id):
    try:
        edicion = OnlyOfficeEditSessionService().get_owned_active_session(public_id=public_id, user=current_user)
    except LookupError:
        abort(404)
    except OnlyOfficeEditError as exc:
        return {"ok": False, "message": str(exc)}, exc.status_code
    return {
        "ok": True,
        "estado": edicion.estado,
        "ultimo_guardado_en": edicion.ultimo_guardado_en.isoformat() if edicion.ultimo_guardado_en else None,
        "error_ultimo_guardado": edicion.error_ultimo_guardado,
    }


@bp.route("/ediciones/<public_id>/liberar", methods=["POST"])
@login_required
def liberar_edicion(public_id):
    try:
        edicion = OnlyOfficeEditSessionService().release(
            public_id=public_id,
            user=current_user,
            reason=request.form.get("motivo") or "LiberaciÃ³n voluntaria desde editor.",
            administrative=False,
        )
    except LookupError:
        abort(404)
    flash("SesiÃ³n de ediciÃ³n liberada.", "success")
    return redirect(url_for("documentacion.detalle", item_id=edicion.documento_id))


@bp.route("/ediciones/<public_id>/liberar-admin", methods=["POST"])
@login_required
@require_permission("documentos.ver_historial")
def liberar_edicion_admin(public_id):
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("El motivo de liberaciÃ³n administrativa es obligatorio.", "warning")
        return redirect(request.referrer or url_for("documentacion.index"))
    try:
        edicion = OnlyOfficeEditSessionService().release(
            public_id=public_id,
            user=current_user,
            reason=motivo,
            administrative=True,
        )
    except LookupError:
        abort(404)
    flash("Bloqueo de ediciÃ³n liberado administrativamente.", "success")
    return redirect(url_for("documentacion.detalle", item_id=edicion.documento_id))


@bp.route("/version/<int:version_id>/descargar")
@login_required
@require_permission("documentos.descargar")
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
@require_permission("documentos.editar")
def editar(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if not can_edit_document(item):
        flash(
            "Solo los documentos en elaboración pueden editarse directamente. Para un documento aprobado debes crear una nueva versión.",
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
@require_permission("documentos.editar")
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
                documento=item,
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
            db.session.flush()
            record_document_event(
                documento=item,
                version_doc=nueva,
                usuario=current_user,
                accion="CREAR_VERSION",
                estado_anterior=None,
                estado_nuevo="EN_ELABORACION",
                comentario=cambios,
                **workflow_request_metadata(),
            )

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
@require_permission("documentos.aprobar")
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
        approve_workflow_version(
            documento=item,
            version_doc=version,
            usuario=current_user,
            comentario=request.form.get("comentario", ""),
            **workflow_request_metadata(),
        )
        db.session.commit()
    except DocumentWorkflowError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    flash("Versión aprobada correctamente.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/enviar-revision", methods=["POST"])
@login_required
@require_permission("documentos.enviar_revision")
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
        send_for_review(
            documento=item,
            version_doc=version_actual,
            usuario=current_user,
            comentario=request.form.get("comentario", ""),
            **workflow_request_metadata(),
        )
        db.session.commit()
    except DocumentWorkflowError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    flash("Documento enviado a revisión correctamente.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/rechazar-version/<int:version_id>", methods=["POST"])
@login_required
@require_permission("documentos.rechazar")
def rechazar_version(item_id, version_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    version = DocumentoVersion.query.filter_by(
        id=version_id,
        documento_id=item.id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()

    try:
        reject_workflow_version(
            documento=item,
            version_doc=version,
            usuario=current_user,
            comentario=request.form.get("comentario", ""),
            **workflow_request_metadata(),
        )
        db.session.commit()
    except DocumentWorkflowError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    flash("Versión rechazada. Debe devolverse a elaboración para su corrección.", "warning")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/devolver-borrador/<int:version_id>", methods=["POST"])
@login_required
@require_permission("documentos.devolver_borrador")
def devolver_borrador(item_id, version_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    version = DocumentoVersion.query.filter_by(
        id=version_id,
        documento_id=item.id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()

    try:
        return_to_draft(
            documento=item,
            version_doc=version,
            usuario=current_user,
            comentario=request.form.get("comentario", ""),
            **workflow_request_metadata(),
        )
        db.session.commit()
    except DocumentWorkflowError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    flash("Versión devuelta a elaboración para corrección.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/obsoletar", methods=["POST"])
@login_required
@require_permission("documentos.obsoletar")
def obsoletar(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    try:
        obsolete_document(
            documento=item,
            usuario=current_user,
            motivo=request.form.get("motivo", ""),
            **workflow_request_metadata(),
        )
        db.session.commit()
    except DocumentWorkflowError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    flash("Documento marcado como obsoleto.", "warning")
    return redirect(url_for("documentacion.detalle", item_id=item.id))
