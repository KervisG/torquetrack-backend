from django.db import models
from django.db.models.functions import Lower, Now
from django.utils import timezone


class Brand(models.Model):
    """Una marca de piezas (Bosch, Garrett). Los productos la llevan por nombre
    en `Product.manufacturer`, que admite varias (`Alliant Power / Bosch`): por
    eso no hay FK y el nombre es único sin distinguir mayúsculas."""

    name = models.TextField()
    # Nombre del objeto en Spaces: con él se borra. Vacío es "sin logo".
    logo_key = models.TextField(blank=True, default="", db_default="")
    logo_url = models.TextField(blank=True, default="", db_default="")
    active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "brands"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="brands_name_unique"),
        ]

    def __str__(self) -> str:
        return self.name
