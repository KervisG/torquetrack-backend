"""El `id` lo genera el servidor y el cliente nunca lo elige. Un carrito
invitado vive en la sesión (`cart_id`, sin `user`); el de una cuenta cuelga de
`user` y se encuentra por la cuenta, desde cualquier dispositivo."""
from django.conf import settings
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


# La etapa y el estado viven en `Cart.data`, sin columna.
class CartStage(models.TextChoices):
    CART = "CART"
    CHECKOUT = "CHECKOUT"
    BUILDING_QUOTE = "BUILDING_QUOTE"


class CartStatus(models.TextChoices):
    """Lo que ven el storefront y el panel: una etapa CART se muestra ACTIVE o
    ABANDONED según su inactividad; las demás etapas se muestran tal cual."""

    ACTIVE = "ACTIVE"
    ABANDONED = "ABANDONED"
    CHECKOUT = "CHECKOUT"
    BUILDING_QUOTE = "BUILDING_QUOTE"
    EMPTY = "EMPTY"


class Cart(models.Model):
    id = models.TextField(primary_key=True)
    # CASCADE: sin su dueño el carrito no lo alcanza nadie (una sesión anónima
    # nunca lee un carrito con `user`) y es dato personal de la cuenta.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="carts",
    )
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "carts"
        # Un carrito por cuenta: la fila se reutiliza entre compras (la etapa
        # vive en `data`) y se borra al vaciarse, así que nunca hay un carrito
        # "convertido" que conservar junto al activo. Los invitados (`NULL`)
        # no chocan entre sí.
        constraints = [
            models.UniqueConstraint(fields=["user"], name="carts_one_per_user"),
        ]

    def __str__(self) -> str:
        return self.id
