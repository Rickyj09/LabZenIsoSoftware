import secrets
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models.documentos import Documento, DocumentoVersion
from app.models.equipos import (
    AreaAmbiente,
    AreaCondicionAmbiental,
    AreaHistorialAmbiental,
    AreaMedicionAmbiental,
    CRITICIDADES_EQUIPO,
    Equipo,
    EquipoCalibracion,
    EquipoCalibracionDocumento,
    EquipoHistorial,
    EquipoMantenimiento,
    EquipoMantenimientoDocumento,
    EquipoPlanMantenimiento,
    ESTADOS_MATERIAL_REFERENCIA,
    ESTADOS_OPERATIVOS_EQUIPO,
    Instalacion,
    MaterialReferencia,
    MaterialReferenciaDocumento,
    MaterialReferenciaHistorial,
    TIPOS_EVIDENCIA_MATERIAL_REFERENCIA,
    TIPOS_MATERIAL_REFERENCIA,
)
from app.models.seguridad import Usuario
from app.security.permissions import current_user_can, require_permission
from app.services import area_condicion_ambiental_service as ambiente_service
from app.services import equipo_calibracion_service as calibracion_service
from app.services import equipo_mantenimiento_service as mantenimiento_service
from app.services import material_referencia_service as material_referencia_service
from app.services.equipo_calibracion_service import EquipoCalibracionError
from app.services.equipo_mantenimiento_service import EquipoMantenimientoError
from app.services.equipamiento_service import (
    EquipamientoError,
    active_areas,
    active_instalaciones,
    change_equipo_status,
    create_area,
    create_equipo,
    create_instalacion,
    equipo_history_change_labels,
    get_area,
    get_equipo,
    get_instalacion,
    link_document_version,
    update_area,
    update_equipo,
    update_instalacion,
)
from app.services.area_condicion_ambiental_service import CondicionAmbientalError
from app.services.material_referencia_service import MaterialReferenciaError

bp = Blueprint("equipamiento", __name__, url_prefix="/equipamiento")

MAINTENANCE_CSRF_SESSION_KEY = "equipamiento_mantenimiento_csrf"


def _maintenance_csrf_token():
    token = session.get(MAINTENANCE_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[MAINTENANCE_CSRF_SESSION_KEY] = token
    return token


def _validate_maintenance_csrf():
    expected = session.get(MAINTENANCE_CSRF_SESSION_KEY)
    provided = request.form.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, provided):
        abort(403)


def _maintenance_template_context(**extra):
    context = {
        "csrf_token": _maintenance_csrf_token(),
        "today": date.today(),
        "is_overdue": mantenimiento_service.esta_vencido,
        "estado_badge_class": _estado_mantenimiento_badge_class,
    }
    context.update(extra)
    return context


def _calibration_template_context(**extra):
    context = {
        "csrf_token": _maintenance_csrf_token(),
        "today": date.today(),
        "estado_badge_class": _estado_calibracion_badge_class,
    }
    context.update(extra)
    return context


def _environment_template_context(**extra):
    context = {
        "csrf_token": _maintenance_csrf_token(),
        "today": date.today(),
        "format_decimal": _format_decimal,
        "format_local_datetime": ambiente_service.format_local_datetime,
        "estado_ambiental_badge_class": _estado_ambiental_badge_class,
    }
    context.update(extra)
    return context


def _material_reference_template_context(**extra):
    context = {
        "csrf_token": _maintenance_csrf_token(),
        "today": date.today(),
        "format_decimal": _format_decimal,
        "format_local_datetime": ambiente_service.format_local_datetime,
        "esta_vencido": material_referencia_service.esta_vencido,
        "estado_material_badge_class": _estado_material_badge_class,
        "tipo_material_label": _tipo_material_label,
        "tipos_material_referencia": TIPOS_MATERIAL_REFERENCIA,
        "estados_material_referencia": ESTADOS_MATERIAL_REFERENCIA,
        "tipos_evidencia_material_referencia": TIPOS_EVIDENCIA_MATERIAL_REFERENCIA,
        "terminal_states": material_referencia_service.TERMINAL_STATES,
        "operative_states": material_referencia_service.OPERATIVE_STATES,
    }
    context.update(extra)
    return context


def _format_decimal(value):
    if value is None:
        return "-"
    text = format(value, "f") if hasattr(value, "as_tuple") else str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _estado_mantenimiento_badge_class(estado):
    return {
        "PROGRAMADO": "text-bg-primary",
        "EN_PROCESO": "text-bg-warning",
        "COMPLETADO": "text-bg-success",
        "CANCELADO": "text-bg-secondary",
    }.get(estado, "text-bg-light")


def _estado_calibracion_badge_class(estado):
    return {
        "PROGRAMADO": "text-bg-primary",
        "EN_PROCESO": "text-bg-warning",
        "COMPLETADO": "text-bg-success",
        "CANCELADO": "text-bg-secondary",
    }.get(estado, "text-bg-light")


def _estado_ambiental_badge_class(estado):
    return {
        "CONFORME": "text-bg-success",
        "FUERA_DE_LIMITE": "text-bg-danger",
    }.get(estado, "text-bg-light")


def _condicion_activa_badge_class(activa):
    return "text-bg-success" if activa else "text-bg-secondary"


def _estado_material_badge_class(estado):
    return {
        "DISPONIBLE": "text-bg-success",
        "EN_USO": "text-bg-primary",
        "AGOTADO": "text-bg-secondary",
        "VENCIDO": "text-bg-danger",
        "RETIRADO": "text-bg-dark",
    }.get(estado, "text-bg-light")


def _tipo_material_label(tipo):
    return {
        "MATERIAL_REFERENCIA": "Material de referencia",
        "PATRON_REFERENCIA": "Patron de referencia",
    }.get(tipo, tipo or "-")


