"""Clientes: panel de staff, autoservicio de la cuenta y activación del portal."""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.services import random_id
from apps.customers.models import Customer

ALLOWED_TAX_STATUSES = [
    "VERIFIED",
    "REJECTED",
    "EXPIRED",
    "PENDING VERIFICATION",
    "NOT SUBMITTED",
]


def _serialize_customer_masked(customer: Customer) -> dict:
    """Las columnas van después de `data` para que una clave vieja de `data`
    (`id`, `email`, `taxStatus`...) nunca tape el valor real."""
    data = customer.data or {}
    raw_tax_id = str(data.get("taxId") or "")
    tax_id_masked = ("•" * max(0, len(raw_tax_id) - 4) + raw_tax_id[-4:]) if raw_tax_id else ""
    excluded_keys = ("taxId", "certificateData")
    safe_data = {key: value for key, value in data.items() if key not in excluded_keys}
    return {
        **safe_data,
        "id": customer.pk,
        "email": customer.email,
        "portalStatus": portal_status(customer),
        "taxStatus": customer.tax_status,
        "taxIdMasked": tax_id_masked,
    }


def list_admin_customers() -> list[dict]:
    customers = Customer.objects.order_by("created_at")
    return [_serialize_customer_masked(customer) for customer in customers]


def upsert_admin_customer(payload: dict) -> dict:
    """Solo guarda en `data` los campos de perfil: el estado fiscal, el
    certificado y el portal tienen su propio flujo."""
    patch, error = _profile_patch(payload)
    if error is not None:
        return error

    email = str(payload.get("email") or "").strip().lower()
    customer_id = str(payload.get("id") or "")
    reused = False

    if not customer_id and email:
        existing = Customer.objects.filter(email__iexact=email).first()
        if existing is not None:
            customer_id = existing.pk
            reused = True

    if customer_id:
        customer = Customer.objects.filter(pk=customer_id).first()
        if customer is None:
            return {"error": "Customer not found", "status": 404}
        if email and Customer.objects.filter(email__iexact=email).exclude(pk=customer_id).exists():
            return {"error": "That email already belongs to another customer.", "status": 409}

        customer.email = email or None
        customer.data = {**(customer.data or {}), **patch}
        customer.updated_at = timezone.now()
        customer.save(update_fields=["email", "data", "updated_at"])
    else:
        customer = Customer.objects.create(
            id=random_id("C"),
            email=email or None,
            data=patch,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

    return {
        "customer": _serialize_customer_masked(customer),
        "reusedExistingCustomer": reused,
    }


def delete_admin_customer(customer_id: str) -> dict:
    if not customer_id:
        return {"error": "Customer required", "status": 400}

    deleted, _ = Customer.objects.filter(pk=customer_id).delete()
    if not deleted:
        return {"error": "Customer not found", "status": 404}
    return {"ok": True, "deletedCustomerId": customer_id}


def get_customer_tax_exemption(customer_id: str) -> dict:
    customer = Customer.objects.filter(pk=customer_id).first()
    if customer is None:
        return {"error": "Customer not found", "status": 404}

    data = customer.data or {}
    return {
        "id": customer.pk,
        "email": customer.email,
        "status": customer.tax_status or "NOT SUBMITTED",
        "tax": {
            "company": data.get("taxCompany") or "",
            "taxId": data.get("taxId") or "",
            "taxState": data.get("taxState") or "",
            "taxExemptionType": data.get("taxExemptionType") or "",
            "certificateName": data.get("certificateName") or "",
            "certificateData": data.get("certificateData") or "",
            "submittedAt": data.get("taxSubmittedAt"),
            "reviewedAt": data.get("taxReviewedAt"),
            "reviewedBy": data.get("taxReviewedBy"),
        },
    }


def update_customer_tax_status(customer_id: str, payload: dict, reviewer_email: str) -> dict:
    status = str(payload.get("status") or "").strip().upper()
    if status not in ALLOWED_TAX_STATUSES:
        return {"error": "Invalid tax status", "status": 400}

    customer = Customer.objects.filter(pk=customer_id).first()
    if customer is None:
        return {"error": "Customer not found", "status": 404}

    reviewed_at = timezone.now().isoformat()
    patch = (
        {}
        if status in ("PENDING VERIFICATION", "NOT SUBMITTED")
        else {"taxReviewedAt": reviewed_at, "taxReviewedBy": reviewer_email}
    )

    customer.tax_status = status
    customer.data = {**(customer.data or {}), **patch}
    customer.updated_at = timezone.now()
    customer.save(update_fields=["tax_status", "data", "updated_at"])

    record_activity(
        actor=reviewer_email,
        action="TAX_EXEMPTION_STATUS_CHANGED",
        entity_type="CUSTOMER",
        entity_id=customer_id,
        data={"status": status, "reviewedAt": reviewed_at},
    )
    return {
        "ok": True,
        "status": status,
        "reviewedAt": reviewed_at,
        "reviewedBy": reviewer_email,
    }


def portal_status(customer: Customer) -> str:
    """Se deriva del vínculo con `User` para no tener una columna que
    mantener sincronizada."""
    if customer.user_id is not None:
        return "ACTIVE"
    if customer.activation_token_hash and customer.activation_expires_at and (
        customer.activation_expires_at > timezone.now()
    ):
        return "INVITED"
    return "NOT ACTIVATED"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_portal_invite(payload: dict) -> dict:
    customer_id = payload.get("customerId") or payload.get("id")
    if not customer_id:
        return {"error": "Customer required", "status": 400}

    customer = Customer.objects.filter(pk=str(customer_id)).first()
    if customer is None:
        return {"error": "Customer not found", "status": 404}
    if customer.user_id is not None:
        return {"error": "Customer already has an account", "status": 409}
    if not customer.email:
        return {"error": "Customer email required", "status": 400}

    token = secrets.token_hex(32)
    customer.activation_token_hash = _hash_token(token)
    customer.activation_expires_at = timezone.now() + timezone.timedelta(days=7)
    customer.updated_at = timezone.now()
    customer.save(
        update_fields=["activation_token_hash", "activation_expires_at", "updated_at"]
    )

    base = (settings.APP_URL or "http://localhost:5173").rstrip("/")
    return {"ok": True, "activationUrl": f"{base}/activate?token={token}"}


def activate_customer_account(payload: dict) -> dict:
    from apps.auth.services import create_account, split_full_name

    token = payload.get("token")
    password = payload.get("password")
    invalid = {"error": "Invalid or expired activation link", "status": 400}
    if not isinstance(token, str) or not token or not isinstance(password, str):
        return invalid

    with transaction.atomic():
        customer = (
            Customer.objects.select_for_update()
            .filter(
                activation_token_hash=_hash_token(token),
                activation_expires_at__gt=timezone.now(),
                user__isnull=True,
            )
            .first()
        )
        if customer is None or not customer.email:
            return invalid

        name = str((customer.data or {}).get("name") or "").strip()
        first_name, last_name = split_full_name(name)
        result = create_account(
            email=customer.email.strip().lower(),
            password=password,
            first_name=first_name,
            last_name=last_name,
            display_name=name or None,
        )
        if "error" in result:
            return result

        # La invitación llegó a este correo y quien la abrió eligió la
        # contraseña: eso ya prueba que controla la casilla.
        user = result["user"]
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])

        customer.user = user
        customer.activation_token_hash = None
        customer.activation_expires_at = None
        customer.updated_at = timezone.now()
        customer.save(
            update_fields=[
                "user",
                "activation_token_hash",
                "activation_expires_at",
                "updated_at",
            ]
        )
    return {"user": result["user"]}


