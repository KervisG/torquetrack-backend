"""`Customer` es el perfil comercial: nombre, empresa, teléfono, dirección y
datos fiscales dentro de `data`. Pedidos y cotizaciones apuntan aquí.

Las credenciales viven solo en `apps.auth.User`. `user` es opcional: un
cliente de checkout invitado no tiene cuenta. Los certificados de exención
siguen en base64 dentro de `data`.
"""
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class Customer(models.Model):
    id = models.TextField(primary_key=True)
    user = models.OneToOneField(
        "tt_auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer",
    )
    email = models.TextField(null=True, blank=True)
    data = models.JSONField(default=dict)
    # Token del enlace de invitación al portal (`portal-invite` → `/activate`).
    activation_token_hash = models.TextField(null=True, blank=True)
    activation_expires_at = models.DateTimeField(null=True, blank=True)
    tax_status = models.TextField(default="NOT SUBMITTED", db_default="NOT SUBMITTED")
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "customers"
        permissions = [
            ("review_tax_exemption", "Can review tax exemptions"),
        ]
        constraints = [
            # El checkout invitado resuelve el perfil por email, así que entre
            # invitados el email sigue siendo único. Un perfil registrado puede
            # repetirlo: el registro nunca se adueña de un invitado existente.
            models.UniqueConstraint(
                fields=["email"],
                condition=Q(user__isnull=True),
                name="customers_guest_email_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.email or self.id