CALIBRATION_HISTORY_EVENTS = (
    "CALIBRACION_PROGRAMADA",
    "VERIFICACION_PROGRAMADA",
    "CALIBRACION_INICIADA",
    "VERIFICACION_INICIADA",
    "CALIBRACION_COMPLETADA",
    "VERIFICACION_COMPLETADA",
    "CALIBRACION_CANCELADA",
    "VERIFICACION_CANCELADA",
    "EVIDENCIA_CALIBRACION_VINCULADA",
    "EVIDENCIA_CALIBRACION_DESVINCULADA",
)


def _active_equipment():
    return (
        Equipo.query
        .filter(
            Equipo.empresa_id == current_user.empresa_id,
            Equipo.estado == "activo",
            Equipo.estado_operativo != "RETIRADO",
        )
        .order_by(Equipo.codigo.asc())
        .all()
    )


def _active_users():
    return (
        Usuario.query
        .filter_by(empresa_id=current_user.empresa_id, activo=True)
        .order_by(Usuario.nombre.asc(), Usuario.apellido.asc())
        .all()
    )


def _documents_for_evidence():
    return (
        Documento.query
        .filter(Documento.empresa_id == current_user.empresa_id)
        .order_by(Documento.codigo.asc())
        .all()
    )


def _document_versions_for_evidence():
    return (
        DocumentoVersion.query
        .join(Documento, Documento.id == DocumentoVersion.documento_id)
        .filter(
            DocumentoVersion.empresa_id == current_user.empresa_id,
            Documento.empresa_id == current_user.empresa_id,
        )
        .order_by(Documento.codigo.asc(), DocumentoVersion.version.asc())
        .all()
    )


def _get_plan_or_404(plan_id):
    plan = EquipoPlanMantenimiento.query.filter_by(id=plan_id, empresa_id=current_user.empresa_id).first()
    if not plan:
        abort(404)
    return plan


def _get_maintenance_or_404(item_id):
    item = EquipoMantenimiento.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first()
    if not item:
        abort(404)
    return item


def _get_calibration_or_404(item_id):
    item = EquipoCalibracion.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first()
    if not item:
        abort(404)
    return item


def _get_environment_condition_or_404(item_id):
    item = AreaCondicionAmbiental.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first()
    if not item:
        abort(404)
    return item


def _get_material_reference_or_404(item_id):
    item = MaterialReferencia.query.filter_by(id=item_id, empresa_id=current_user.empresa_id).first()
    if not item:
        abort(404)
    return item


def _redirect_back_to_maintenance(item):
    return redirect(url_for("equipamiento.detalle_mantenimiento", item_id=item.id))


def _redirect_back_to_calibration(item):
    return redirect(url_for("equipamiento.detalle_calibracion", item_id=item.id))


def _redirect_back_to_environment_condition(item):
    return redirect(url_for("equipamiento.detalle_condicion_ambiental", item_id=item.id))


def _redirect_back_to_material_reference(item):
    return redirect(url_for("equipamiento.detalle_material_referencia", item_id=item.id))


def _estado_filter(query, model, estado):
    if estado == "activos":
        return query.filter(model.estado == "activo")
    if estado == "inactivos":
        return query.filter(model.estado == "inactivo")
    return query


def _controlled_areas():
    return (
        AreaAmbiente.query
        .filter_by(empresa_id=current_user.empresa_id, estado="activo", requiere_control_ambiental=True)
        .order_by(AreaAmbiente.codigo.asc())
        .all()
    )


def _latest_measurements_for_conditions(condition_ids):
    latest = {}
    if not condition_ids:
        return latest
    measurements = (
        AreaMedicionAmbiental.query
        .filter(
            AreaMedicionAmbiental.empresa_id == current_user.empresa_id,
            AreaMedicionAmbiental.condicion_ambiental_id.in_(condition_ids),
        )
        .order_by(AreaMedicionAmbiental.fecha_hora_medicion.desc(), AreaMedicionAmbiental.id.desc())
        .all()
    )
    for measurement in measurements:
        latest.setdefault(measurement.condicion_ambiental_id, measurement)
    return latest


def _environment_condition_form_context(item=None, form_data=None, area_id=None):
    return _environment_template_context(
        item=item,
        form_data=form_data or {},
        area_id=area_id,
        areas=_controlled_areas(),
    )


def _active_environment_conditions(area_id=None):
    query = AreaCondicionAmbiental.query.filter_by(empresa_id=current_user.empresa_id, activa=True)
    if area_id:
        query = query.filter_by(area_ambiente_id=area_id)
    return query.order_by(AreaCondicionAmbiental.codigo.asc()).all()


def _environment_measurement_form_context(form_data=None, area_id=None, condicion_id=None):
    selected_area_id = area_id or (form_data or {}).get("area_ambiente_id")
    return _environment_template_context(
        form_data=form_data or {},
        area_id=selected_area_id,
        condicion_id=condicion_id or (form_data or {}).get("condicion_ambiental_id"),
        areas=_controlled_areas(),
        condiciones=_active_environment_conditions(selected_area_id),
    )


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
    return render_template("equipamiento/instalaciones_index.html", items=items, q=q, estado=estado, csrf_token=_maintenance_csrf_token())


