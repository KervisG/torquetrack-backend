"""Cuentas: credenciales, alta de `User`, la forma del usuario de sesión y los
enlaces por correo (restablecer contraseña, verificar el email y activar la
invitación al portal). El perfil `Customer` es de `apps.customers`, que
depende de esta app y no al revés."""
from __future__ import annotations

import logging
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import escape

from apps.auth.models import AccountToken, Role, User, compose_display_name
from apps.auth.permissions import is_staff_user, permission_codenames_for_role
from apps.auth.utils.background import run_in_background
from apps.common.ids import random_id
from apps.common.links import app_url
from apps.common.tokens import hash_token
from apps.integrations.email import resend

logger = logging.getLogger(__name__)


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
    """Clientes y staff entran por el mismo lado."""
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
    """Forma compartida por las respuestas de sesión, login y registro."""
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
        "emailVerified": user.email_verified_at is not None,
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
    """Devuelve `{"user": user}` o `{"error", "status"}`. Debe correr dentro de
    la transacción de quien lo llama si hay más filas que crear juntas."""
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


# --- enlaces por correo: reset de contraseña, verificación y activación -----

PASSWORD_RESET_TTL = timezone.timedelta(hours=1)
EMAIL_VERIFICATION_TTL = timezone.timedelta(hours=48)
ACTIVATION_TTL = timezone.timedelta(days=7)
_TOKEN_TTL = {
    AccountToken.PASSWORD_RESET: PASSWORD_RESET_TTL,
    AccountToken.EMAIL_VERIFICATION: EMAIL_VERIFICATION_TTL,
    AccountToken.ACTIVATION: ACTIVATION_TTL,
}
PASSWORD_RESET_REQUESTED = {
    "ok": True,
    "message": "If an account exists for that email, we sent a link to reset the password.",
}
_INVALID_RESET = {"error": "Invalid or expired reset link", "status": 400}


def _create_token(purpose: str, email: str, user: User | None = None) -> str:
    """Devuelve el valor en claro, que solo debe viajar en el enlace del correo."""
    token = secrets.token_urlsafe(32)
    AccountToken.objects.create(
        user=user,
        purpose=purpose,
        token_hash=hash_token(token),
        email=email,
        expires_at=timezone.now() + _TOKEN_TTL[purpose],
    )
    return token


def issue_account_token(user: User, purpose: str) -> str:
    return _create_token(purpose, user.email, user)


def issue_activation_token(email: str) -> str:
    """Un perfil tiene una sola invitación vigente: la nueva anula las
    anteriores, así un enlace viejo reenviado por error ya no activa."""
    AccountToken.objects.filter(
        purpose=AccountToken.ACTIVATION, email=email, used_at__isnull=True
    ).update(used_at=timezone.now())
    return _create_token(AccountToken.ACTIVATION, email)


def _pending_tokens(purpose: str):
    return AccountToken.objects.filter(
        purpose=purpose, used_at__isnull=True, expires_at__gt=timezone.now()
    )


def invited_emails(emails) -> set[str]:
    """Emails con una invitación al portal vigente, en una sola consulta."""
    return set(
        _pending_tokens(AccountToken.ACTIVATION)
        .filter(email__in=[email for email in emails if email])
        .values_list("email", flat=True)
    )


def lock_activation_token(token) -> AccountToken | None:
    """Igual que `_lock_account_token` pero sin `user`: quien llama resuelve el
    perfil por `record.email` y marca `used_at` en la misma transacción."""
    if not isinstance(token, str) or not token:
        return None
    return (
        _pending_tokens(AccountToken.ACTIVATION)
        .select_for_update()
        .filter(token_hash=hash_token(token))
        .first()
    )


def _lock_account_token(token, purpose: str) -> AccountToken | None:
    """Bloquea y devuelve el token vigente, o `None`. Debe correr dentro de
    una transacción: el `select_for_update` evita que dos requests
    simultáneos usen el mismo enlace."""
    if not isinstance(token, str) or not token:
        return None
    record = (
        _pending_tokens(purpose)
        .select_for_update()
        .select_related("user")
        # Con el filtro el join es INNER: Postgres no admite FOR UPDATE sobre
        # el lado nullable de un LEFT JOIN y así se bloquea también el `User`.
        .filter(token_hash=hash_token(token), user__isnull=False)
        .first()
    )
    if record is None:
        return None
    # El enlace se mandó a `record.email`: si la cuenta cambió de correo o
    # quedó inactiva, deja de valer.
    if not record.user.active or record.user.email != record.email:
        return None
    return record