# --- autoservicio del cliente ----------------------------------------------

# Campos de perfil en `data`: los únicos que editan el propio cliente y el alta
# de staff. El resto (estado fiscal, certificado, email de la cuenta) tiene su
# propio flujo.
ACCOUNT_PROFILE_FIELDS = (
    "name",
    "company",
    "phone",
    "address1",
    "address2",
    "city",
    "state",
    "zip",
    "country",
)

# El body JSON entero tiene que caber en `DATA_UPLOAD_MAX_MEMORY_SIZE`
# (2.5 MB por defecto) y el base64 ocupa ~4/3 del archivo.
MAX_CERTIFICATE_BYTES = 1_500_000
CERTIFICATE_MIME_TYPES = ("application/pdf", "image/png", "image/jpeg")
_DATA_URL = re.compile(r"^data:([\w.+-]+/[\w.+-]+);base64,(.*)$", re.S)
_INVALID_CERTIFICATE = {"error": "Certificate must be a PDF, PNG or JPEG file", "status": 400}


def customer_for_user(user) -> Customer | None:
    return Customer.objects.filter(user=user).first()


def resolve_guest_customer(snapshot: dict) -> str | None:
    """Un email tipeado no prueba identidad, así que el perfil existente nunca
    se reescribe: los datos del formulario quedan solo en el snapshot del
    pedido o la cotización, y la exención de ese perfil no se aplica (eso lo
    decide quien llama). Se reusa el invitado existente porque el email es
    único entre invitados. Nunca toca un perfil con cuenta.
    """
    email = str(snapshot.get("email") or "").strip()
    if not email:
        return None

    existing = (
        Customer.objects.filter(email__iexact=email, user__isnull=True)
        .order_by("created_at")
        .values_list("pk", flat=True)
        .first()
    )
    if existing:
        return existing

    customer_id = random_id("C")
    try:
        with transaction.atomic():
            Customer.objects.create(
                id=customer_id, email=email, data={**snapshot, "email": email, "id": customer_id}
            )
    except IntegrityError:
        # Otro request creó el mismo invitado entre la lectura y el insert.
        return (
            Customer.objects.filter(email__iexact=email, user__isnull=True)
            .values_list("pk", flat=True)
            .first()
        )
    return customer_id


