"""`admin/customers` business rules (task 7.2), near-verbatim ports of
`app/api/admin/customers/route.ts`, `app/api/admin/customers/[id]/
route.ts`, `app/api/admin/customers/[id]/tax-exemption/route.ts`,
`app/api/admin/customers/[id]/tax-status/route.ts`, and
`app/api/admin/customers/portal-invite/route.ts`.
"""
from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.utils import timezone

from apps.backoffice.models import ActivityLog
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
    """Mirror `route.ts`'s `view()`: mask `taxId` to its last 4 characters,
    strip `taxId`/`certificateData` from the spread `data`, and let any
    `id`/`email`/`portalStatus`/`taxStatus` key ALSO present inside `data`
    win over the explicit row columns (verbatim spread order: explicit
    columns first, `...safeData` after)."""
    data = customer.data or {}
    raw_tax_id = str(data.get("taxId") or "")
    tax_id_masked = ("•" * max(0, len(raw_tax_id) - 4) + raw_tax_id[-4:]) if raw_tax_id else ""
    excluded_keys = ("taxId", "certificateData")
    safe_data = {key: value for key, value in data.items() if key not in excluded_keys}
    return {
        "id": customer.pk,
        "email": customer.email,
        "portalStatus": customer.portal_status,
        "taxStatus": customer.tax_status,
        **safe_data,
        "taxIdMasked": tax_id_masked,
    }


def list_admin_customers() -> list[dict]:
    customers = Customer.objects.order_by("created_at")
    return [_serialize_customer_masked(customer) for customer in customers]


def upsert_admin_customer(payload: dict) -> dict:
    """`POST /api/admin/customers` — create when no `id` resolves, update
    otherwise. `reusedExistingCustomer` mirrors the legacy flag verbatim:
    it reflects only whether the ORIGINAL payload omitted `id` and had an
    email, not whether an existing row was actually matched — preserved
    as-is rather than "corrected" to a more accurate signal."""
    email = str(payload.get("email") or "").strip().lower()
    had_id = bool(payload.get("id"))
    customer_id = str(payload["id"]) if had_id else ""

    if not customer_id and email:
        existing = Customer.objects.filter(email__iexact=email).first()
        if existing is not None:
            customer_id = existing.pk

    if customer_id:
        if email and Customer.objects.filter(email__iexact=email).exclude(pk=customer_id).exists():
            return {"error": "That email already belongs to another customer.", "status": 409}

        customer = Customer.objects.filter(pk=customer_id).first()
        if customer is None:
            # Legacy `update ... where id=$1` on a non-existent id is a
            # silent no-op; the route re-selects afterward and returns
            # 500 "Customer could not be saved" when nothing comes back.
            return {"error": "Customer could not be saved", "status": 500}

        customer.email = email or None
        customer.data = {**(customer.data or {}), **payload, "id": customer_id, "email": email}
        customer.updated_at = timezone.now()
        customer.save(update_fields=["email", "data", "updated_at"])
    else:
        customer_id = random_id("C")
        Customer.objects.create(
            id=customer_id,
            email=email or None,
            data={**payload, "id": customer_id, "email": email},
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

    customer = Customer.objects.get(pk=customer_id)
    return {
        "customer": _serialize_customer_masked(customer),
        "reusedExistingCustomer": bool(not had_id and email),
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


def update_customer_tax_status(customer_id: str, payload: dict, reviewer_username: str) -> dict:
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
        else {"taxReviewedAt": reviewed_at, "taxReviewedBy": reviewer_username}
    )

    customer.tax_status = status
    customer.data = {**(customer.data or {}), **patch}
    customer.updated_at = timezone.now()
    customer.save(update_fields=["tax_status", "data", "updated_at"])

    ActivityLog.objects.create(
        actor_id=reviewer_username,
        action="TAX_EXEMPTION_STATUS_CHANGED",
        entity_type="CUSTOMER",
        entity_id=customer_id,
        data={"status": status, "reviewedAt": reviewed_at},
        created_at=timezone.now(),
    )
    return {
        "ok": True,
        "status": status,
        "reviewedAt": reviewed_at,
        "reviewedBy": reviewer_username,
    }


def create_portal_invite(payload: dict) -> dict:
    customer_id = payload.get("customerId") or payload.get("id")
    if not customer_id:
        return {"error": "Customer required", "status": 400}

    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    # Legacy SQL runs the `update` unconditionally, with no prior existence
    # check — a non-existent id is a silent no-op and the route still
    # returns 200 `ok`; preserved verbatim (no 404 branch here).
    Customer.objects.filter(pk=customer_id).update(
        activation_token_hash=token_hash,
        activation_expires_at=timezone.now() + timezone.timedelta(days=7),
        portal_status="INVITED",
    )

    base = settings.APP_URL or "http://localhost:3000"
    return {"ok": True, "activationUrl": f"{base}/customer-login.html?token={token}"}
