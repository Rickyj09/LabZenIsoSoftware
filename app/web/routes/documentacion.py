import hmac
import os
import secrets

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
    session,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.security.permissions import current_user_can, require_permission
from app.models.documentos import (
    Documento,
    DocumentoVersion,
    DocumentoVersionAnexo,
    DocumentoAprobacion,
    ESTADOS_DOCUMENTO,
    DocumentoFirmaProceso,
    DocumentoFirmaPaso,
    FIRMA_PROCESO_COMPLETADO,
    FIRMA_PROCESO_EN_FIRMA,
    FIRMA_PROCESO_PENDIENTE,
    FIRMA_PASO_HABILITADO,
)
from app.models.seguridad import Usuario
from app.services.document_attachment_service import (
    DocumentAttachmentError,
    DocumentAttachmentService,
    can_user_edit_attachment,
    list_active_attachments,
)
from app.services.document_versioning_service import (
    DocumentVersioningError,
    can_edit_document,
    create_draft_version,
    create_initial_version,
    get_current_version,
    get_preparation_version,
    validate_document_responsibles,
)
from app.services.document_workflow_service import (
    DocumentWorkflowError,
    approve_version as approve_workflow_version,
    get_latest_rejected_version,
    mark_review_conformity,
    obsolete_document,
    record_document_event,
    reject_version as reject_workflow_version,
    request_review_corrections,
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
from app.services.document_explorer_service import DocumentExplorerError, DocumentExplorerService
from app.services.document_folder_service import (
    DocumentFolderError,
    DocumentFolderService,
    can_create_document_folder,
    can_delete_document_folder,
    can_edit_document_folder,
    can_move_document_to_folder,
)
from app.services.document_snapshot_service import DocumentSnapshotError, DocumentSnapshotService
from app.services.document_pdf_service import DocumentPdfError, DocumentPdfService
from app.services.document_signature_service import (
    DocumentSignatureError,
    DocumentSignatureService,
    START_SIGNATURE_PERMISSION,
)
from app.services.document_signature_identity_service import SIGNATURE_IDENTITY_PERMISSION
from app.services.document_signature_dev_service import (
    DocumentSignatureDevCertificateService,
    DocumentSignatureDevError,
    dev_signature_mode_enabled,
)
from app.services.onlyoffice_document_view_service import (
    OnlyOfficeDocumentViewError,
    OnlyOfficeDocumentViewService,
    is_onlyoffice_supported_version,
)
from app.services.onlyoffice_document_edit_service import (
    OnlyOfficeDocumentEditService,
    OnlyOfficeEditConflictError,
    OnlyOfficeEditError,
    OnlyOfficeEditSessionService,
    can_user_edit_onlyoffice_version,
    get_active_edit_info,
)

bp = Blueprint("documentacion", __name__, url_prefix="/documentacion")


def _dev_signature_csrf_session_key(public_id):
    return f"dev_signature_csrf:{public_id}"


def _issue_dev_signature_csrf_token(public_id):
    token = secrets.token_urlsafe(32)
    session[_dev_signature_csrf_session_key(public_id)] = token
    return token


def _validate_dev_signature_csrf_token(public_id):
    expected = session.get(_dev_signature_csrf_session_key(public_id))
    provided = request.form.get("csrf_token", "")
    return bool(expected and provided and hmac.compare_digest(expected, provided))

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


def _responsables_documentales():
    return (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(Usuario.nombre.asc(), Usuario.apellido.asc(), Usuario.id.asc())
        .all()
    )


def _document_form_context(item=None, version_item=None, form_data=None):
    return {
        "item": item,
        "version_item": version_item,
        "tipos_documento": TIPOS_DOCUMENTO,
        "estados_documento": ESTADOS_DOCUMENTO,
        "responsables_documentales": _responsables_documentales(),
        "form_data": form_data or {},
    }


def _version_form_context(item, form_data=None):
    return {
        "item": item,
        "estados_documento": ESTADOS_DOCUMENTO,
        "responsables_documentales": _responsables_documentales(),
        "form_data": form_data or {},
    }


def workflow_request_metadata():
    return {
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
    }


def _redirect_to_explorer(folder_id=None, uncategorized=False):
    if uncategorized:
        return redirect(url_for("documentacion.explorador_sin_clasificar"))
    if folder_id:
        return redirect(url_for("documentacion.explorador_carpeta", carpeta_id=folder_id))
    return redirect(url_for("documentacion.explorador"))


def _optional_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DocumentFolderError("La carpeta indicada no es valida.") from exc


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


def _archivo_principal_es_anexo_excel(file_storage):
    filename = (getattr(file_storage, "filename", "") or "").lower()
    return filename.endswith(".xlsx") or filename.endswith(".xlsm") or filename.endswith(".xltm")


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


def _render_explorer(folder_id=None, uncategorized=False):
    explorer = DocumentExplorerService()
    try:
        folder = None if uncategorized else explorer.get_folder(user=current_user, folder_id=folder_id)
    except DocumentExplorerError:
        abort(404)
    filters = {
        "q": request.args.get("q", "").strip(),
        "estado": request.args.get("estado", "").strip(),
        "tipo": request.args.get("tipo", "").strip(),
        "proceso": request.args.get("proceso", "").strip(),
    }
    content = explorer.list_content(
        user=current_user,
        folder=folder,
        uncategorized=uncategorized,
        **filters,
    )
    return render_template(
        "documentacion/explorador.html",
        folder=folder,
        uncategorized=uncategorized,
        breadcrumb=explorer.breadcrumb(folder=folder),
        tree=explorer.folder_tree(user=current_user),
        folder_options=explorer.folder_options(user=current_user, exclude_folder_id=getattr(folder, "id", None)),
        filters=filters,
        filter_options=explorer.filter_options(user=current_user),
        estados_documento=ESTADOS_DOCUMENTO,
        subfolders=content["subfolders"],
        documents=content["documents"],
        document_counts=content["document_counts"],
        subfolder_counts=content["subfolder_counts"],
        attachment_counts=content["attachment_counts"],
        can_create_folder=can_create_document_folder(current_user),
        can_edit_folder=can_edit_document_folder(current_user),
        can_delete_folder=can_delete_document_folder(current_user),
        can_move_documents=can_move_document_to_folder(current_user),
    )


@bp.route("/explorador")
@login_required
@require_permission("documentos.ver")
def explorador():
    return _render_explorer()


@bp.route("/explorador/sin-clasificar")
@login_required
@require_permission("documentos.ver")
def explorador_sin_clasificar():
    return _render_explorer(uncategorized=True)


@bp.route("/explorador/carpetas/<int:carpeta_id>")
@login_required
@require_permission("documentos.ver")
def explorador_carpeta(carpeta_id):
    return _render_explorer(folder_id=carpeta_id)


@bp.route("/explorador/carpetas", methods=["POST"])
@login_required
def crear_carpeta():
    parent_id = _optional_int(request.form.get("padre_id"))
    try:
        folder = DocumentFolderService().create_folder(
            user=current_user,
            nombre=request.form.get("nombre"),
            descripcion=request.form.get("descripcion"),
            parent_id=parent_id,
            orden=request.form.get("orden") or 0,
            **workflow_request_metadata(),
        )
        db.session.commit()
        flash("Carpeta creada correctamente.", "success")
        return _redirect_to_explorer(folder.id)
    except DocumentFolderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return _redirect_to_explorer(parent_id)


@bp.route("/explorador/carpetas/<int:carpeta_id>/editar", methods=["POST"])
@login_required
def editar_carpeta(carpeta_id):
    try:
        DocumentFolderService().update_folder(
            user=current_user,
            folder_id=carpeta_id,
            nombre=request.form.get("nombre"),
            descripcion=request.form.get("descripcion"),
            **workflow_request_metadata(),
        )
        db.session.commit()
        flash("Carpeta actualizada correctamente.", "success")
    except DocumentFolderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _redirect_to_explorer(carpeta_id)


@bp.route("/explorador/carpetas/<int:carpeta_id>/mover", methods=["POST"])
@login_required
def mover_carpeta(carpeta_id):
    parent_id = _optional_int(request.form.get("padre_id"))
    try:
        folder = DocumentFolderService().move_folder(
            user=current_user,
            folder_id=carpeta_id,
            parent_id=parent_id,
            **workflow_request_metadata(),
        )
        db.session.commit()
        flash("Carpeta movida correctamente.", "success")
        return _redirect_to_explorer(folder.id)
    except DocumentFolderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return _redirect_to_explorer(carpeta_id)


@bp.route("/explorador/carpetas/<int:carpeta_id>/eliminar", methods=["POST"])
@login_required
def eliminar_carpeta(carpeta_id):
    parent_id = _optional_int(request.form.get("retorno_padre_id"))
    try:
        DocumentFolderService().deactivate_folder(
            user=current_user,
            folder_id=carpeta_id,
            **workflow_request_metadata(),
        )
        db.session.commit()
        flash("Carpeta eliminada correctamente.", "success")
        return _redirect_to_explorer(parent_id)
    except DocumentFolderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return _redirect_to_explorer(carpeta_id)


@bp.route("/explorador/documentos/<int:item_id>/mover", methods=["POST"])
@login_required
def mover_documento_carpeta(item_id):
    folder_id = _optional_int(request.form.get("carpeta_id"))
    current_folder_id = _optional_int(request.form.get("retorno_carpeta_id"))
    uncategorized = request.form.get("retorno_sin_clasificar") == "1"
    try:
        DocumentFolderService().assign_document(
            user=current_user,
            document_id=item_id,
            folder_id=folder_id,
            **workflow_request_metadata(),
        )
        db.session.commit()
        flash("Documento movido correctamente.", "success")
    except DocumentFolderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _redirect_to_explorer(current_folder_id, uncategorized=uncategorized)


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
        elaborado_por_id = request.form.get("elaborado_por_id")
        revisado_por_id = request.form.get("revisado_por_id")
        aprobado_por_id = request.form.get("aprobado_por_id")
        form_data = request.form
        cambios = request.form.get("cambios", "").strip() or "Versión inicial del documento"

        archivo = request.files.get("archivo")
        try:
            validate_document_file(archivo)
            if _archivo_principal_es_anexo_excel(archivo):
                raise DocumentStorageError("Los XLSX se cargan como anexos de una version DOCX, no como documento principal.")
        except DocumentStorageError as exc:
            flash(str(exc), "danger")
            return render_template(
                "documentacion/form.html",
                **_document_form_context(form_data=form_data),
            )

        if not codigo or not titulo or not tipo_documento or not version:
            flash("Código, título, tipo de documento y versión son obligatorios.", "danger")
            return render_template(
                "documentacion/form.html",
                **_document_form_context(form_data=form_data),
            )

        existente = Documento.query.filter_by(
            empresa_id=current_user.empresa_id,
            codigo=codigo
        ).first()

        if existente:
            flash("Ya existe un documento con ese código.", "danger")
            return render_template(
                "documentacion/form.html",
                **_document_form_context(form_data=form_data),
            )

        stored_file = None
        try:
            responsables = validate_document_responsibles(
                empresa_id=current_user.empresa_id,
                elaborado_por_id=elaborado_por_id,
                revisado_por_id=revisado_por_id,
                aprobado_por_id=aprobado_por_id,
            )
            documento = Documento(
                empresa_id=current_user.empresa_id,
                codigo=codigo,
                titulo=titulo,
                tipo_documento=tipo_documento,
                proceso=proceso or None,
                estado="EN_ELABORACION",
                version_actual=version,
                elaborado_por_id=responsables["elaborado_por_id"],
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
                elaborado_por_id=responsables["elaborado_por_id"],
                revisado_por_id=responsables["revisado_por_id"],
                aprobado_por_id=responsables["aprobado_por_id"],
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
                **_document_form_context(form_data=form_data),
            )
        except Exception:
            db.session.rollback()
            delete_document_file(stored_file.storage_path if stored_file else None)
            current_app.logger.exception("No se pudo crear el documento")
            flash("No se pudo guardar el documento. Inténtalo nuevamente.", "danger")
            return render_template(
                "documentacion/form.html",
                **_document_form_context(form_data=form_data),
            )

        flash("Documento creado correctamente.", "success")
        return redirect(url_for("documentacion.detalle", item_id=documento.id))

    return render_template(
        "documentacion/form.html",
        **_document_form_context(),
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
    snapshots = DocumentSnapshotService().list_snapshots(documento=item) if can_view_history else []
    anexos_version_mostrada = list_active_attachments(version_mostrada) if version_mostrada else []
    pdf_service = DocumentPdfService()
    pdf_artifact = pdf_service.available_artifact_for_version(version_vigente) if version_vigente else None
    pdf_conversion = pdf_service.latest_conversion_for_version(version_vigente) if version_vigente else None
    signature_service = DocumentSignatureService()
    signature_process = signature_service.latest_process_for_version(version_vigente) if version_vigente else None
    signature_identity_statuses = (
        signature_service.required_identity_statuses(version_vigente)
        if version_vigente
        else []
    )
    missing_signature_identities = [
        status for status in signature_identity_statuses if not status["verified"]
    ]
    signature_process_blocks_start = bool(
        signature_process
        and signature_process.estado in (
            FIRMA_PROCESO_PENDIENTE,
            FIRMA_PROCESO_EN_FIRMA,
            FIRMA_PROCESO_COMPLETADO,
        )
    )
    can_start_signature = bool(
        signature_service.signatures_enabled()
        and version_vigente
        and item.estado == "APROBADO"
        and version_vigente.estado == "APROBADO"
        and pdf_artifact
        and pdf_artifact.estado == "DISPONIBLE"
        and not signature_process_blocks_start
        and not missing_signature_identities
        and current_user_can(START_SIGNATURE_PERMISSION)
    )
    signature_enabled_step = None
    if signature_process:
        signature_enabled_step = (
            DocumentoFirmaPaso.query
            .filter_by(
                empresa_id=current_user.empresa_id,
                proceso_id=signature_process.id,
                usuario_id=current_user.id,
                estado=FIRMA_PASO_HABILITADO,
            )
            .first()
        )
    dev_signature_available = False
    dev_signature_csrf_token = None
    dev_signature_preview_available = bool(
        dev_signature_mode_enabled(current_app)
        and pdf_artifact
        and pdf_artifact.estado == "DISPONIBLE"
    )
    if signature_enabled_step and dev_signature_mode_enabled(current_app):
        try:
            dev_signature_available = bool(
                DocumentSignatureDevCertificateService(current_app).certificate_for_user(current_user)
            )
        except DocumentSignatureDevError:
            dev_signature_available = False
        if dev_signature_available:
            dev_signature_csrf_token = _issue_dev_signature_csrf_token(signature_enabled_step.public_id)

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
        is_onlyoffice_supported_version=is_onlyoffice_supported_version,
        can_user_edit_onlyoffice_version=can_user_edit_onlyoffice_version,
        active_edit_info=active_edit_info,
        anexos_version_mostrada=anexos_version_mostrada,
        can_user_edit_attachment=can_user_edit_attachment,
        snapshots=snapshots,
        pdf_artifact=pdf_artifact,
        pdf_conversion=pdf_conversion,
        signatures_enabled=signature_service.signatures_enabled(),
        signature_process=signature_process,
        signature_enabled_step=signature_enabled_step,
        dev_signature_available=dev_signature_available,
        dev_signature_csrf_token=dev_signature_csrf_token,
        dev_signature_preview_available=dev_signature_preview_available,
        signature_identity_statuses=signature_identity_statuses,
        missing_signature_identities=missing_signature_identities,
        can_start_signature=can_start_signature,
        start_signature_permission=START_SIGNATURE_PERMISSION,
        manage_signature_identity_permission=SIGNATURE_IDENTITY_PERMISSION,
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
        source = DocumentSnapshotService().official_source_for_version(
            documento=version_doc.documento,
            version_doc=version_doc,
        )
        if source.kind == "snapshot":
            physical_path = DocumentSnapshotService().resolve_snapshot_path(source.snapshot)
            if not physical_path or not os.path.isfile(physical_path):
                abort(404)
            return send_file(
                physical_path,
                as_attachment=request.args.get("inline") != "1",
                download_name=source.filename,
                mimetype=source.mime_type or None,
                conditional=True,
            )
    except DocumentSnapshotError:
        current_app.logger.warning("Snapshot documental invalido para la version %s", version_doc.id)
        abort(404)

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


def _load_document_version_for_attachment(item_id, version_id):
    item = Documento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first_or_404()
    version = DocumentoVersion.query.filter_by(
        id=version_id,
        documento_id=item.id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    return item, version


def _load_attachment(public_id):
    return DocumentoVersionAnexo.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()


@bp.route("/<int:item_id>/versiones/<int:version_id>/anexos", methods=["POST"])
@login_required
@require_permission("documentos.editar")
def agregar_anexo(item_id, version_id):
    item, version = _load_document_version_for_attachment(item_id, version_id)
    try:
        DocumentAttachmentService().add_attachment(
            documento=item,
            version_doc=version,
            usuario=current_user,
            file_storage=request.files.get("anexo"),
        )
        db.session.commit()
    except DocumentAttachmentError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except DocumentStorageError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/anexos/<public_id>/reemplazar", methods=["POST"])
@login_required
@require_permission("documentos.editar")
def reemplazar_anexo(public_id):
    anexo = _load_attachment(public_id)
    try:
        DocumentAttachmentService().replace_attachment(
            anexo=anexo,
            usuario=current_user,
            file_storage=request.files.get("anexo"),
        )
        db.session.commit()
        flash("Anexo reemplazado correctamente.", "success")
    except DocumentAttachmentError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except DocumentStorageError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("documentacion.detalle", item_id=anexo.documento_id))


@bp.route("/anexos/<public_id>/eliminar", methods=["POST"])
@login_required
@require_permission("documentos.editar")
def eliminar_anexo(public_id):
    anexo = _load_attachment(public_id)
    try:
        DocumentAttachmentService().delete_attachment(anexo=anexo, usuario=current_user)
        db.session.commit()
        flash("Anexo eliminado de la version de trabajo.", "success")
    except DocumentAttachmentError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("documentacion.detalle", item_id=anexo.documento_id))


@bp.route("/anexos/<public_id>/descargar")
@login_required
@require_permission("documentos.descargar")
def descargar_anexo(public_id):
    anexo = _load_attachment(public_id)
    try:
        physical_path = DocumentAttachmentService().resolve_attachment_path(anexo)
    except DocumentStorageError:
        abort(404)
    return send_file(
        physical_path,
        as_attachment=True,
        download_name=anexo.archivo_nombre_original,
        mimetype=anexo.archivo_mime,
        conditional=True,
    )


@bp.route("/anexos/<public_id>/onlyoffice/ver")
@login_required
@require_permission("documentos.ver")
def ver_anexo_onlyoffice(public_id):
    try:
        context = DocumentAttachmentService().build_view_context(public_id=public_id, user=current_user)
    except LookupError:
        abort(404)
    except (DocumentStorageError, OnlyOfficeDocumentViewError) as exc:
        abort(getattr(exc, "status_code", 422), description=str(exc))
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


@bp.route("/anexos/<public_id>/onlyoffice/editar")
@login_required
@require_permission("documentos.editar")
def editar_anexo_onlyoffice(public_id):
    try:
        context = DocumentAttachmentService().build_edit_context(public_id=public_id, user=current_user)
    except LookupError:
        abort(404)
    except OnlyOfficeEditConflictError as exc:
        flash(str(exc), "warning")
        return redirect(request.referrer or url_for("documentacion.index"))
    except (DocumentStorageError, OnlyOfficeEditError, OnlyOfficeDocumentViewError) as exc:
        abort(getattr(exc, "status_code", 422), description=str(exc))
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
        elaborado_por_id = request.form.get("elaborado_por_id")
        revisado_por_id = request.form.get("revisado_por_id")
        aprobado_por_id = request.form.get("aprobado_por_id")
        form_data = request.form

        archivo = request.files.get("archivo")
        try:
            validate_document_file(archivo)
            if _archivo_principal_es_anexo_excel(archivo):
                raise DocumentStorageError("Los XLSX se cargan como anexos de una version DOCX, no como documento principal.")
        except DocumentStorageError as exc:
            flash(str(exc), "danger")
            return render_template(
                "documentacion/version_form.html",
                **_version_form_context(item, form_data=form_data),
            )

        if not version or not cambios:
            flash("La versión y la descripción de cambios son obligatorias.", "danger")
            return render_template(
                "documentacion/version_form.html",
                **_version_form_context(item, form_data=form_data),
            )

        stored_file = None
        try:
            responsables = validate_document_responsibles(
                empresa_id=current_user.empresa_id,
                elaborado_por_id=elaborado_por_id,
                revisado_por_id=revisado_por_id,
                aprobado_por_id=aprobado_por_id,
            )
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
                elaborado_por_id=responsables["elaborado_por_id"],
                revisado_por_id=responsables["revisado_por_id"],
                aprobado_por_id=responsables["aprobado_por_id"],
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
                **_version_form_context(item, form_data=form_data),
            )
        except Exception:
            db.session.rollback()
            delete_document_file(stored_file.storage_path if stored_file else None)
            current_app.logger.exception("No se pudo crear la versión documental")
            flash("No se pudo guardar la versión. Inténtalo nuevamente.", "danger")
            return render_template(
                "documentacion/version_form.html",
                **_version_form_context(item, form_data=form_data),
            )

        flash("Nueva versión registrada correctamente.", "success")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    return render_template(
        "documentacion/version_form.html",
        **_version_form_context(item),
    )


