"""Tokens de un solo uso que viajan por correo: restablecer la contraseña y
verificar el email.

Solo se guarda el SHA-256 del token; el valor en claro existe únicamente en
el enlace del correo, así que una copia de la base no sirve para usarlos.
`email` fija el correo al que se mandó el enlace: si la cuenta cambia de
email, el token deja de valer.
"""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class AccountToken(models.Model):
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"
    PURPOSES = [
        (PASSWORD_RESET, "Password reset"),
        (EMAIL_VERIFICATION, "Email verification"),
    ]

    user = models.ForeignKey(
        "tt_auth.User", on_delete=models.CASCADE, related_name="account_tokens"
    )
    purpose = models.TextField(choices=PURPOSES)
    token_hash = models.TextField(unique=True)
    email = models.TextField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "account_tokens"
        default_permissions = ()
        indexes = [models.Index(fields=["user", "purpose"], name="account_tokens_user_purpose")]

    def __str__(self) -> str:
        return f"{self.purpose} for {self.user_id}"
