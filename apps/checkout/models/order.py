from urllib.parse import quote

from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class OrderStatus(models.TextChoices):
    OPEN = "OPEN"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderPaymentStatus(models.TextChoices):
    """Resumen del cobro del pedido; lo reembolsado sigue contando como
    cobrado (`CHARGED_PAYMENT_STATUSES`)."""

    UNPAID = "UNPAID"
    PAID = "PAID"
    FAILED = "FAILED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


# Los casos de core y de devolución viven en `Order.data` (`coreCase`,
# `returnCase`), sin columna propia; los valores con espacio son el contrato
# del panel.
class CoreStatus(models.TextChoices):
    AWAITING_CORE = "AWAITING CORE"
    IN_TRANSIT = "IN TRANSIT"
    RECEIVED = "RECEIVED"
    INSPECTING = "INSPECTING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"


class ReturnStatus(models.TextChoices):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_TRANSIT = "IN TRANSIT"
    RECEIVED = "RECEIVED"
    INSPECTING = "INSPECTING"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"


class FulfillmentStatus(models.TextChoices):
    """Envío del pedido, separado de `Order.status`: avanzar el envío no cierra
    ni reabre el pedido. Las transiciones van solo hacia adelante
    (`FULFILLMENT_TRANSITIONS` en `services/fulfillment.py`)."""

    UNFULFILLED = "UNFULFILLED"
    PREPARING = "PREPARING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class Carrier(models.TextChoices):
    UPS = "UPS", "UPS"
    FEDEX = "FEDEX", "FedEx"
    USPS = "USPS", "USPS"
    OTHER = "OTHER", "Other"


# Páginas públicas de seguimiento de cada transportista. `OTHER` no tiene
# enlace: el cliente recibe solo el número de guía.
TRACKING_URL_TEMPLATES = {
    Carrier.UPS: "https://www.ups.com/track?tracknum={}",
    Carrier.FEDEX: "https://www.fedex.com/fedextrack/?trknbr={}",
    Carrier.USPS: "https://tools.usps.com/go/TrackConfirmAction?tLabels={}",
}


class Order(models.Model):
    id = models.TextField(primary_key=True)
    number = models.TextField(unique=True)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    status = models.TextField(
        choices=OrderStatus, default=OrderStatus.OPEN, db_default=OrderStatus.OPEN
    )
    payment_status = models.TextField(
        choices=OrderPaymentStatus,
        default=OrderPaymentStatus.UNPAID,
        db_default=OrderPaymentStatus.UNPAID,
    )
    fulfillment_status = models.TextField(
        choices=FulfillmentStatus,
        default=FulfillmentStatus.UNFULFILLED,
        db_default=FulfillmentStatus.UNFULFILLED,
    )
    carrier = models.TextField(choices=Carrier, blank=True, default="", db_default="")
    tracking_number = models.TextField(blank=True, default="", db_default="")
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "orders"
        permissions = [
            ("change_status", "Can change order status"),
            ("cancel_order", "Can cancel orders"),
            ("manage_cores", "Can manage cores"),
            ("manage_returns", "Can manage returns"),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def tracking_url(self) -> str | None:
        template = TRACKING_URL_TEMPLATES.get(self.carrier)
        if template is None or not self.tracking_number:
            return None
        return template.format(quote(self.tracking_number, safe=""))

    def fulfillment_summary(self) -> dict:
        """Campos del envío para el JSON. Vive en el modelo porque lo
        serializan el panel (`checkout`) y el portal del cliente
        (`customers`), y `customers` llega al pedido por `customer.orders` sin
        poder importar `checkout`."""
        return {
            "fulfillmentStatus": self.fulfillment_status,
            "carrier": self.carrier,
            "trackingNumber": self.tracking_number,
            "trackingUrl": self.tracking_url,
            "shippedAt": self.shipped_at,
            "deliveredAt": self.delivered_at,
        }
