from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class ProductImage(models.Model):
    """Una foto de la galería del producto. La de `position` 0 es la portada,
    que `Product.data["image"]` repite para el catálogo y el carrito."""

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="images")
    position = models.PositiveSmallIntegerField()
    # Nombre del objeto en Spaces: con él se borra.
    key = models.TextField(unique=True)
    url = models.TextField()
    alt = models.TextField(blank=True, default="", db_default="")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "product_images"
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.key
