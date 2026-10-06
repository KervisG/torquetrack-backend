from django.db import models


class ProductFitment(models.Model):
    """Un producto es compatible con una aplicación. Es la fuente de verdad del
    fitment: el texto de `Product.data` (marca, años, motor) queda solo como
    respaldo para los productos que todavía no tienen filas."""

    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="fitments"
    )
    application = models.ForeignKey(
        "catalog.Application", on_delete=models.CASCADE, related_name="fitments"
    )

    class Meta:
        db_table = "product_fitments"
        constraints = [
            models.UniqueConstraint(
                fields=["product", "application"], name="product_fitments_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.product_id} -> {self.application_id}"
