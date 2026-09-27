"""Clientes en el panel de staff: alta y edición, estado fiscal e invitación
al portal."""
from __future__ import annotations

from django.utils import timezone

from apps.audit.services import record_activity
from apps.authentication.services import invited_emails, issue_activation_token
from apps.common.ids import random_id
from apps.common.links import app_url
from apps.customers.models import Customer
from apps.customers.services.storefront import _profile_patch

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
