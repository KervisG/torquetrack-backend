from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class ProductLine(models.TextChoices):
    """Sección de la portada donde sale una categoría. Los valores son el
    contrato con el SPA, que les pone título y descripción."""

    FUEL_SYSTEM = "FUEL_SYSTEM", "Fuel system"
    TURBO_AIR = "TURBO_AIR", "Turbo & air"
    EMISSIONS = "EMISSIONS", "Emission systems"
    OTHER = "OTHER", "More parts"


class Category(models.Model):
    """Una categoría de piezas. Los productos la llevan como texto en
    `Product.category`, escrito de varias formas (`Injector`, `Fuel
    Injectors`): el cruce es por `value`, la forma canónica, y no una FK."""

    name = models.TextField()
    value = models.TextField(unique=True)
    line = models.TextField(
        choices=ProductLine.choices, default=ProductLine.OTHER, db_default=ProductLine.OTHER
    )
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
