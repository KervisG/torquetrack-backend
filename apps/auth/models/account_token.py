"""Tokens de un solo uso que viajan por correo: restablecer la contraseña,
verificar el email y activar la invitación al portal.

Solo se guarda el SHA-256 del token; el valor en claro existe únicamente en
el enlace del correo, así que una copia de la base no sirve para usarlos.
`email` fija el correo al que se mandó el enlace: si la cuenta (o el perfil
invitado) cambia de email, el token deja de valer. La activación no tiene
`user` porque la cuenta todavía no existe: la liga el email del `Customer`
invitado, que es único entre invitados.
"""
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now
from django.utils import timezone


class AccountToken(models.Model):
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"
    ACTIVATION = "activation"
    PURPOSES = [
        (PASSWORD_RESET, "Password reset"),
        (EMAIL_VERIFICATION, "Email verification"),
        (ACTIVATION, "Portal activation"),
    ]

    user = models.ForeignKey(
        "tt_auth.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="account_tokens",
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
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False) | Q(purpose="activation"),
                name="account_tokens_user_required",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.purpose} for {self.user_id or self.email}"
