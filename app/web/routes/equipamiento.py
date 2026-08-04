from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.equipos import (
    AreaAmbiente,
    CRITICIDADES_EQUIPO,
    Equipo,
    ESTADOS_OPERATIVOS_EQUIPO,
    Instalacion,
)
from app.security.permissions import require_permission
from app.services.equipamiento_service import (
    EquipamientoError,
    active_areas,
    active_instalaciones,
    change_equipo_status,
    create_area,
    create_equipo,
    create_instalacion,
    get_area,
    get_equipo,
    get_instalacion,
    link_document_version,
    update_area,
    update_equipo,
    update_instalacion,
)

bp = Blueprint("equipamiento", __name__, url_prefix="/equipamiento")


def _estado_filter(query, model, estado):
    if estado == "activos":
        return query.filter(model.estado == "activo")
    if estado == "inactivos":
        return query.filter(model.estado == "inactivo")
    return query


@bp.route("/")
@login_required
@require_permission("equipamiento.dashboard.ver")
def dashboard():
    empresa_id = current_user.empresa_id
    active_installations = Instalacion.query.filter_by(empresa_id=empresa_id, estado="activo").count()
    active_areas_count = AreaAmbiente.query.filter_by(empresa_id=empresa_id, estado="activo").count()
    active_equipment = Equipo.query.filter_by(empresa_id=empresa_id, estado="activo").count()
    status_counts = {
        status: Equipo.query.filter_by(empresa_id=empresa_id, estado_operativo=status).count()
        for status in ESTADOS_OPERATIVOS_EQUIPO
    }
    high_criticality = Equipo.query.filter_by(empresa_id=empresa_id, criticidad="ALTA").count()
    return render_template(
        "equipamiento/dashboard.html",
        stats={
            "instalaciones_activas": active_installations,
            "areas_activas": active_areas_count,
            "equipos_activos": active_equipment,
            "estado_operativo": status_counts,
            "criticidad_alta": high_criticality,
        },
    )


@bp.route("/instalaciones")
@login_required
@require_permission("instalaciones.ver")
def instalaciones():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "activos").strip()
    query = Instalacion.query.filter_by(empresa_id=current_user.empresa_id)
    query = _estado_filter(query, Instalacion, estado)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Instalacion.codigo.ilike(like), Instalacion.nombre.ilike(like), Instalacion.responsable.ilike(like)))
    items = query.order_by(Instalacion.codigo.asc()).all()
    return render_template("equipamiento/instalaciones_index.html", items=items, q=q, estado=estado)


