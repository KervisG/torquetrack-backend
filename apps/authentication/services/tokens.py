"""Enlaces por correo: emitir, bloquear e invalidar filas de `AccountToken`
(reset de contraseña, verificación del email e invitación al portal) y
entregar el correo que lleva el enlace fuera del request."""
from __future__ import annotations

import logging
import secrets

from django.utils import timezone

from apps.authentication.models import AccountToken, User
from apps.authentication.utils.background import run_in_background
from apps.common.emails import branded_email_html
from apps.common.tokens import hash_token
from apps.integrations.email import resend

logger = logging.getLogger(__name__)

PASSWORD_RESET_TTL = timezone.timedelta(hours=1)
EMAIL_VERIFICATION_TTL = timezone.timedelta(hours=48)
ACTIVATION_TTL = timezone.timedelta(days=7)
_TOKEN_TTL = {
    AccountToken.PASSWORD_RESET: PASSWORD_RESET_TTL,
    AccountToken.EMAIL_VERIFICATION: EMAIL_VERIFICATION_TTL,
    AccountToken.ACTIVATION: ACTIVATION_TTL,
}


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
    """Solo vale el último enlace de cada tipo: pedir uno nuevo anula los
    pendientes del mismo propósito, igual que la invitación al portal."""
    AccountToken.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(
        used_at=timezone.now()
    )
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
    """Igual que `lock_account_token` pero sin `user`: quien llama resuelve el
    perfil por `record.email` y marca `used_at` en la misma transacción."""
    if not isinstance(token, str) or not token:
        return None
    return (
        _pending_tokens(AccountToken.ACTIVATION)
        .select_for_update()
        .filter(token_hash=hash_token(token))
        .first()
    )


def lock_account_token(token, purpose: str) -> AccountToken | None:
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


def send_account_email(user: User, subject: str, html: str) -> None:
    """La respuesta no puede depender del envío: en el reset, esperar a Resend
    solo cuando la cuenta existe revelaría por el tiempo de respuesta qué
    correos están registrados. Por eso el hilo recibe el correo ya armado y no
    toca la base. Quien llama ya confirmó el token, así que el enlace nunca
    apunta a una fila revertida. `html` es el cuerpo armado con `format_html`;
    el layout de marca se agrega aquí para todos los correos de cuenta.
    """
    run_in_background(
        _deliver_account_email, user.pk, user.email, subject, branded_email_html(html)
    )
