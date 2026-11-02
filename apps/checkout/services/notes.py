"""Notas internas de los pedidos desde el panel.

Sirven para dejar rastro de dónde se pidió la pieza, verificaciones y el
seguimiento del pedido. Viven en `Order.data["internalNotes"]`, como los casos
de core y devolución, y son de solo agregar: cada nota guarda quién la
escribió y cuándo, y nunca se editan ni se borran. Solo las devuelve el panel;
el portal del cliente arma su JSON con una lista cerrada de campos.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import Order
from apps.common.ids import random_id

INTERNAL_NOTES_KEY = "internalNotes"
MAX_NOTE_LENGTH = 2000

NOTE_REQUIRED = "Note is required"
NOTE_TOO_LONG = f"Note must be {MAX_NOTE_LENGTH} characters or fewer"
ORDER_NOT_FOUND = "Order not found"


def add_order_note(order_id: str, payload, actor_email: str) -> dict | tuple[dict, int]:
    """`({"note": ...}, 201)`, o `{"error": ..., "status": ...}`."""
    raw_body = payload.get("body") if isinstance(payload, dict) else None
    body = raw_body.strip() if isinstance(raw_body, str) else ""
    if not body:
        return {"error": NOTE_REQUIRED, "status": 400}
    if len(body) > MAX_NOTE_LENGTH:
        return {"error": NOTE_TOO_LONG, "status": 400}

    note = {
        "id": random_id("note_"),
        "body": body,
        "by": actor_email,
        "at": timezone.now().isoformat(),
    }
    with transaction.atomic():
        # Fila bloqueada: dos notas a la vez no se pisan la lista.
        order = Order.objects.select_for_update().filter(pk=order_id).first()
        if order is None:
            return {"error": ORDER_NOT_FOUND, "status": 404}
        data = dict(order.data or {})
        data[INTERNAL_NOTES_KEY] = [*(data.get(INTERNAL_NOTES_KEY) or []), note]
        order.data = data
        order.updated_at = timezone.now()
        order.save(update_fields=["data", "updated_at"])

    record_activity(
        actor=actor_email,
        action="ORDER_NOTE_ADDED",
        entity_type="ORDER",
        entity_id=order.pk,
        data={"number": order.number, "noteId": note["id"]},
    )
    return {"note": note}, 201
