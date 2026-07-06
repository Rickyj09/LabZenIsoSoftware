from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def user_has_permission(user, codigo_permiso):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "activo", False):
        return False

    return any(
        role_link.rol
        and any(
            permission_link.permiso
            and permission_link.permiso.codigo == codigo_permiso
            for permission_link in role_link.rol.permisos
        )
        for role_link in user.roles
    )


def current_user_can(codigo_permiso):
    return user_has_permission(current_user, codigo_permiso)


def require_permission(codigo_permiso):
    def decorator(view):
        @wraps(view)
        def permission_checked(*args, **kwargs):
            if not current_user_can(codigo_permiso):
                abort(403)
            return view(*args, **kwargs)

        return login_required(permission_checked)

    return decorator