def invalidate_password_reset_tokens(user_id: str) -> None:
    """Todo cambio de contraseña deja sin efecto los enlaces de reset
    pendientes: un correo viejo no puede volver a pisar la contraseña nueva."""
    AccountToken.objects.filter(
        user_id=user_id, purpose=AccountToken.PASSWORD_RESET, used_at__isnull=True
    ).update(used_at=timezone.now())


def _deliver_account_email(user_id: str, email: str, subject: str, html: str) -> None:
    result = resend.send_email(to=email, subject=subject, html=html)
    if not result.get("sent"):
        logger.warning(
            "Account email %r to user %s not sent: %s", subject, user_id, result.get("reason")
        )


def _send_account_email(user: User, subject: str, html: str) -> None:
    """La respuesta no puede depender del envío: en el reset, esperar a Resend
    solo cuando la cuenta existe revelaría por el tiempo de respuesta qué
    correos están registrados. Por eso el hilo recibe el correo ya armado y no
    toca la base. Quien llama ya confirmó el token, así que el enlace nunca
    apunta a una fila revertida.
    """
    run_in_background(_deliver_account_email, user.pk, user.email, subject, html)


def request_password_reset(payload: dict) -> dict:
    """Siempre devuelve el mismo body, exista o no la cuenta, para no permitir
    enumerar correos."""
    email = parse_email(payload.get("email"))
    user = User.objects.filter(email=email, active=True).first() if email else None
    if user is not None:
        token = issue_account_token(user, AccountToken.PASSWORD_RESET)
        link = escape(app_url(f"/reset-password?token={token}"))
        _send_account_email(
            user,
            "Reset your TorqueTrack password",
            (
                "<p>We received a request to reset the password of your TorqueTrack "
                "account.</p>"
                f'<p><a href="{link}">Reset your password</a></p>'
                "<p>This link expires in 1 hour and can be used only once. If you did "
                "not ask for it, you can ignore this email.</p>"
            ),
        )
    return dict(PASSWORD_RESET_REQUESTED)


def confirm_password_reset(payload: dict) -> dict:
    from apps.auth.sessions import revoke_user_sessions

    password = payload.get("password")
    with transaction.atomic():
        record = _lock_account_token(payload.get("token"), AccountToken.PASSWORD_RESET)
        if record is None:
            return dict(_INVALID_RESET)
        if not isinstance(password, str) or not password:
            return {"error": "Password required", "status": 400}
        user = record.user
        # Una contraseña rechazada no consume el enlace: la persona puede
        # reintentar con una más fuerte.
        error = password_error(password, user)
        if error is not None:
            return {"error": error, "status": 400}

        user.password_hash = make_password(password)
        user.save(update_fields=["password_hash"])
        invalidate_password_reset_tokens(user.pk)
    revoke_user_sessions(user.pk)
    return {"ok": True}


def send_verification_email(user: User) -> None:
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)
    link = escape(app_url(f"/verify-email?token={token}"))
    _send_account_email(
        user,
        "Verify your TorqueTrack email",
        (
            "<p>Confirm that this is your email to finish setting up your TorqueTrack "
            "account.</p>"
            f'<p><a href="{link}">Verify your email</a></p>'
            "<p>Once verified, past orders and quotes placed with this email are "
            "added to your account. This link expires in 48 hours.</p>"
        ),
    )


def resend_verification_email(user: User) -> dict:
    if user.email_verified_at is not None:
        return {"ok": True, "emailVerified": True}
    send_verification_email(user)
    return {"ok": True, "emailVerified": False}


def consume_email_verification(token) -> User | None:
    """Marca el email como verificado y consume los enlaces pendientes, o
    devuelve `None`. Debe correr dentro de la transacción de quien llama, que
    en la misma transacción vincula el historial de compras."""
    record = _lock_account_token(token, AccountToken.EMAIL_VERIFICATION)
    if record is None:
        return None
    now = timezone.now()
    user = record.user
    user.email_verified_at = user.email_verified_at or now
    user.save(update_fields=["email_verified_at"])
    AccountToken.objects.filter(
        user=user, purpose=AccountToken.EMAIL_VERIFICATION, used_at__isnull=True
    ).update(used_at=now)
    return user