@bp.route("/instalaciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission("instalaciones.crear")
def nueva_instalacion():
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            item = create_instalacion(current_user, request.form)
            db.session.commit()
            flash("Instalacion creada correctamente.", "success")
            return redirect(url_for("equipamiento.instalaciones"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/instalacion_form.html", item=None, form_data=request.form, csrf_token=_maintenance_csrf_token())
    return render_template("equipamiento/instalacion_form.html", item=None, form_data={}, csrf_token=_maintenance_csrf_token())


@bp.route("/instalaciones/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission("instalaciones.editar")
def editar_instalacion(item_id):
    item = get_instalacion(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            update_instalacion(current_user, item, request.form)
            db.session.commit()
            flash("Instalacion actualizada correctamente.", "success")
            return redirect(url_for("equipamiento.instalaciones"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/instalacion_form.html", item=item, form_data=request.form, csrf_token=_maintenance_csrf_token())
    return render_template("equipamiento/instalacion_form.html", item=item, form_data={}, csrf_token=_maintenance_csrf_token())


@bp.route("/instalaciones/<int:item_id>/inactivar", methods=["POST"])
@login_required
@require_permission("instalaciones.inactivar")
def inactivar_instalacion(item_id):
    _validate_maintenance_csrf()
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
        csrf_token=_maintenance_csrf_token(),
    )


@bp.route("/areas/nueva", methods=["GET", "POST"])
@login_required
@require_permission("areas.crear")
def nueva_area():
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            create_area(current_user, request.form)
            db.session.commit()
            flash("Area o ambiente creado correctamente.", "success")
            return redirect(url_for("equipamiento.areas"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/area_form.html", item=None, form_data=request.form, instalaciones=active_instalaciones(current_user), csrf_token=_maintenance_csrf_token())
    return render_template("equipamiento/area_form.html", item=None, form_data={}, instalaciones=active_instalaciones(current_user), csrf_token=_maintenance_csrf_token())


@bp.route("/areas/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission("areas.editar")
def editar_area(item_id):
    item = get_area(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            update_area(current_user, item, request.form)
            db.session.commit()
            flash("Area o ambiente actualizado correctamente.", "success")
            return redirect(url_for("equipamiento.areas"))
        except EquipamientoError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/area_form.html", item=item, form_data=request.form, instalaciones=active_instalaciones(current_user), csrf_token=_maintenance_csrf_token())
    return render_template("equipamiento/area_form.html", item=item, form_data={}, instalaciones=active_instalaciones(current_user), csrf_token=_maintenance_csrf_token())


@bp.route("/areas/<int:item_id>/inactivar", methods=["POST"])
@login_required
@require_permission("areas.inactivar")
def inactivar_area(item_id):
    _validate_maintenance_csrf()
    item = get_area(current_user, item_id)
    if not item:
        abort(404)
    item.estado = "inactivo"
    db.session.commit()
    flash("Area o ambiente inactivado correctamente.", "warning")
    return redirect(url_for("equipamiento.areas"))


@bp.route("/areas/<int:item_id>")
@login_required
@require_permission("areas.ver")
def detalle_area(item_id):
    item = get_area(current_user, item_id)
    if not item:
        abort(404)
    condiciones = ambiente_service.condiciones_area(current_user, item.id) if item.requiere_control_ambiental else []
    latest_measurements = _latest_measurements_for_conditions([condition.id for condition in condiciones])
    history = (
        AreaHistorialAmbiental.query
        .filter_by(empresa_id=current_user.empresa_id, area_ambiente_id=item.id)
        .order_by(AreaHistorialAmbiental.created_at.desc(), AreaHistorialAmbiental.id.desc())
        .all()
    )
    return render_template(
        "equipamiento/area_detalle.html",
        **_environment_template_context(
            item=item,
            condiciones=condiciones,
            latest_measurements=latest_measurements,
            history=history,
            condicion_activa_badge_class=_condicion_activa_badge_class,
        ),
    )


@bp.route("/condiciones-ambientales")
@login_required
@require_permission(ambiente_service.PERM_VER)
def condiciones_ambientales():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "estado", "vista")}
    if filters["vista"] == "fuera_limite":
        return redirect(url_for("equipamiento.mediciones_ambientales_fuera_limite"))
    query = AreaCondicionAmbiental.query.filter_by(empresa_id=current_user.empresa_id).join(
        AreaAmbiente,
        AreaAmbiente.id == AreaCondicionAmbiental.area_ambiente_id,
    ).filter(AreaAmbiente.empresa_id == current_user.empresa_id)
    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.filter(or_(
            AreaAmbiente.codigo.ilike(like),
            AreaAmbiente.nombre.ilike(like),
            AreaCondicionAmbiental.codigo.ilike(like),
            AreaCondicionAmbiental.nombre.ilike(like),
            AreaCondicionAmbiental.unidad.ilike(like),
        ))
    if filters["estado"] == "activas":
        query = query.filter(AreaCondicionAmbiental.activa.is_(True))
    elif filters["estado"] == "inactivas":
        query = query.filter(AreaCondicionAmbiental.activa.is_(False))
    items = query.order_by(AreaAmbiente.codigo.asc(), AreaCondicionAmbiental.codigo.asc()).all()
    latest_measurements = _latest_measurements_for_conditions([item.id for item in items])
    return render_template(
        "equipamiento/condiciones_ambientales_index.html",
        **_environment_template_context(
            items=items,
            filters=filters,
            latest_measurements=latest_measurements,
            condicion_activa_badge_class=_condicion_activa_badge_class,
        ),
    )


@bp.route("/condiciones-ambientales/nueva", methods=["GET", "POST"])
@login_required
@require_permission(ambiente_service.PERM_GESTIONAR)
def nueva_condicion_ambiental():
    area_id = request.args.get("area_id", "").strip()
    if request.method == "POST":
        _validate_maintenance_csrf()
        area_id = request.form.get("area_ambiente_id")
        try:
            item = ambiente_service.crear_condicion(current_user, area_id, request.form)
            if not request.form.get("activa"):
                ambiente_service.inactivar_condicion(current_user, item.id, "Configuracion creada como inactiva.")
            db.session.commit()
            flash("Condicion ambiental creada correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_condicion_ambiental", item_id=item.id))
        except (CondicionAmbientalError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "equipamiento/condicion_ambiental_form.html",
                **_environment_condition_form_context(form_data=request.form, area_id=area_id),
            )
    return render_template(
        "equipamiento/condicion_ambiental_form.html",
        **_environment_condition_form_context(form_data={"activa": "1"}, area_id=area_id),
    )


@bp.route("/condiciones-ambientales/<int:item_id>")
@login_required
@require_permission(ambiente_service.PERM_VER)
def detalle_condicion_ambiental(item_id):
    item = _get_environment_condition_or_404(item_id)
    measurements = (
        AreaMedicionAmbiental.query
        .filter_by(empresa_id=current_user.empresa_id, condicion_ambiental_id=item.id)
        .order_by(AreaMedicionAmbiental.fecha_hora_medicion.desc(), AreaMedicionAmbiental.id.desc())
        .all()
    )
    history = (
        AreaHistorialAmbiental.query
        .filter_by(empresa_id=current_user.empresa_id, condicion_ambiental_id=item.id)
        .order_by(AreaHistorialAmbiental.created_at.desc(), AreaHistorialAmbiental.id.desc())
        .all()
    )
    return render_template(
        "equipamiento/condicion_ambiental_detalle.html",
        **_environment_template_context(
            item=item,
            measurements=measurements,
            history=history,
            condicion_activa_badge_class=_condicion_activa_badge_class,
        ),
    )


@bp.route("/condiciones-ambientales/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(ambiente_service.PERM_GESTIONAR)
def editar_condicion_ambiental(item_id):
    item = _get_environment_condition_or_404(item_id)
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            ambiente_service.actualizar_condicion(current_user, item.id, request.form)
            db.session.commit()
            flash("Condicion ambiental actualizada correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_condicion_ambiental", item_id=item.id))
        except (CondicionAmbientalError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "equipamiento/condicion_ambiental_form.html",
                **_environment_condition_form_context(item=item, form_data=request.form, area_id=item.area_ambiente_id),
            )
    return render_template(
        "equipamiento/condicion_ambiental_form.html",
        **_environment_condition_form_context(item=item, area_id=item.area_ambiente_id),
    )


@bp.route("/condiciones-ambientales/<int:item_id>/inactivar", methods=["POST"])
@login_required
@require_permission(ambiente_service.PERM_GESTIONAR)
def inactivar_condicion_ambiental(item_id):
    _validate_maintenance_csrf()
    item = _get_environment_condition_or_404(item_id)
    try:
        ambiente_service.inactivar_condicion(current_user, item.id, request.form.get("observaciones"))
        db.session.commit()
        flash("Condicion ambiental inactivada correctamente.", "warning")
    except CondicionAmbientalError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_environment_condition(item)


@bp.route("/condiciones-ambientales/mediciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission(ambiente_service.PERM_GESTIONAR)
def nueva_medicion_ambiental():
    area_id = (request.args.get("area_id") or request.args.get("area_ambiente_id") or "").strip()
    condicion_id = (request.args.get("condicion_id") or request.args.get("condicion_ambiental_id") or "").strip()
    if request.method == "POST":
        _validate_maintenance_csrf()
        area_id = request.form.get("area_ambiente_id")
        condicion_id = request.form.get("condicion_ambiental_id")
        try:
            measurement = ambiente_service.registrar_medicion(current_user, area_id, condicion_id, request.form)
            db.session.commit()
            flash(
                f"Medicion registrada: {measurement.estado.replace('_', ' ')}.",
                "success" if measurement.estado == "CONFORME" else "warning",
            )
            return redirect(url_for("equipamiento.detalle_condicion_ambiental", item_id=measurement.condicion_ambiental_id))
        except (CondicionAmbientalError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "equipamiento/medicion_ambiental_form.html",
                **_environment_measurement_form_context(form_data=request.form, area_id=area_id, condicion_id=condicion_id),
            )
    return render_template(
        "equipamiento/medicion_ambiental_form.html",
        **_environment_measurement_form_context(area_id=area_id, condicion_id=condicion_id),
    )


@bp.route("/condiciones-ambientales/fuera-limite")
@login_required
@require_permission(ambiente_service.PERM_VER)
def mediciones_ambientales_fuera_limite():
    measurements = ambiente_service.mediciones_fuera_de_limite(current_user)
    return render_template(
        "equipamiento/mediciones_ambientales_fuera_limite.html",
        **_environment_template_context(measurements=measurements),
    )


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
        "csrf_token": _maintenance_csrf_token(),
        "instalaciones": active_instalaciones(current_user),
        "areas": active_areas(current_user),
        "estados_operativos": ESTADOS_OPERATIVOS_EQUIPO,
        "criticidades": CRITICIDADES_EQUIPO,
    }


@bp.route("/mantenimientos")
@login_required
@require_permission(mantenimiento_service.PERM_VER)
def mantenimientos():
    filters = {key: request.args.get(key, "").strip() for key in (
        "q", "equipo_id", "tipo", "estado", "vista", "fecha_desde", "fecha_hasta",
    )}
    query = EquipoMantenimiento.query.filter_by(empresa_id=current_user.empresa_id)
    if filters["vista"] == "vencidos":
        items = mantenimiento_service.mantenimientos_vencidos(current_user)
        query = None
    elif filters["vista"] == "proximos":
        items = mantenimiento_service.mantenimientos_proximos(current_user)
        query = None
    else:
        items = None
    if query is not None:
        if filters["q"]:
            like = f"%{filters['q']}%"
            query = query.join(Equipo, Equipo.id == EquipoMantenimiento.equipo_id).filter(
                Equipo.empresa_id == current_user.empresa_id,
                or_(
                    EquipoMantenimiento.codigo.ilike(like),
                    Equipo.codigo.ilike(like),
                    Equipo.nombre.ilike(like),
                    EquipoMantenimiento.proveedor.ilike(like),
                ),
            )
        if filters["equipo_id"]:
            query = query.filter(EquipoMantenimiento.equipo_id == int(filters["equipo_id"]))
        if filters["tipo"]:
            query = query.filter(EquipoMantenimiento.tipo_mantenimiento == filters["tipo"])
        if filters["estado"]:
            query = query.filter(EquipoMantenimiento.estado == filters["estado"])
        if filters["fecha_desde"]:
            query = query.filter(EquipoMantenimiento.fecha_planificada >= date.fromisoformat(filters["fecha_desde"]))
        if filters["fecha_hasta"]:
            query = query.filter(EquipoMantenimiento.fecha_planificada <= date.fromisoformat(filters["fecha_hasta"]))
        items = query.order_by(EquipoMantenimiento.fecha_planificada.asc(), EquipoMantenimiento.codigo.asc()).all()
    return render_template(
        "equipamiento/mantenimientos_index.html",
        **_maintenance_template_context(
            items=items,
            filters=filters,
            equipos=Equipo.query.filter_by(empresa_id=current_user.empresa_id).order_by(Equipo.codigo.asc()).all(),
        ),
    )


@bp.route("/calibraciones")
@login_required
@require_permission(calibracion_service.PERM_VER)
def calibraciones():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "tipo", "estado")}
    query = EquipoCalibracion.query.filter_by(empresa_id=current_user.empresa_id)
    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.join(Equipo, Equipo.id == EquipoCalibracion.equipo_id).filter(
            Equipo.empresa_id == current_user.empresa_id,
            or_(
                EquipoCalibracion.codigo.ilike(like),
                Equipo.codigo.ilike(like),
                Equipo.nombre.ilike(like),
                EquipoCalibracion.proveedor.ilike(like),
            ),
        )
    if filters["tipo"]:
        query = query.filter(EquipoCalibracion.tipo_control == filters["tipo"])
    if filters["estado"]:
        query = query.filter(EquipoCalibracion.estado == filters["estado"])
    items = query.order_by(EquipoCalibracion.fecha_planificada.asc(), EquipoCalibracion.codigo.asc()).all()
    return render_template(
        "equipamiento/calibraciones_index.html",
        **_calibration_template_context(items=items, filters=filters),
    )


@bp.route("/materiales-referencia")
@login_required
@require_permission(material_referencia_service.PERM_VER)
def materiales_referencia():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "tipo", "estado")}
    query = MaterialReferencia.query.filter_by(empresa_id=current_user.empresa_id)
    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.filter(or_(
            MaterialReferencia.codigo.ilike(like),
            MaterialReferencia.nombre.ilike(like),
            MaterialReferencia.lote.ilike(like),
        ))
    if filters["tipo"]:
        query = query.filter(MaterialReferencia.tipo == filters["tipo"])
    if filters["estado"]:
        query = query.filter(MaterialReferencia.estado == filters["estado"])
    items = query.order_by(MaterialReferencia.codigo.asc()).all()
    return render_template(
        "equipamiento/materiales_referencia_index.html",
        **_material_reference_template_context(items=items, filters=filters),
    )


def _material_reference_form_context(form_data=None):
    return _material_reference_template_context(
        form_data=form_data or {},
        responsables=_active_users(),
    )


@bp.route("/materiales-referencia/nuevo", methods=["GET", "POST"])
@login_required
@require_permission(material_referencia_service.PERM_GESTIONAR)
def nuevo_material_referencia():
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            item = material_referencia_service.crear_material_referencia(current_user, request.form)
            db.session.commit()
            flash("Material o patron de referencia creado correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_material_referencia", item_id=item.id))
        except (MaterialReferenciaError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "equipamiento/material_referencia_form.html",
                **_material_reference_form_context(form_data=request.form),
            )
    return render_template(
        "equipamiento/material_referencia_form.html",
        **_material_reference_form_context(form_data={"tipo": "MATERIAL_REFERENCIA"}),
    )


@bp.route("/materiales-referencia/<int:item_id>")
@login_required
@require_permission(material_referencia_service.PERM_VER)
def detalle_material_referencia(item_id):
    item = _get_material_reference_or_404(item_id)
    history = (
        MaterialReferenciaHistorial.query
        .filter_by(empresa_id=current_user.empresa_id, material_referencia_id=item.id)
        .order_by(MaterialReferenciaHistorial.created_at.desc(), MaterialReferenciaHistorial.id.desc())
        .all()
    )
    return render_template(
        "equipamiento/material_referencia_detalle.html",
        **_material_reference_template_context(
            item=item,
            history=history,
            documentos=_documents_for_evidence(),
            document_versions=_document_versions_for_evidence(),
        ),
    )


@bp.route("/materiales-referencia/<int:item_id>/poner-en-uso", methods=["POST"])
@login_required
@require_permission(material_referencia_service.PERM_GESTIONAR)
def poner_en_uso_material_referencia(item_id):
    _validate_maintenance_csrf()
    item = _get_material_reference_or_404(item_id)
    try:
        material_referencia_service.poner_en_uso(
            current_user,
            item.id,
            request.form.get("fecha"),
            request.form.get("observaciones"),
        )
        db.session.commit()
        flash("Material o patron de referencia puesto en uso correctamente.", "success")
    except MaterialReferenciaError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_material_reference(item)


@bp.route("/materiales-referencia/<int:item_id>/agotar", methods=["POST"])
@login_required
@require_permission(material_referencia_service.PERM_GESTIONAR)
def agotar_material_referencia(item_id):
    _validate_maintenance_csrf()
    item = _get_material_reference_or_404(item_id)
    try:
        material_referencia_service.agotar(current_user, item.id, request.form.get("motivo"))
        db.session.commit()
        flash("Material o patron de referencia marcado como agotado.", "warning")
    except MaterialReferenciaError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_material_reference(item)


@bp.route("/materiales-referencia/<int:item_id>/retirar", methods=["POST"])
@login_required
@require_permission(material_referencia_service.PERM_GESTIONAR)
def retirar_material_referencia(item_id):
    _validate_maintenance_csrf()
    item = _get_material_reference_or_404(item_id)
    try:
        material_referencia_service.retirar(current_user, item.id, request.form.get("motivo"))
        db.session.commit()
        flash("Material o patron de referencia retirado correctamente.", "warning")
    except MaterialReferenciaError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_material_reference(item)


@bp.route("/materiales-referencia/<int:item_id>/marcar-vencido", methods=["POST"])
@login_required
@require_permission(material_referencia_service.PERM_GESTIONAR)
def marcar_vencido_material_referencia(item_id):
    _validate_maintenance_csrf()
    item = _get_material_reference_or_404(item_id)
    try:
        material_referencia_service.marcar_vencido(current_user, item.id)
        db.session.commit()
        flash("Material o patron de referencia marcado como vencido.", "warning")
    except MaterialReferenciaError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_material_reference(item)


@bp.route("/materiales-referencia/<int:item_id>/evidencias", methods=["POST"])
@login_required
@require_permission(material_referencia_service.PERM_VINCULAR_EVIDENCIA)
def vincular_evidencia_material_referencia(item_id):
    _validate_maintenance_csrf()
    item = _get_material_reference_or_404(item_id)
    try:
        material_referencia_service.vincular_evidencia_documental(
            current_user,
            item.id,
            request.form.get("documento_id"),
            request.form.get("documento_version_id"),
            request.form.get("tipo_evidencia"),
            request.form.get("observaciones"),
        )
        db.session.commit()
        flash("Evidencia vinculada correctamente.", "success")
    except MaterialReferenciaError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_material_reference(item)


@bp.route("/materiales-referencia/evidencias/<int:evidencia_id>/desvincular", methods=["POST"])
@login_required
@require_permission(material_referencia_service.PERM_DESVINCULAR_EVIDENCIA)
def desvincular_evidencia_material_referencia(evidencia_id):
    _validate_maintenance_csrf()
    evidence = MaterialReferenciaDocumento.query.filter_by(id=evidencia_id, empresa_id=current_user.empresa_id).first()
    if not evidence:
        abort(404)
    item_id = evidence.material_referencia_id
    try:
        material_referencia_service.desvincular_evidencia_documental(current_user, evidence.id, request.form.get("motivo"))
        db.session.commit()
        flash("Evidencia desvinculada correctamente.", "warning")
    except MaterialReferenciaError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("equipamiento.detalle_material_referencia", item_id=item_id))


def _calibration_form_context(form_data=None):
    return _calibration_template_context(
        form_data=form_data or {},
        equipos=_active_equipment(),
        responsables=_active_users(),
    )


@bp.route("/calibraciones/nueva", methods=["GET", "POST"])
@login_required
@require_permission(calibracion_service.PERM_GESTIONAR)
def nueva_calibracion():
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            item = calibracion_service.programar_control(
                current_user,
                request.form.get("equipo_id"),
                request.form,
            )
            db.session.commit()
            flash("Control metrologico programado correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_calibracion", item_id=item.id))
        except (EquipoCalibracionError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/calibracion_form.html", **_calibration_form_context(form_data=request.form))
    return render_template("equipamiento/calibracion_form.html", **_calibration_form_context())


@bp.route("/calibraciones/<int:item_id>")
@login_required
@require_permission(calibracion_service.PERM_VER)
def detalle_calibracion(item_id):
    item = _get_calibration_or_404(item_id)
    history = (
        EquipoHistorial.query
        .filter_by(empresa_id=current_user.empresa_id, equipo_id=item.equipo_id)
        .filter(EquipoHistorial.tipo_evento.in_(CALIBRATION_HISTORY_EVENTS))
        .order_by(EquipoHistorial.created_at.desc(), EquipoHistorial.id.desc())
        .all()
    )
    return render_template(
        "equipamiento/calibracion_detalle.html",
        **_calibration_template_context(
            item=item,
            history=history,
            documentos=_documents_for_evidence(),
            document_versions=_document_versions_for_evidence(),
        ),
    )


@bp.route("/calibraciones/<int:item_id>/iniciar", methods=["POST"])
@login_required
@require_permission(calibracion_service.PERM_GESTIONAR)
def iniciar_calibracion(item_id):
    _validate_maintenance_csrf()
    item = _get_calibration_or_404(item_id)
    try:
        calibracion_service.iniciar_control(current_user, item.id, request.form.get("fecha_inicio"))
        db.session.commit()
        flash("Control metrologico iniciado correctamente.", "success")
    except EquipoCalibracionError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_calibration(item)


@bp.route("/calibraciones/<int:item_id>/completar", methods=["POST"])
@login_required
@require_permission(calibracion_service.PERM_GESTIONAR)
def completar_calibracion(item_id):
    _validate_maintenance_csrf()
    item = _get_calibration_or_404(item_id)
    try:
        calibracion_service.completar_control(current_user, item.id, request.form)
        db.session.commit()
        flash("Control metrologico completado correctamente.", "success")
    except EquipoCalibracionError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_calibration(item)


@bp.route("/calibraciones/<int:item_id>/cancelar", methods=["POST"])
@login_required
@require_permission(calibracion_service.PERM_GESTIONAR)
def cancelar_calibracion(item_id):
    _validate_maintenance_csrf()
    item = _get_calibration_or_404(item_id)
    try:
        calibracion_service.cancelar_control(current_user, item.id, request.form.get("motivo"))
        db.session.commit()
        flash("Control metrologico cancelado correctamente.", "warning")
    except EquipoCalibracionError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_calibration(item)


@bp.route("/calibraciones/<int:item_id>/evidencias", methods=["POST"])
@login_required
@require_permission(calibracion_service.PERM_VINCULAR_EVIDENCIA)
def vincular_evidencia_calibracion(item_id):
    _validate_maintenance_csrf()
    item = _get_calibration_or_404(item_id)
    try:
        calibracion_service.vincular_evidencia_documental(
            current_user,
            item.id,
            request.form.get("documento_id"),
            request.form.get("documento_version_id"),
            request.form.get("tipo_evidencia"),
            request.form.get("observaciones"),
        )
        db.session.commit()
        flash("Evidencia vinculada correctamente.", "success")
    except EquipoCalibracionError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_calibration(item)


@bp.route("/calibraciones/evidencias/<int:evidencia_id>/desvincular", methods=["POST"])
@login_required
@require_permission(calibracion_service.PERM_DESVINCULAR_EVIDENCIA)
def desvincular_evidencia_calibracion(evidencia_id):
    _validate_maintenance_csrf()
    evidence = EquipoCalibracionDocumento.query.filter_by(id=evidencia_id, empresa_id=current_user.empresa_id).first()
    if not evidence:
        abort(404)
    item_id = evidence.calibracion_id
    try:
        calibracion_service.desvincular_evidencia_documental(current_user, evidence.id, request.form.get("motivo"))
        db.session.commit()
        flash("Evidencia desvinculada correctamente.", "warning")
    except EquipoCalibracionError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("equipamiento.detalle_calibracion", item_id=item_id))


