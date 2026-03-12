from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion

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

ESTADOS_DOCUMENTO = [
    "borrador",
    "vigente",
    "obsoleto",
    "archivado",
]


@bp.route("/")
@login_required
def index():
    tipo = request.args.get("tipo", "").strip()
    estado = request.args.get("estado", "").strip()
    q = request.args.get("q", "").strip()

    query = Documento.query.filter_by(empresa_id=current_user.empresa_id)

    # Gestión documental: excluye registros y archivados por defecto
    query = query.filter(Documento.tipo_documento != "REGISTRO")

    if tipo:
        query = query.filter(Documento.tipo_documento == tipo)

    if estado:
        query = query.filter(Documento.estado == estado)
    else:
        query = query.filter(Documento.estado != "archivado")

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
    query = query.filter(Documento.estado.in_(["obsoleto", "archivado"]))

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
        version = request.form.get("version", "").strip()
        estado = request.form.get("estado", "borrador").strip()
        contenido = request.form.get("contenido", "").strip()
        archivo_url = request.form.get("archivo_url", "").strip()
        cambios = request.form.get("cambios", "").strip()

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

        documento = Documento(
            empresa_id=current_user.empresa_id,
            codigo=codigo,
            titulo=titulo,
            tipo_documento=tipo_documento,
            proceso=proceso,
            estado=estado,
            version_actual=version,
            elaborado_por_id=current_user.id,
        )
        db.session.add(documento)
        db.session.flush()

        version_doc = DocumentoVersion(
            empresa_id=current_user.empresa_id,
            documento_id=documento.id,
            version=version,
            archivo_url=archivo_url or None,
            contenido=contenido,
            fecha_version=date.today(),
            cambios=cambios,
            elaborado_por_id=current_user.id,
            estado=estado,
        )
        db.session.add(version_doc)
        db.session.commit()

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

    version_actual = None
    if item.version_actual:
        version_actual = (
            DocumentoVersion.query
            .filter_by(
                documento_id=item.id,
                empresa_id=current_user.empresa_id,
                version=item.version_actual
            )
            .first()
        )

    return render_template(
        "documentacion/detalle.html",
        item=item,
        versiones=versiones,
        version_actual=version_actual,
    )


@bp.route("/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar(item_id):
    item = Documento.query.filter_by(
        id=item_id,
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if request.method == "POST":
        item.codigo = request.form.get("codigo", "").strip().upper()
        item.titulo = request.form.get("titulo", "").strip()
        item.tipo_documento = request.form.get("tipo_documento", "").strip()
        item.proceso = request.form.get("proceso", "").strip()
        item.estado = request.form.get("estado", "borrador").strip()

        if not item.codigo or not item.titulo or not item.tipo_documento:
            flash("Código, título y tipo de documento son obligatorios.", "danger")
            return render_template(
                "documentacion/form.html",
                item=item,
                version_item=None,
                tipos_documento=TIPOS_DOCUMENTO,
                estados_documento=ESTADOS_DOCUMENTO,
            )

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
        estado = request.form.get("estado", item.estado).strip()
        contenido = request.form.get("contenido", "").strip()
        archivo_url = request.form.get("archivo_url", "").strip()
        cambios = request.form.get("cambios", "").strip()

        if not version:
            flash("La versión es obligatoria.", "danger")
            return render_template(
                "documentacion/version_form.html",
                item=item,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        existente = DocumentoVersion.query.filter_by(
            empresa_id=current_user.empresa_id,
            documento_id=item.id,
            version=version
        ).first()

        if existente:
            flash("Ya existe esa versión para este documento.", "danger")
            return render_template(
                "documentacion/version_form.html",
                item=item,
                estados_documento=ESTADOS_DOCUMENTO,
            )

        nueva = DocumentoVersion(
            empresa_id=current_user.empresa_id,
            documento_id=item.id,
            version=version,
            archivo_url=archivo_url or None,
            contenido=contenido,
            fecha_version=date.today(),
            cambios=cambios,
            elaborado_por_id=current_user.id,
            estado=estado,
        )
        db.session.add(nueva)

        item.version_actual = version
        item.estado = estado

        db.session.commit()

        flash("Nueva versión registrada correctamente.", "success")
        return redirect(url_for("documentacion.detalle", item_id=item.id))

    return render_template(
        "documentacion/version_form.html",
        item=item,
        estados_documento=ESTADOS_DOCUMENTO,
    )