@bp.route("/<int:item_id>/versiones/<int:version_id>/dar-conformidad", methods=["POST"])
@login_required
@require_permission("documentos.revisar")
def dar_conformidad_revision(item_id, version_id):
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
        mark_review_conformity(
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

    flash("Conformidad de revision registrada. El documento paso a aprobacion.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/versiones/<int:version_id>/solicitar-correcciones", methods=["POST"])
@login_required
@require_permission("documentos.revisar")
def solicitar_correcciones_revision(item_id, version_id):
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
        request_review_corrections(
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

    flash("Correcciones solicitadas. La version queda pendiente de devolucion a elaboracion.", "warning")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


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

    conversion_message = None
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

    try:
        artifact = DocumentPdfService().ensure_conversion_for_approved_version(
            documento=item,
            version_doc=version,
            usuario=current_user,
            start=True,
        )
        if artifact and artifact.estado == "DISPONIBLE":
            conversion_message = " PDF aprobado sin firmas generado correctamente."
        elif artifact:
            conversion_message = " La conversión PDF quedó en proceso o requiere revisión."
    except DocumentPdfError as exc:
        current_app.logger.warning("Conversion PDF posterior a aprobacion fallida: %s", exc)
        conversion_message = " La aprobación se mantuvo, pero la conversión PDF no pudo completarse."

    if conversion_message:
        flash(conversion_message.strip(), "info")

    flash("Versión aprobada correctamente.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/<int:item_id>/versiones/<int:version_id>/pdf-aprobado/ver")
@login_required
@require_permission("documentos.ver")
def ver_pdf_aprobado(item_id, version_id):
    item = Documento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first_or_404()
    version = DocumentoVersion.query.filter_by(
        id=version_id,
        documento_id=item.id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    artifact = DocumentPdfService().available_artifact_for_version(version)
    if not artifact or artifact.documento_id != item.id or artifact.empresa_id != current_user.empresa_id:
        abort(404)
    try:
        physical_path = DocumentPdfService().validate_artifact_file(artifact)
    except DocumentPdfError:
        abort(404)
    filename = artifact.archivo_nombre_visible or "pdf-aprobado-sin-firmas.pdf"
    response = send_file(
        physical_path,
        as_attachment=False,
        download_name=filename,
        mimetype="application/pdf",
        conditional=True,
    )
    response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; frame-ancestors 'self'; base-uri 'self'"
    )
    return response


@bp.route("/<int:item_id>/versiones/<int:version_id>/pdf-aprobado/descargar")
@login_required
@require_permission("documentos.descargar")
def descargar_pdf_aprobado(item_id, version_id):
    item = Documento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first_or_404()
    version = DocumentoVersion.query.filter_by(
        id=version_id,
        documento_id=item.id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    artifact = DocumentPdfService().available_artifact_for_version(version)
    if not artifact or artifact.documento_id != item.id or artifact.empresa_id != current_user.empresa_id:
        abort(404)
    try:
        physical_path = DocumentPdfService().validate_artifact_file(artifact)
    except DocumentPdfError:
        abort(404)
    return send_file(
        physical_path,
        as_attachment=True,
        download_name=artifact.archivo_nombre_visible or "pdf-aprobado-sin-firmas.pdf",
        mimetype="application/pdf",
        conditional=True,
    )


@bp.route("/<int:item_id>/firmas-dev/vista-previa")
@login_required
@require_permission("documentos.ver")
def vista_previa_firmas_dev(item_id):
    if not dev_signature_mode_enabled(current_app):
        abort(404)
    item = Documento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first_or_404()
    version = item.version_vigente
    if not version:
        abort(404)
    artifact = DocumentPdfService().available_artifact_for_version(version)
    if not artifact or artifact.documento_id != item.id or artifact.empresa_id != current_user.empresa_id:
        abort(404)
    try:
        physical_path = DocumentPdfService().validate_artifact_file(artifact)
        preview_path = DocumentSignatureDevCertificateService(current_app).preview_signature_locations(
            physical_path,
            documento=item,
        )
    except (DocumentPdfError, DocumentSignatureDevError):
        abort(404)

    response = send_file(
        preview_path,
        as_attachment=True,
        download_name=f"{item.codigo}-vista-previa-firmas-dev.pdf",
        mimetype="application/pdf",
        conditional=False,
    )
    response.call_on_close(lambda: preview_path.unlink(missing_ok=True))
    return response


@bp.route("/<int:item_id>/versiones/<int:version_id>/firmas/iniciar", methods=["POST"])
@login_required
@require_permission(START_SIGNATURE_PERMISSION)
def iniciar_firma_digital(item_id, version_id):
    item = Documento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first_or_404()
    version = DocumentoVersion.query.filter_by(
        id=version_id,
        documento_id=item.id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    try:
        DocumentSignatureService().start_process(
            documento=item,
            version_doc=version,
            usuario=current_user,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
    except DocumentSignatureError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=item.id))
    flash("Proceso de firma digital externa iniciado. El documento permanece APROBADO.", "success")
    return redirect(url_for("documentacion.detalle", item_id=item.id))


@bp.route("/firmas/pasos/<public_id>/descargar")
@login_required
@require_permission("documentos.ver")
def descargar_pdf_para_firma(public_id):
    paso = DocumentoFirmaPaso.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    try:
        artifact, physical_path = DocumentSignatureService().downloadable_artifact_for_step(
            paso=paso,
            usuario=current_user,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
    except DocumentSignatureError:
        abort(403)
    return send_file(
        physical_path,
        as_attachment=True,
        download_name=artifact.archivo_nombre_visible or "documento-para-firma.pdf",
        mimetype="application/pdf",
        conditional=True,
    )


@bp.route("/firmas/pasos/<public_id>/subir", methods=["POST"])
@login_required
@require_permission("documentos.ver")
def subir_pdf_firmado(public_id):
    paso = DocumentoFirmaPaso.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    try:
        DocumentSignatureService().upload_signed_pdf(
            paso=paso,
            usuario=current_user,
            file_storage=request.files.get("pdf_firmado"),
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
    except DocumentSignatureError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=paso.documento_id))
    flash("PDF firmado validado y conservado como artefacto privado e inmutable.", "success")
    return redirect(url_for("documentacion.detalle", item_id=paso.documento_id))


@bp.route("/firmas/pasos/<public_id>/firmar-dev", methods=["POST"])
@login_required
@require_permission("documentos.ver")
def firmar_pdf_dev(public_id):
    if not dev_signature_mode_enabled(current_app):
        abort(404)
    paso = DocumentoFirmaPaso.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    if not _validate_dev_signature_csrf_token(public_id):
        abort(403)
    current_user_id = int(session.get("_user_id") or current_user.get_id())
    if (
        int(paso.usuario_id) != current_user_id
        or paso.estado != FIRMA_PASO_HABILITADO
        or paso.proceso.estado != FIRMA_PROCESO_EN_FIRMA
    ):
        abort(403)
    try:
        DocumentSignatureService().sign_step_with_dev_certificate(
            paso=paso,
            usuario=current_user,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
    except DocumentSignatureError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=paso.documento_id))
    flash("Firma PAdES de desarrollo generada y validada con pyHanko.", "success")
    return redirect(url_for("documentacion.detalle", item_id=paso.documento_id))


@bp.route("/firmas/pasos/<public_id>/rechazar", methods=["POST"])
@login_required
@require_permission("documentos.ver")
def rechazar_paso_firma(public_id):
    paso = DocumentoFirmaPaso.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    try:
        DocumentSignatureService().reject_step(
            paso=paso,
            usuario=current_user,
            comentario=request.form.get("comentario", ""),
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
    except DocumentSignatureError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=paso.documento_id))
    flash("Paso de firma rechazado. El documento permanece APROBADO.", "warning")
    return redirect(url_for("documentacion.detalle", item_id=paso.documento_id))


@bp.route("/firmas/procesos/<public_id>/pdf-final/descargar")
@login_required
@require_permission("documentos.ver")
def descargar_pdf_firmado_final(public_id):
    proceso = DocumentoFirmaProceso.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    artifact = proceso.pdf_final
    if not artifact or artifact.empresa_id != current_user.empresa_id or artifact.documento_id != proceso.documento_id:
        abort(404)
    try:
        physical_path = resolve_document_path(artifact.storage_path)
        result = DocumentPdfService().validate_pdf_file(physical_path, allow_signature_forms=True)
        if result.sha256 != artifact.archivo_sha256 or int(result.size) != int(artifact.archivo_size or 0):
            abort(404)
    except (DocumentStorageError, DocumentPdfError):
        abort(404)
    return send_file(
        physical_path,
        as_attachment=True,
        download_name=artifact.archivo_nombre_visible or "pdf-final-firmado.pdf",
        mimetype="application/pdf",
        conditional=True,
    )


@bp.route("/firmas/procesos/<public_id>/cancelar", methods=["POST"])
@login_required
@require_permission(START_SIGNATURE_PERMISSION)
def cancelar_proceso_firma(public_id):
    proceso = DocumentoFirmaProceso.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    try:
        DocumentSignatureService().cancel_process(
            proceso=proceso,
            usuario=current_user,
            comentario=request.form.get("comentario", ""),
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
    except DocumentSignatureError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=proceso.documento_id))
    flash("Proceso de firma cancelado. El documento permanece APROBADO.", "warning")
    return redirect(url_for("documentacion.detalle", item_id=proceso.documento_id))


@bp.route("/conversiones/<public_id>/actualizar", methods=["POST"])
@login_required
@require_permission("documentos.aprobar")
def actualizar_conversion(public_id):
    from app.models.documentos import DocumentoConversion

    conversion = DocumentoConversion.query.filter_by(
        public_id=public_id,
        empresa_id=current_user.empresa_id,
    ).first_or_404()
    try:
        if conversion.estado == "ERROR":
            DocumentPdfService().retry_conversion(conversion_public_id=public_id, usuario=current_user)
        else:
            DocumentPdfService().process_conversion(conversion=conversion)
    except DocumentPdfError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documentacion.detalle", item_id=conversion.documento_id))
    flash("Conversión PDF actualizada.", "success")
    return redirect(url_for("documentacion.detalle", item_id=conversion.documento_id))


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
            resumen_cambios=request.form.get("resumen_cambios") or request.form.get("comentario", ""),
            hojas_modificadas=request.form.get("hojas_modificadas") or "No aplica",
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