@bp.route("/mantenimientos/correctivo/nuevo", methods=["GET", "POST"])
@login_required
@require_permission(mantenimiento_service.PERM_CREAR_CORRECTIVO)
def nuevo_mantenimiento_correctivo():
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            item = mantenimiento_service.crear_mantenimiento_correctivo(
                current_user,
                request.form.get("equipo_id"),
                request.form,
            )
            db.session.commit()
            flash("Mantenimiento correctivo creado correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_mantenimiento", item_id=item.id))
        except (EquipoMantenimientoError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template(
                "equipamiento/mantenimiento_correctivo_form.html",
                **_maintenance_template_context(form_data=request.form, equipos=_active_equipment(), responsables=_active_users()),
            )
    return render_template(
        "equipamiento/mantenimiento_correctivo_form.html",
        **_maintenance_template_context(form_data={}, equipos=_active_equipment(), responsables=_active_users()),
    )


@bp.route("/mantenimientos/<int:item_id>")
@login_required
@require_permission(mantenimiento_service.PERM_VER)
def detalle_mantenimiento(item_id):
    item = _get_maintenance_or_404(item_id)
    history = (
        EquipoHistorial.query
        .filter_by(empresa_id=current_user.empresa_id, equipo_id=item.equipo_id)
        .filter(EquipoHistorial.tipo_evento.in_([
            "MANTENIMIENTO_PROGRAMADO",
            "MANTENIMIENTO_CORRECTIVO_CREADO",
            "MANTENIMIENTO_INICIADO",
            "MANTENIMIENTO_COMPLETADO",
            "MANTENIMIENTO_CANCELADO",
            "EVIDENCIA_MANTENIMIENTO_VINCULADA",
            "EVIDENCIA_MANTENIMIENTO_DESVINCULADA",
        ]))
        .order_by(EquipoHistorial.created_at.desc(), EquipoHistorial.id.desc())
        .all()
    )
    return render_template(
        "equipamiento/mantenimiento_detalle.html",
        **_maintenance_template_context(
            item=item,
            history=history,
            documentos=_documents_for_evidence(),
            document_versions=_document_versions_for_evidence(),
        ),
    )


@bp.route("/mantenimientos/<int:item_id>/iniciar", methods=["POST"])
@login_required
@require_permission(mantenimiento_service.PERM_INICIAR)
def iniciar_mantenimiento(item_id):
    _validate_maintenance_csrf()
    item = _get_maintenance_or_404(item_id)
    try:
        mantenimiento_service.iniciar_mantenimiento(current_user, item.id, request.form.get("fecha_inicio"))
        db.session.commit()
        flash("Mantenimiento iniciado correctamente.", "success")
    except EquipoMantenimientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_maintenance(item)


@bp.route("/mantenimientos/<int:item_id>/completar", methods=["POST"])
@login_required
@require_permission(mantenimiento_service.PERM_COMPLETAR)
def completar_mantenimiento(item_id):
    _validate_maintenance_csrf()
    item = _get_maintenance_or_404(item_id)
    try:
        mantenimiento_service.completar_mantenimiento(current_user, item.id, request.form)
        db.session.commit()
        flash("Mantenimiento completado correctamente.", "success")
    except EquipoMantenimientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_maintenance(item)


@bp.route("/mantenimientos/<int:item_id>/cancelar", methods=["POST"])
@login_required
@require_permission(mantenimiento_service.PERM_CANCELAR)
def cancelar_mantenimiento(item_id):
    _validate_maintenance_csrf()
    item = _get_maintenance_or_404(item_id)
    try:
        mantenimiento_service.cancelar_mantenimiento(current_user, item.id, request.form.get("motivo"))
        db.session.commit()
        flash("Mantenimiento cancelado correctamente.", "warning")
    except EquipoMantenimientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_maintenance(item)


@bp.route("/mantenimientos/<int:item_id>/evidencias", methods=["POST"])
@login_required
@require_permission(mantenimiento_service.PERM_VINCULAR_EVIDENCIA)
def vincular_evidencia_mantenimiento(item_id):
    _validate_maintenance_csrf()
    item = _get_maintenance_or_404(item_id)
    try:
        mantenimiento_service.vincular_evidencia_documental(
            current_user,
            item.id,
            request.form.get("documento_id"),
            request.form.get("documento_version_id"),
            request.form.get("tipo_evidencia"),
            request.form.get("observaciones"),
        )
        db.session.commit()
        flash("Evidencia vinculada correctamente.", "success")
    except EquipoMantenimientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return _redirect_back_to_maintenance(item)


@bp.route("/mantenimientos/evidencias/<int:evidencia_id>/desvincular", methods=["POST"])
@login_required
@require_permission(mantenimiento_service.PERM_DESVINCULAR_EVIDENCIA)
def desvincular_evidencia_mantenimiento(evidencia_id):
    _validate_maintenance_csrf()
    evidence = EquipoMantenimientoDocumento.query.filter_by(id=evidencia_id, empresa_id=current_user.empresa_id).first()
    if not evidence:
        abort(404)
    maintenance_id = evidence.mantenimiento_id
    try:
        mantenimiento_service.desvincular_evidencia_documental(current_user, evidence.id, request.form.get("motivo"))
        db.session.commit()
        flash("Evidencia desvinculada correctamente.", "warning")
    except EquipoMantenimientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("equipamiento.detalle_mantenimiento", item_id=maintenance_id))


