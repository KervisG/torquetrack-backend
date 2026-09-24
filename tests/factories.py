"""Los permisos se piden con el string del catálogo (`products.view`) y se
traducen al `Permission` del modelo de dominio."""
from importlib import import_module

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import ActivityLog
from apps.auth.models import Role, User
from apps.auth.permission_catalog import CODE_TO_PERMISSION
from apps.auth.sessions import CART_SESSION_KEY, SESSION_USER_KEY
from apps.customers.models import Customer

DEFAULT_PASSWORD = "diesel-pass-123"


def create_role(slug, *, permissions=(), full_access=False, name=None) -> Role:
    role = Role.objects.create(name=name or slug, slug=slug, full_access=full_access)
    resolved = []
    for codename in permissions:
        app_label, django_codename = CODE_TO_PERMISSION[codename]
        resolved.append(
            Permission.objects.get(
                content_type__app_label=app_label, codename=django_codename
            )
        )
    role.permissions.set(resolved)
    return role


def create_user(
    user_id,
    *,
    email=None,
    password=None,
    role=None,
    active=True,
    first_name="",
    last_name="",
) -> User:
    # Sin `password` se guarda un hash inutilizable: PBKDF2 es lento y la
    # mayoría de los tests no pasa por el login.
    return User.objects.create(
        id=user_id,
        email=email or f"{user_id}@example.com",
        password_hash=make_password(password),
        role=role,
        active=active,
        first_name=first_name,
        last_name=last_name,
    )


def create_staff_user(
    user_id,
    *,
    permissions=None,
    full_access=False,
    active=True,
    email=None,
    password=None,
) -> User:
    role = create_role(
        f"role-{user_id}", permissions=permissions or [], full_access=full_access
    )
    return create_user(
        user_id, email=email, password=password, role=role, active=active
    )


def create_customer(customer_id, *, email=None, user=None, data=None, **fields) -> Customer:
    now = timezone.now()
    return Customer.objects.create(
        id=customer_id,
        email=email,
        user=user,
        data=data or {},
        created_at=now,
        updated_at=now,
        **fields,
    )


def session_client(user_id, *, enforce_csrf=False):
    """Devuelve `(client, session_key)` con la cookie de sesión ya puesta."""
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store[SESSION_USER_KEY] = user_id
    store.save()
    client = APIClient(enforce_csrf_checks=enforce_csrf)
    client.cookies[settings.SESSION_COOKIE_NAME] = store.session_key
    return client, store.session_key


def guest_cart_client(cart_id):
    """`APIClient` anónimo cuya sesión ya tiene `cart_id` como carrito propio."""
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store[CART_SESSION_KEY] = cart_id
    store.save()
    client = APIClient()
    client.cookies[settings.SESSION_COOKIE_NAME] = store.session_key
    return client


def activity_count(**filters) -> int:
    """Existe para que los tests de otras apps no importen `ActivityLog`: fuera
    de `apps/audit` solo se usa `record_activity`."""
    return ActivityLog.objects.filter(**filters).count()
