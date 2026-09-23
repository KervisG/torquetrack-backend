"""Cuentas: credenciales, alta pública y la forma del usuario de sesión."""
from __future__ import annotations

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auth.models import Role, User
from apps.auth.permissions import is_staff_user, permission_codenames_for_role
from apps.checkout.services import random_id


def compose_display_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part)


def split_full_name(name: str) -> tuple[str, str]:
    parts = str(name or "").strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def parse_email(raw) -> str | None:
    email = str(raw or "").strip().lower()
    if not email:
        return None
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def password_error(password: str, user: User) -> str | None:
    """Corre `AUTH_PASSWORD_VALIDATORS` y devuelve el mensaje, o `None`."""
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return " ".join(exc.messages)
    return None


def authenticate_user(email, password) -> User | None:
    """`POST /api/login/`. Clientes y staff entran por el mismo lado."""
    normalized = str(email or "").strip().lower()
    user = (
        User.objects.select_related("role").filter(email=normalized, active=True).first()
        if normalized
        else None
    )
    if user is None:
        # Igual que `ModelBackend`: hashear igual para que el tiempo de
        # respuesta no revele qué correos tienen cuenta.
        make_password(str(password or ""))
        return None

    try:
        matches = check_password(str(password or ""), user.password_hash)
    except ValueError:
        return None
    return user if matches else None


def serialize_session_user(user: User) -> dict:
    """Forma del usuario en `/api/session/`, `/api/login/` y `/api/register/`."""
    first_name, last_name = user.given_names()
    role = user.role if user.role_id is not None else None
    return {
        "id": user.pk,
        "email": user.email,
        "firstName": first_name,
        "lastName": last_name,
        "isStaff": is_staff_user(user),
        "role": serialize_role(role) if role is not None else None,
        "permissions": permission_codenames_for_role(role),
    }


def serialize_role(role: Role) -> dict:
    return {"slug": role.slug, "name": role.name, "fullAccess": role.full_access}


def create_account(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    role: Role | None = None,
    display_name: str | None = None,
) -> dict:
    """Crea el `User` con la contraseña ya validada. Lo usan el registro,
    la activación del portal y el alta de staff.

    Devuelve `{"user": user}` o `{"error", "status"}`. Debe correr dentro de
    la transacción de quien lo llama si hay más filas que crear juntas.
    """
    candidate = User(
        id=random_id("U"),
        email=email,
        first_name=first_name,
        last_name=last_name,
        display_name=display_name or compose_display_name(first_name, last_name),
        role=role,
        active=True,
        created_at=timezone.now(),
    )
    error = password_error(str(password), candidate)
    if error is not None:
        return {"error": error, "status": 400}
    if User.objects.filter(email=email).exists():
        return {"error": "Email already exists", "status": 409}

    candidate.password_hash = make_password(str(password))
    try:
        with transaction.atomic():
            candidate.save(force_insert=True)
    except IntegrityError:
        return {"error": "Email already exists", "status": 409}
    return {"user": candidate}


def register_customer(payload: dict) -> dict:
    """`POST /api/register/` — cuenta sin Role más un Customer nuevo.

    Nunca se vincula un Customer invitado existente con el mismo email: el
    correo no está verificado, así que adueñarse de ese perfil le daría a
    cualquiera el historial de pedidos y cotizaciones de otra persona. El
    invitado entra a su historial solo por el enlace de `portal-invite`.
    """
    from apps.customers.models import Customer

    email = parse_email(payload.get("email"))
    password = payload.get("password")
    name = str(payload.get("name") or "").strip()
    if email is None or not isinstance(password, str) or not password or not name:
        return {"error": "Email, password and name required", "status": 400}

    company = str(payload.get("company") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    first_name, last_name = split_full_name(name)

    with transaction.atomic():
        result = create_account(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            display_name=name,
        )
        if "error" in result:
            return result
        user = result["user"]
        customer_id = random_id("C")
        now = timezone.now()
        Customer.objects.create(
            id=customer_id,
            user=user,
            email=email,
            data={
                "id": customer_id,
                "email": email,
                "name": name,
                "company": company,
                "phone": phone,
            },
            created_at=now,
            updated_at=now,
        )
    return {"user": user}