@bp.route("/planes-mantenimiento")
@login_required
@require_permission(mantenimiento_service.PERM_VER)
def planes_mantenimiento():
    filters = {key: request.args.get(key, "").strip() for key in ("q", "equipo_id", "estado")}
    query = EquipoPlanMantenimiento.query.filter_by(empresa_id=current_user.empresa_id)
    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.join(Equipo, Equipo.id == EquipoPlanMantenimiento.equipo_id).filter(
            Equipo.empresa_id == current_user.empresa_id,
            or_(
                EquipoPlanMantenimiento.codigo.ilike(like),
                EquipoPlanMantenimiento.nombre.ilike(like),
                Equipo.codigo.ilike(like),
                Equipo.nombre.ilike(like),
            ),
        )
    if filters["equipo_id"]:
        query = query.filter(EquipoPlanMantenimiento.equipo_id == int(filters["equipo_id"]))
    if filters["estado"]:
        query = query.filter(EquipoPlanMantenimiento.estado == filters["estado"])
    items = query.order_by(EquipoPlanMantenimiento.codigo.asc()).all()
    return render_template(
        "equipamiento/planes_mantenimiento_index.html",
        **_maintenance_template_context(
            items=items,
            filters=filters,
            equipos=Equipo.query.filter_by(empresa_id=current_user.empresa_id).order_by(Equipo.codigo.asc()).all(),
        ),
    )


