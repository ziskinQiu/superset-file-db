"""Superset-native permission checks (spec 6): no custom roles."""


def current_user():
    try:
        from flask import g

        user = getattr(g, "user", None)
    except RuntimeError:  # outside an application context
        user = None
    if user is None or getattr(user, "is_anonymous", False):
        raise PermissionError("authentication required")
    return user


def current_user_id() -> str:
    return str(current_user().id)


def is_admin(user=None) -> bool:
    user = user if user is not None else current_user()
    return any("Admin" in str(getattr(role, "name", role)) for role in getattr(user, "roles", []) or [])


def can_create_datasource(user=None) -> bool:
    user = user if user is not None else current_user()
    return is_admin(user) or "can_write on Dataset" in _permission_strings(user)


def check_file_owner(file_record, user=None) -> None:
    user = user if user is not None else current_user()
    if is_admin(user):
        return
    if str(getattr(file_record, "created_by", None)) != str(user.id):
        raise PermissionError("only the file owner or an admin may modify this file")


def _permission_strings(user) -> set:
    """Accept both plain-string sets (tests) and FAB role->permission objects."""
    perms = {str(p) for p in getattr(user, "permissions", None) or []}
    for role in getattr(user, "roles", []) or []:
        for perm in getattr(role, "permissions", []) or []:
            name = getattr(perm, "name", None)
            if name is None:
                perms.add(str(perm))
                continue
            menu = getattr(perm, "view_menu", None)
            if menu is not None:
                perms.add(f"{name} on {getattr(menu, 'name', menu)}")
            else:
                perms.add(str(name))
    return perms
