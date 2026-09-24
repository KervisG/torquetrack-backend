"""Clientes: el perfil de la sesión, el alta pública, la verificación del
email con el historial de invitado, el panel de staff, el autoservicio de la
cuenta y la activación del portal.

Pedidos y cotizaciones dependen de esta app y no al revés: aquí se llega a
ellos solo por las relaciones inversas de `Customer` (`orders`, `quotes`).
"""
from __future__ import annotations

import base64
import binascii
import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.auth.models import User, split_full_name
from apps.auth.services import (
    consume_email_verification,
    create_account,
    invited_emails,
    issue_activation_token,
    lock_activation_token,
    parse_email,
    send_verification_email,
)
from apps.common.ids import random_id
from apps.common.links import app_url
from apps.customers.models import Customer

ALLOWED_TAX_STATUSES = [
    "VERIFIED",
    "REJECTED",
    "EXPIRED",
    "PENDING VERIFICATION",
    "NOT SUBMITTED",
]


def _serialize_customer_masked(customer: Customer, invited: set[str]) -> dict:
    """`invited` son los emails con invitación vigente (`invited_emails`).

    Las columnas van después de `data` para que una clave vieja de `data`
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
        "portalStatus": portal_status(customer, invited),
        "taxStatus": customer.tax_status,
        "taxIdMasked": tax_id_masked,
    }


def list_admin_customers() -> list[dict]:
    customers = list(Customer.objects.order_by("created_at"))
    invited = invited_emails(customer.email for customer in customers)
    return [_serialize_customer_masked(customer, invited) for customer in customers]


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
        "customer": _serialize_customer_masked(customer, invited_emails([customer.email])),
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


def portal_status(customer: Customer, invited: set[str]) -> str:
    """Se deriva del vínculo con `User` y de los tokens de activación para no
    tener una columna que mantener sincronizada."""
    if customer.user_id is not None:
        return "ACTIVE"
    if customer.email and customer.email in invited:
        return "INVITED"
    return "NOT ACTIVATED"


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

    token = issue_activation_token(customer.email)
    return {"ok": True, "activationUrl": app_url(f"/activate?token={token}")}


def activate_customer_account(payload: dict) -> dict:
    """El token está ligado al email exacto del perfil invitado, que es único
    entre invitados: si el perfil cambió de email o ya tiene cuenta, el enlace
    deja de valer."""
    password = payload.get("password")
    invalid = {"error": "Invalid or expired activation link", "status": 400}
    if not isinstance(password, str):
        return invalid

    with transaction.atomic():
        record = lock_activation_token(payload.get("token"))
        customer = (
            Customer.objects.select_for_update()
            .filter(email=record.email, user__isnull=True)
            .first()
            if record is not None
            else None
        )
        if customer is None:
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
        now = timezone.now()
        user = result["user"]
        user.email_verified_at = now
        user.save(update_fields=["email_verified_at"])

        customer.user = user
        customer.updated_at = now
        customer.save(update_fields=["user", "updated_at"])

        record.user = user
        record.used_at = now
        record.save(update_fields=["user", "used_at"])
    return {"user": user}


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
    """Perfil comercial de la cuenta con sesión, o `None` para un invitado.

    Se exige un `User` real: `AnonymousUser.pk` es `None` y filtrar por
    `user_id=None` devolvería un perfil invitado cualquiera.
    """
    if not isinstance(user, User):
        return None
    return Customer.objects.filter(user=user).first()


def register_customer(payload: dict) -> dict:
    """El registro no toca un Customer invitado con el mismo email: el correo
    todavía no está verificado y adueñarse de ese perfil le daría a
    cualquiera el historial de otra persona. Ese historial se vincula recién
    en `verify_customer_email`, cuando el enlace prueba que la persona
    controla la casilla; hasta entonces puede entrar y comprar igual.
    """
    email = parse_email(payload.get("email"))
    password = payload.get("password")
    name = str(payload.get("name") or "").strip()
    if email is None or not isinstance(password, str) or not password or not name:
        return {"error": "Email, password and name required", "status": 400}

    company = str(payload.get("company") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    first_name, last_name = split_full_name(name)

    with transaction.atomic():
        result = create_account(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            display_name=name,
        )
        if "error" in result:
            return result
        user = result["user"]
        customer_id = random_id("C")
        now = timezone.now()
        Customer.objects.create(
            id=customer_id,
            user=user,
            email=email,
            data={
                "id": customer_id,
                "email": email,
                "name": name,
                "company": company,
                "phone": phone,
            },
            created_at=now,
            updated_at=now,
        )
    send_verification_email(user)
    return {"user": user}


def verify_customer_email(payload: dict) -> dict:
    """Vincula el historial de compras como invitado en la misma transacción
    que verifica el correo."""
    with transaction.atomic():
        user = consume_email_verification(payload.get("token"))
        if user is None:
            return {"error": "Invalid or expired verification link", "status": 400}
        linked = link_guest_history(user)
    return {"ok": True, **linked}


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
        linked_orders += own.orders.count()
        linked_quotes += own.quotes.count()

    for guest in guests:
        linked_orders += guest.orders.update(customer=own)
        linked_quotes += guest.quotes.update(customer=own)
    if guests:
        Customer.objects.filter(pk__in=[guest.pk for guest in guests]).delete()
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
    orders = customer.orders.order_by("-created_at")
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
    quotes = customer.quotes.order_by("-created_at")
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