def link_guest_history(user) -> dict:
    """Solo se llama después de verificar el correo, dentro de esa transacción.

    Se mueven los FKs de `Order` y `Quote` y se borra el invitado en vez de
    fusionar los `data`: pedidos y cotizaciones son lo único que apunta a
    `Customer`, así que no queda ninguna fila huérfana y el perfil que el
    cliente ya editó no se pisa con datos del checkout. Una cuenta sin perfil
    (por ejemplo, staff) adopta el primer invitado.
    """
    from apps.checkout.models import Order
    from apps.quotes.models import Quote

    guests = list(
        Customer.objects.select_for_update()
        .filter(user__isnull=True, email__iexact=user.email)
        .order_by("created_at")
    )
    if not guests:
        return {"linkedOrders": 0, "linkedQuotes": 0}

    own = Customer.objects.select_for_update().filter(user=user).first()
    linked_orders = linked_quotes = 0
    if own is None:
        own = guests.pop(0)
        own.user = user
        own.updated_at = timezone.now()
        own.save(update_fields=["user", "updated_at"])
        linked_orders += Order.objects.filter(customer=own).count()
        linked_quotes += Quote.objects.filter(customer=own).count()

    guest_ids = [guest.pk for guest in guests]
    if guest_ids:
        linked_orders += Order.objects.filter(customer_id__in=guest_ids).update(customer=own)
        linked_quotes += Quote.objects.filter(customer_id__in=guest_ids).update(customer=own)
        Customer.objects.filter(pk__in=guest_ids).delete()
    return {"linkedOrders": linked_orders, "linkedQuotes": linked_quotes}


def serialize_account(customer: Customer) -> dict:
    data = customer.data or {}
    profile = {field: data.get(field) or "" for field in ACCOUNT_PROFILE_FIELDS}
    return {
        "id": customer.pk,
        "email": customer.email,
        **profile,
        "taxStatus": customer.tax_status,
    }