@bp.route("/instalaciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission("instalaciones.crear")
def nueva_instalacion():
    if request.method == "POST":
        try:
            item = create_instalacion(current_user, request.form)
            db.session.commit()
            flash("Instalacion creada correctamente.", "success")
            return redirect(url_for("equipamiento.instalaciones"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/instalacion_form.html", item=None, form_data=request.form)
    return render_template("equipamiento/instalacion_form.html", item=None, form_data={})


@bp.route("/instalaciones/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission("instalaciones.editar")
def editar_instalacion(item_id):
    item = get_instalacion(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        try:
            update_instalacion(current_user, item, request.form)
            db.session.commit()
            flash("Instalacion actualizada correctamente.", "success")
            return redirect(url_for("equipamiento.instalaciones"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/instalacion_form.html", item=item, form_data=request.form)
    return render_template("equipamiento/instalacion_form.html", item=item, form_data={})


@bp.route("/instalaciones/<int:item_id>/inactivar", methods=["POST"])
@login_required
@require_permission("instalaciones.inactivar")
def inactivar_instalacion(item_id):
    item = get_instalacion(current_user, item_id)
    if not item:
        abort(404)
    item.estado = "inactivo"
    db.session.commit()
    flash("Instalacion inactivada correctamente.", "warning")
    return redirect(url_for("equipamiento.instalaciones"))


@bp.route("/areas")
@login_required
@require_permission("areas.ver")
def areas():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "activos").strip()
    instalacion_id = request.args.get("instalacion_id", "").strip()
    query = AreaAmbiente.query.filter_by(empresa_id=current_user.empresa_id)
    query = _estado_filter(query, AreaAmbiente, estado)
    if instalacion_id:
        query = query.filter(AreaAmbiente.instalacion_id == int(instalacion_id))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(AreaAmbiente.codigo.ilike(like), AreaAmbiente.nombre.ilike(like), AreaAmbiente.tipo.ilike(like), AreaAmbiente.responsable.ilike(like)))
    items = query.order_by(AreaAmbiente.codigo.asc()).all()
    return render_template(
        "equipamiento/areas_index.html",
        items=items,
        q=q,
        estado=estado,
        instalacion_id=instalacion_id,
        instalaciones=active_instalaciones(current_user),
    )


@bp.route("/areas/nueva", methods=["GET", "POST"])
@login_required
@require_permission("areas.crear")
def nueva_area():
    if request.method == "POST":
        try:
            create_area(current_user, request.form)
            db.session.commit()
            flash("Area o ambiente creado correctamente.", "success")
            return redirect(url_for("equipamiento.areas"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/area_form.html", item=None, form_data=request.form, instalaciones=active_instalaciones(current_user))
    return render_template("equipamiento/area_form.html", item=None, form_data={}, instalaciones=active_instalaciones(current_user))


@bp.route("/areas/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission("areas.editar")
def editar_area(item_id):
    item = get_area(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        try:
            update_area(current_user, item, request.form)
            db.session.commit()
            flash("Area o ambiente actualizado correctamente.", "success")
            return redirect(url_for("equipamiento.areas"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/area_form.html", item=item, form_data=request.form, instalaciones=active_instalaciones(current_user))
    return render_template("equipamiento/area_form.html", item=item, form_data={}, instalaciones=active_instalaciones(current_user))


@bp.route("/areas/<int:item_id>/inactivar", methods=["POST"])
@login_required
@require_permission("areas.inactivar")
def inactivar_area(item_id):
    item = get_area(current_user, item_id)
    if not item:
        abort(404)
    item.estado = "inactivo"
    db.session.commit()
    flash("Area o ambiente inactivado correctamente.", "warning")
    return redirect(url_for("equipamiento.areas"))


@bp.route("/equipos")
@login_required
@require_permission("equipos.ver")
def equipos():
    filters = {key: request.args.get(key, "").strip() for key in (
        "q", "codigo", "nombre", "instalacion_id", "area_ambiente_id", "estado_operativo",
        "criticidad", "responsable", "estado", "requiere_calibracion", "requiere_mantenimiento",
    )}
    query = Equipo.query.filter_by(empresa_id=current_user.empresa_id)
    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.filter(or_(Equipo.codigo.ilike(like), Equipo.nombre.ilike(like), Equipo.marca.ilike(like), Equipo.modelo.ilike(like), Equipo.serie.ilike(like)))
    if filters["codigo"]:
        query = query.filter(Equipo.codigo.ilike(f"%{filters['codigo']}%"))
    if filters["nombre"]:
        query = query.filter(Equipo.nombre.ilike(f"%{filters['nombre']}%"))
    if filters["instalacion_id"]:
        query = query.filter(Equipo.instalacion_id == int(filters["instalacion_id"]))
    if filters["area_ambiente_id"]:
        query = query.filter(Equipo.area_ambiente_id == int(filters["area_ambiente_id"]))
    if filters["estado_operativo"]:
        query = query.filter(Equipo.estado_operativo == filters["estado_operativo"])
    if filters["criticidad"]:
        query = query.filter(Equipo.criticidad == filters["criticidad"])
    if filters["responsable"]:
        query = query.filter(Equipo.responsable.ilike(f"%{filters['responsable']}%"))
    if filters["estado"] in {"activo", "inactivo"}:
        query = query.filter(Equipo.estado == filters["estado"])
    if filters["requiere_calibracion"] in {"1", "0"}:
        query = query.filter(Equipo.requiere_calibracion == (filters["requiere_calibracion"] == "1"))
    if filters["requiere_mantenimiento"] in {"1", "0"}:
        query = query.filter(Equipo.requiere_mantenimiento == (filters["requiere_mantenimiento"] == "1"))
    items = query.order_by(Equipo.codigo.asc()).all()
    return render_template(
        "equipamiento/equipos_index.html",
        items=items,
        filters=filters,
        instalaciones=active_instalaciones(current_user),
        areas=active_areas(current_user),
        estados_operativos=ESTADOS_OPERATIVOS_EQUIPO,
        criticidades=CRITICIDADES_EQUIPO,
    )


def _equipo_form_context(item=None, form_data=None):
    return {
        "item": item,
        "form_data": form_data or {},
        "instalaciones": active_instalaciones(current_user),
        "areas": active_areas(current_user),
        "estados_operativos": ESTADOS_OPERATIVOS_EQUIPO,
        "criticidades": CRITICIDADES_EQUIPO,
    }


@bp.route("/equipos/nuevo", methods=["GET", "POST"])
@login_required
@require_permission("equipos.crear")
def nuevo_equipo():
    if request.method == "POST":
        try:
            item = create_equipo(current_user, request.form)
            db.session.commit()
            flash("Equipo creado correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_equipo", item_id=item.id))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/equipo_form.html", **_equipo_form_context(form_data=request.form))
    return render_template("equipamiento/equipo_form.html", **_equipo_form_context())


@bp.route("/equipos/<int:item_id>")
@login_required
@require_permission("equipos.ver")
def detalle_equipo(item_id):
    item = get_equipo(current_user, item_id)
    if not item:
        abort(404)
    document_versions = (
        DocumentoVersion.query
        .join(Documento, Documento.id == DocumentoVersion.documento_id)
        .filter(DocumentoVersion.empresa_id == current_user.empresa_id)
        .order_by(Documento.codigo.asc(), DocumentoVersion.version.asc())
        .all()
    )
    return render_template(
        "equipamiento/equipo_detalle.html",
        item=item,
        estados_operativos=ESTADOS_OPERATIVOS_EQUIPO,
        document_versions=document_versions,
    )


@bp.route("/equipos/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission("equipos.editar")
def editar_equipo(item_id):
    item = get_equipo(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        try:
            update_equipo(current_user, item, request.form)
            db.session.commit()
            flash("Equipo actualizado correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_equipo", item_id=item.id))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/equipo_form.html", **_equipo_form_context(item=item, form_data=request.form))
    return render_template("equipamiento/equipo_form.html", **_equipo_form_context(item=item))


@bp.route("/equipos/<int:item_id>/estado", methods=["POST"])
@login_required
@require_permission("equipos.cambiar_estado")
def cambiar_estado_equipo(item_id):
    item = get_equipo(current_user, item_id)
    if not item:
        abort(404)
    try:
        change_equipo_status(current_user, item, request.form.get("estado_operativo"), request.form.get("descripcion"))
        db.session.commit()
        flash("Estado operativo actualizado correctamente.", "success")
    except EquipamientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("equipamiento.detalle_equipo", item_id=item.id))


@bp.route("/equipos/<int:item_id>/inactivar", methods=["POST"])
@login_required
@require_permission("equipos.inactivar")
def inactivar_equipo(item_id):
    item = get_equipo(current_user, item_id)
    if not item:
        abort(404)
    item.estado = "inactivo"
    db.session.commit()
    flash("Equipo inactivado correctamente.", "warning")
    return redirect(url_for("equipamiento.detalle_equipo", item_id=item.id))


@bp.route("/equipos/<int:item_id>/documentos", methods=["POST"])
@login_required
@require_permission("equipos.documentos.vincular")
def vincular_documento_equipo(item_id):
    item = get_equipo(current_user, item_id)
    if not item:
        abort(404)
    try:
        link_document_version(
            current_user,
            item,
            request.form.get("documento_version_id"),
            request.form.get("tipo_documento"),
            request.form.get("observaciones"),
        )
        db.session.commit()
        flash("Documento vinculado al equipo correctamente.", "success")
    except EquipamientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("equipamiento.detalle_equipo", item_id=item.id))