def _plan_form_context(item=None, form_data=None):
    return _maintenance_template_context(
        item=item,
        form_data=form_data or {},
        equipos=_active_equipment(),
        responsables=_active_users(),
    )


@bp.route("/planes-mantenimiento/nuevo", methods=["GET", "POST"])
@login_required
@require_permission(mantenimiento_service.PERM_CREAR_PLAN)
def nuevo_plan_mantenimiento():
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            plan = mantenimiento_service.crear_plan_preventivo(current_user, request.form)
            db.session.commit()
            flash("Plan de mantenimiento creado correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_plan_mantenimiento", plan_id=plan.id))
        except (EquipoMantenimientoError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/plan_mantenimiento_form.html", **_plan_form_context(form_data=request.form))
    return render_template("equipamiento/plan_mantenimiento_form.html", **_plan_form_context())


@bp.route("/planes-mantenimiento/<int:plan_id>")
@login_required
@require_permission(mantenimiento_service.PERM_VER)
def detalle_plan_mantenimiento(plan_id):
    plan = _get_plan_or_404(plan_id)
    return render_template(
        "equipamiento/plan_mantenimiento_detalle.html",
        **_maintenance_template_context(plan=plan, form_data={}),
    )


@bp.route("/planes-mantenimiento/<int:plan_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission(mantenimiento_service.PERM_EDITAR_PLAN)
def editar_plan_mantenimiento(plan_id):
    plan = _get_plan_or_404(plan_id)
    if request.method == "POST":
        _validate_maintenance_csrf()
        try:
            mantenimiento_service.actualizar_plan_preventivo(current_user, plan.id, request.form)
            db.session.commit()
            flash("Plan de mantenimiento actualizado correctamente.", "success")
            return redirect(url_for("equipamiento.detalle_plan_mantenimiento", plan_id=plan.id))
        except (EquipoMantenimientoError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return render_template("equipamiento/plan_mantenimiento_form.html", **_plan_form_context(item=plan, form_data=request.form))
    if plan.estado != "ACTIVO":
        flash("Los planes inactivos no se pueden editar.", "warning")
        return redirect(url_for("equipamiento.detalle_plan_mantenimiento", plan_id=plan.id))
    return render_template("equipamiento/plan_mantenimiento_form.html", **_plan_form_context(item=plan))


@bp.route("/planes-mantenimiento/<int:plan_id>/inactivar", methods=["POST"])
@login_required
@require_permission(mantenimiento_service.PERM_EDITAR_PLAN)
def inactivar_plan_mantenimiento(plan_id):
    _validate_maintenance_csrf()
    plan = _get_plan_or_404(plan_id)
    try:
        mantenimiento_service.inactivar_plan_preventivo(current_user, plan.id, request.form.get("motivo"))
        db.session.commit()
        flash("Plan de mantenimiento inactivado correctamente.", "warning")
    except EquipoMantenimientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("equipamiento.detalle_plan_mantenimiento", plan_id=plan.id))


@bp.route("/planes-mantenimiento/<int:plan_id>/programar", methods=["POST"])
@login_required
@require_permission(mantenimiento_service.PERM_PROGRAMAR)
def programar_plan_mantenimiento(plan_id):
    _validate_maintenance_csrf()
    plan = _get_plan_or_404(plan_id)
    try:
        item = mantenimiento_service.programar_mantenimiento_desde_plan(
            current_user,
            plan.id,
            request.form.get("fecha_planificada"),
            request.form.get("observaciones"),
        )
        db.session.commit()
        flash("Mantenimiento preventivo programado correctamente.", "success")
        return redirect(url_for("equipamiento.detalle_mantenimiento", item_id=item.id))
    except EquipoMantenimientoError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("equipamiento.detalle_plan_mantenimiento", plan_id=plan.id))


@bp.route("/equipos/nuevo", methods=["GET", "POST"])
@login_required
@require_permission("equipos.crear")
def nuevo_equipo():
    if request.method == "POST":
        _validate_maintenance_csrf()
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
    csrf_token = _maintenance_csrf_token()
    metrologia_items = (
        EquipoCalibracion.query
        .filter_by(empresa_id=current_user.empresa_id, equipo_id=item.id)
        .order_by(EquipoCalibracion.fecha_planificada.desc(), EquipoCalibracion.codigo.desc())
        .all()
    )
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
        metrologia_items=metrologia_items,
        csrf_token=csrf_token,
        estado_calibracion_badge_class=_estado_calibracion_badge_class,
        equipo_history_change_labels=equipo_history_change_labels,
        format_local_datetime=ambiente_service.format_local_datetime,
    )


@bp.route("/equipos/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
@require_permission("equipos.editar")
def editar_equipo(item_id):
    item = get_equipo(current_user, item_id)
    if not item:
        abort(404)
    if request.method == "POST":
        _validate_maintenance_csrf()
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
    _validate_maintenance_csrf()
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
    _validate_maintenance_csrf()
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
    _validate_maintenance_csrf()
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
