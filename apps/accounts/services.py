"""`admin/users`, `admin/users/[id]` business rules (task 7.1),
near-verbatim ports of `app/api/admin/users/route.ts` and
`app/api/admin/users/[id]/route.ts`.

New/updated passwords are hashed with Django's own `make_password` (which
uses the FIRST-listed `PASSWORD_HASHERS` entry, PBKDF2 — design decision
#5's "preferred hasher going forward"), not the legacy `ScryptLegacyHasher`
— that hasher exists only to VERIFY rows the frozen Next.js app already
wrote, never to encode new ones (see `apps/accounts/hashers.py`'s module
docstring).
"""
from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.db.models import Case, When
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import (
    DEFAULT_EMPLOYEE_PERMISSIONS,
    normalize_permissions,
)
from apps.backoffice.models import ActivityLog


def _serialize_user(user: User) -> dict:
    return {
        "id": user.pk,
        "name": user.display_name,
        "username": user.username,
        "role": user.role,
        "active": user.active,
        "permissions": user.permissions or [],
        "createdAt": user.created_at,
    }


def list_admin_users() -> list[dict]:
    """`GET /api/admin/users` — admin role first, then by `created_at`."""
    users = User.objects.order_by(
        Case(When(role="admin", then=0), default=1), "created_at"
    )
    return [_serialize_user(user) for user in users]


def create_admin_user(payload: dict, actor_username: str) -> dict:
    """`POST /api/admin/users`."""
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        return {"error": "Username and password required", "status": 400}

    user_id = payload.get("id") or _random_id("U")
    name = str(payload.get("name") or username).strip()
    username = str(username).strip()
    submitted_permissions = payload.get("permissions")
    permissions = normalize_permissions(
        submitted_permissions if submitted_permissions else DEFAULT_EMPLOYEE_PERMISSIONS
    )

    try:
        with transaction.atomic():
            User.objects.create(
                id=user_id,
                display_name=name,
                username=username,
                password_hash=make_password(str(password)),
                role="authorized",
                active=True,
                permissions=permissions,
                created_at=timezone.now(),
            )
    except IntegrityError:
        return {"error": "Username already exists", "status": 409}

    ActivityLog.objects.create(
        actor_id=actor_username,
        action="USER_CREATED",
        entity_type="USER",
        entity_id=user_id,
        data={"username": username, "permissions": permissions},
        created_at=timezone.now(),
    )
    return {
        "ok": True,
        "user": {
            "id": user_id,
            "name": name,
            "username": username,
            "role": "authorized",
            "active": True,
            "permissions": permissions,
        },
    }


def update_admin_user(user_id: str, payload: dict, actor_username: str) -> dict:
    """`PUT /api/admin/users/[id]`. The primary Admin branch only allows
    name/username/password changes and rejects deactivation or a role
    change away from `admin`; the employee branch replaces `permissions`
    wholesale and revokes sessions on deactivation."""
    target = User.objects.filter(pk=user_id).first()
    if target is None:
        return {"error": "User not found", "status": 404}

    is_admin = str(target.role).lower() == "admin"
    if is_admin:
        active = payload.get("active")
        role = payload.get("role")
        if active is False or (role is not None and str(role).lower() != "admin"):
            return {"error": "The primary Admin must remain active with full access", "status": 403}

        if payload.get("name") is not None:
            target.display_name = payload["name"]
        if payload.get("username") is not None:
            target.username = payload["username"]
        if payload.get("password"):
            target.password_hash = make_password(str(payload["password"]))
        target.save(update_fields=["display_name", "username", "password_hash"])
        permissions_for_log = ["*"]
    else:
        permissions = normalize_permissions(payload.get("permissions") or [])
        if payload.get("name") is not None:
            target.display_name = payload["name"]
        if payload.get("username") is not None:
            target.username = payload["username"]
        if payload.get("active") is not None:
            target.active = payload["active"]
        target.permissions = permissions
        if payload.get("password"):
            target.password_hash = make_password(str(payload["password"]))
        target.save(
            update_fields=["display_name", "username", "active", "permissions", "password_hash"]
        )
        permissions_for_log = permissions
        if payload.get("active") is False:
            _revoke_admin_sessions(user_id)

    ActivityLog.objects.create(
        actor_id=actor_username,
        action="USER_UPDATED",
        entity_type="USER",
        entity_id=user_id,
        data={
            "username": payload.get("username") or target.username,
            "permissions": permissions_for_log,
        },
        created_at=timezone.now(),
    )
    return {"ok": True}


def delete_admin_user(user_id: str, actor_user_id: str, actor_username: str) -> dict:
    """`DELETE /api/admin/users/[id]`."""
    if user_id == actor_user_id:
        return {"error": "You cannot delete your own account", "status": 400}

    target = User.objects.filter(pk=user_id).first()
    if target is None:
        return {"error": "User not found", "status": 404}

    if str(target.role).lower() == "admin":
        return {"error": "The primary Admin account cannot be deleted", "status": 403}

    username = target.username
    _revoke_admin_sessions(user_id)
    target.delete()
    ActivityLog.objects.create(
        actor_id=actor_username,
        action="USER_DELETED",
        entity_type="USER",
        entity_id=user_id,
        data={"username": username},
        created_at=timezone.now(),
    )
    return {"ok": True}


def _revoke_admin_sessions(user_id: str) -> None:
    """`delete from sessions where kind='admin' and subject_id=$1` — the
    legacy hashed-token `sessions` table has no Stage A binding yet
    (Django's own session engine backs `tt_admin`/`tt_customer` instead,
    design decision #5), so there is no live table to delete rows from
    for this port; matches the fact that no login view exists yet to
    populate that table in the first place (see
    `apps/accounts/authentication.py`'s module docstring)."""


def _random_id(prefix: str) -> str:
    from apps.checkout.services import random_id

    return random_id(prefix)
