"""Perfil comercial; las credenciales viven solo en `apps.authentication.User` y un
cliente invitado no tiene cuenta."""
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class TaxStatus(models.TextChoices):
    """Solo `VERIFIED` exime de impuestos (`is_tax_exempt`)."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    PENDING_VERIFICATION = "PENDING VERIFICATION"
    NOT_SUBMITTED = "NOT SUBMITTED"


class PortalStatus(models.TextChoices):
    """Se deriva al serializar (`portal_status`), sin columna."""

    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    NOT_ACTIVATED = "NOT ACTIVATED"


# Claves del perfil que tienen columna; coinciden con el nombre de la columna.
# Lo demás (la exención de impuestos y sus datos) queda en `details`.
PROFILE_COLUMNS = ("name", "company", "phone", "address1", "address2", "city", "state", "zip")


class Customer(models.Model):
    id = models.TextField(primary_key=True)
    user = models.OneToOneField(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer",
    )
    email = models.TextField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)
    company = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    address1 = models.TextField(null=True, blank=True)
    address2 = models.TextField(null=True, blank=True)
    city = models.TextField(null=True, blank=True)
    state = models.TextField(null=True, blank=True)
    zip = models.TextField(null=True, blank=True)
    details = models.JSONField(default=dict)
    tax_status = models.TextField(
        choices=TaxStatus, default=TaxStatus.NOT_SUBMITTED, db_default=TaxStatus.NOT_SUBMITTED
    )
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

    @property
    def data(self) -> dict:
        """La forma que consumen la API, el checkout y el panel: `details`
        más las columnas del perfil que tienen valor."""
        merged = dict(self.details or {})
        for column in PROFILE_COLUMNS:
            value = getattr(self, column)
            if value is not None:
                merged[column] = value
        return merged

    @data.setter
    def data(self, value: dict) -> None:
        """Reemplaza todo: un campo del perfil ausente o vacío queda en `None`."""
        remaining = dict(value or {})
        for column in PROFILE_COLUMNS:
            column_value = remaining.pop(column, None)
            setattr(self, column, None if column_value in (None, "") else str(column_value))
        self.details = remaining

    def save(self, *args, **kwargs):
        # Quien guarda `data` guarda lo que la propiedad repartió.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "data" in update_fields:
            kwargs["update_fields"] = [
                *(field for field in update_fields if field != "data"),
                *PROFILE_COLUMNS,
                "details",
            ]
        super().save(*args, **kwargs)