def _profile_patch(payload: dict) -> tuple[dict, dict | None]:
    """`(patch, None)` con los campos de perfil presentes, o `({}, error)`."""
    patch = {}
    for field in ACCOUNT_PROFILE_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if value is None:
            value = ""
        if not isinstance(value, str):
            return {}, {"error": f"{field} must be a string", "status": 400}
        patch[field] = value.strip()[:200]
    return patch, None


def update_account(customer: Customer, payload: dict) -> dict:
    patch, error = _profile_patch(payload)
    if error is not None:
        return error

    if patch:
        customer.data = {**(customer.data or {}), **patch}
        customer.updated_at = timezone.now()
        customer.save(update_fields=["data", "updated_at"])
    return {"customer": serialize_account(customer)}


def list_account_orders(customer: Customer) -> list[dict]:
    from apps.checkout.models import Order

    orders = Order.objects.filter(customer=customer).order_by("-created_at")
    result = []
    for order in orders:
        data = order.data or {}
        result.append(
            {
                "id": order.pk,
                "number": order.number,
                "status": order.status,
                "paymentStatus": order.payment_status,
                "createdAt": order.created_at,
                "items": data.get("items") or [],
                "totals": data.get("totals") or {},
                "vehicle": data.get("vehicle") or {},
                "shipping": data.get("shipping") or {},
            }
        )
    return result


def list_account_quotes(customer: Customer) -> list[dict]:
    from apps.quotes.models import Quote

    quotes = Quote.objects.filter(customer=customer).order_by("-created_at")
    result = []
    for quote in quotes:
        data = quote.data or {}
        result.append(
            {
                "id": quote.pk,
                "number": quote.number,
                "status": quote.status,
                "createdAt": quote.created_at,
                "expiresAt": quote.expires_at,
                "items": data.get("items") or [],
                "totals": data.get("totals") or {},
                "vehicle": data.get("vehicle") or {},
            }
        )
    return result


def _certificate_error(certificate_data: str) -> dict | None:
    match = _DATA_URL.match(certificate_data)
    if match is None or match.group(1).lower() not in CERTIFICATE_MIME_TYPES:
        return _INVALID_CERTIFICATE
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        return _INVALID_CERTIFICATE
    if len(decoded) > MAX_CERTIFICATE_BYTES:
        return {"error": "Certificate file is too large", "status": 413}
    return None


def submit_tax_exemption(customer: Customer, payload: dict) -> dict:
    tax_id = str(payload.get("taxId") or "").strip()
    company = str(payload.get("company") or "").strip()
    tax_state = str(payload.get("taxState") or "").strip().upper()
    if not tax_id:
        return {"error": "Tax ID / EIN is required", "status": 400}
    if not company:
        return {"error": "Company name is required", "status": 400}
    if not tax_state:
        return {"error": "State is required", "status": 400}

    certificate_data = payload.get("certificateData") or ""
    if not isinstance(certificate_data, str):
        return _INVALID_CERTIFICATE
    if certificate_data:
        error = _certificate_error(certificate_data)
        if error is not None:
            return error

    submitted_at = timezone.now().isoformat()
    customer.tax_status = "PENDING VERIFICATION"
    customer.data = {
        **(customer.data or {}),
        "taxCompany": company,
        "taxId": tax_id,
        "taxState": tax_state,
        "taxExemptionType": str(payload.get("taxExemptionType") or "").strip(),
        "certificateName": str(payload.get("certificateName") or "").strip(),
        "certificateData": certificate_data,
        "taxSubmittedAt": submitted_at,
        "taxReviewedAt": None,
        "taxReviewedBy": None,
    }
    customer.updated_at = timezone.now()
    customer.save(update_fields=["tax_status", "data", "updated_at"])
    return {"ok": True, "status": "PENDING VERIFICATION", "submittedAt": submitted_at}
