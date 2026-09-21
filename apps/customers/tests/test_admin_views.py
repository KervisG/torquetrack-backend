"""`admin/customers`, `admin/customers/[id]`,
`admin/customers/[id]/tax-exemption`, `admin/customers/[id]/tax-status`,
`admin/customers/portal-invite` (task 7.2), pinned against
`app/api/admin/customers/route.ts`, `app/api/admin/customers/[id]/route.ts`,
`app/api/admin/customers/[id]/tax-exemption/route.ts`,
`app/api/admin/customers/[id]/tax-status/route.ts`, and
`app/api/admin/customers/portal-invite/route.ts`.

`tax-exemption` (GET) and `tax-status` (POST) use ONLY `requireAdmin()` in
the legacy code (any active admin-role-or-employee session, 401 only) —
NOT `requirePermission("customers.view")` as the spec's paraphrase might
suggest. Verified directly against `lib/auth.ts` and both route files;
preserved verbatim rather than "corrected" to match the spec prose.
"""
import json
from importlib import import_module

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.backoffice.models import ActivityLog
from apps.customers.models import Customer


def _insert_user(user_id, role="authorized", permissions=None, active=True):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into users (id, username, password_hash, role, active, "
            "permissions) values (%s, %s, %s, %s, %s, %s::jsonb)",
            [
                user_id,
                f"{user_id}@example.com",
                "scrypt$salt$hash",
                role,
                active,
                json.dumps(permissions or []),
            ],
        )


def _admin_client(user_id):
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store["user_id"] = user_id
    store.save()
    client = APIClient()
    client.cookies["tt_admin"] = store.session_key
    return client


def _make_customer(customer_id="cus_1", email="pat@example.com", data=None, **kwargs):
    return Customer.objects.create(
        id=customer_id,
        email=email,
        data=data or {},
        created_at=timezone.now(),
        updated_at=timezone.now(),
        **kwargs,
    )


# --- list (GET) -------------------------------------------------------------


@pytest.mark.django_db
def test_list_returns_403_without_customers_view_permission():
    _insert_user("usr_list_no_perm", permissions=[])
    client = _admin_client("usr_list_no_perm")

    response = client.get("/api/admin/customers/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_list_masks_tax_id_and_strips_certificate_data():
    _insert_user("usr_list", permissions=["customers.view"])
    _make_customer(
        data={
            "name": "Pat Diesel",
            "taxId": "12-3456789",
            "certificateData": "base64stuff",
        }
    )
    client = _admin_client("usr_list")

    response = client.get("/api/admin/customers/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["taxIdMasked"] == "••••••6789"
    assert "taxId" not in row
    assert "certificateData" not in row
    assert row["name"] == "Pat Diesel"


# --- create/update (POST) --------------------------------------------------


@pytest.mark.django_db
def test_create_returns_403_without_customers_edit_permission():
    _insert_user("usr_create_no_perm", permissions=["customers.view"])
    client = _admin_client("usr_create_no_perm")

    response = client.post("/api/admin/customers/", {"email": "new@example.com"}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_create_new_customer_without_id():
    _insert_user("usr_create", permissions=["customers.edit"])
    client = _admin_client("usr_create")

    response = client.post(
        "/api/admin/customers/",
        {"email": "brand-new@example.com", "name": "Brand New"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    # Legacy `reusedExistingCustomer` reflects only "no id was submitted
    # AND an email was present" — true here even though no existing row
    # actually matched (see `upsert_admin_customer`'s docstring).
    assert body["reusedExistingCustomer"] is True
    customer = Customer.objects.get(pk=body["customer"]["id"])
    assert customer.email == "brand-new@example.com"
    assert customer.data["name"] == "Brand New"


@pytest.mark.django_db
def test_create_new_customer_without_email_is_not_flagged_as_reused():
    _insert_user("usr_create_no_email", permissions=["customers.edit"])
    client = _admin_client("usr_create_no_email")

    response = client.post(
        "/api/admin/customers/", {"name": "No Email Customer"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["reusedExistingCustomer"] is False


@pytest.mark.django_db
def test_create_without_id_reuses_existing_customer_by_email():
    _insert_user("usr_create2", permissions=["customers.edit"])
    existing = _make_customer(customer_id="cus_existing", email="repeat@example.com")
    client = _admin_client("usr_create2")

    response = client.post(
        "/api/admin/customers/",
        {"email": "repeat@example.com", "name": "Repeat Customer"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["customer"]["id"] == existing.pk
    assert body["reusedExistingCustomer"] is True
    existing.refresh_from_db()
    assert existing.data["name"] == "Repeat Customer"


@pytest.mark.django_db
def test_update_returns_409_when_email_belongs_to_another_customer():
    _insert_user("usr_update", permissions=["customers.edit"])
    _make_customer(customer_id="cus_a", email="a@example.com")
    _make_customer(customer_id="cus_b", email="b@example.com")
    client = _admin_client("usr_update")

    response = client.post(
        "/api/admin/customers/",
        {"id": "cus_a", "email": "b@example.com"},
        format="json",
    )

    assert response.status_code == 409


# --- delete (DELETE) --------------------------------------------------------


@pytest.mark.django_db
def test_delete_returns_403_without_customers_delete_permission():
    _insert_user("usr_delete_no_perm", permissions=["customers.view"])
    _make_customer()
    client = _admin_client("usr_delete_no_perm")

    response = client.delete("/api/admin/customers/cus_1/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_removes_customer():
    _insert_user("usr_delete", permissions=["customers.delete"])
    _make_customer()
    client = _admin_client("usr_delete")

    response = client.delete("/api/admin/customers/cus_1/")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "deletedCustomerId": "cus_1"}
    assert not Customer.objects.filter(pk="cus_1").exists()


@pytest.mark.django_db
def test_delete_returns_404_for_unknown_customer():
    _insert_user("usr_delete2", permissions=["customers.delete"])
    client = _admin_client("usr_delete2")

    response = client.delete("/api/admin/customers/does-not-exist/")

    assert response.status_code == 404


# --- tax-exemption (GET) -----------------------------------------------


@pytest.mark.django_db
def test_tax_exemption_returns_401_without_session():
    _make_customer()

    response = APIClient().get("/api/admin/customers/cus_1/tax-exemption/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_tax_exemption_returns_unmasked_tax_id_for_any_active_admin_session():
    # No specific permission required beyond an active session — verified
    # directly against `requireAdmin()` in the legacy route.
    _insert_user("usr_tax_view", permissions=[])
    _make_customer(
        data={"taxId": "12-3456789", "taxCompany": "Diesel Co", "certificateData": "b64"}
    )
    client = _admin_client("usr_tax_view")

    response = client.get("/api/admin/customers/cus_1/tax-exemption/")

    assert response.status_code == 200
    body = response.json()
    assert body["tax"]["taxId"] == "12-3456789"
    assert body["tax"]["company"] == "Diesel Co"
    assert body["tax"]["certificateData"] == "b64"


@pytest.mark.django_db
def test_tax_exemption_returns_404_for_unknown_customer():
    _insert_user("usr_tax_view2", permissions=[])
    client = _admin_client("usr_tax_view2")

    response = client.get("/api/admin/customers/does-not-exist/tax-exemption/")

    assert response.status_code == 404


# --- tax-status (POST) ---------------------------------------------------


@pytest.mark.django_db
def test_tax_status_returns_401_without_session():
    _make_customer()

    response = APIClient().post(
        "/api/admin/customers/cus_1/tax-status/", {"status": "VERIFIED"}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_tax_status_rejects_invalid_status():
    _insert_user("usr_tax_status", permissions=[])
    _make_customer()
    client = _admin_client("usr_tax_status")

    response = client.post(
        "/api/admin/customers/cus_1/tax-status/", {"status": "BOGUS"}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_tax_status_verified_sets_reviewed_metadata_and_logs_activity():
    _insert_user("usr_tax_status2", permissions=[])
    _make_customer()
    client = _admin_client("usr_tax_status2")

    response = client.post(
        "/api/admin/customers/cus_1/tax-status/", {"status": "verified"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "VERIFIED"
    assert body["reviewedBy"] == "usr_tax_status2@example.com"

    customer = Customer.objects.get(pk="cus_1")
    assert customer.tax_status == "VERIFIED"
    assert customer.data["taxReviewedBy"] == "usr_tax_status2@example.com"
    assert ActivityLog.objects.filter(
        action="TAX_EXEMPTION_STATUS_CHANGED", entity_id="cus_1"
    ).exists()


@pytest.mark.django_db
def test_tax_status_pending_verification_does_not_set_reviewed_metadata():
    _insert_user("usr_tax_status3", permissions=[])
    _make_customer()
    client = _admin_client("usr_tax_status3")

    response = client.post(
        "/api/admin/customers/cus_1/tax-status/",
        {"status": "PENDING VERIFICATION"},
        format="json",
    )

    assert response.status_code == 200
    customer = Customer.objects.get(pk="cus_1")
    assert "taxReviewedBy" not in customer.data


# --- portal-invite (POST) ------------------------------------------------


@pytest.mark.django_db
def test_portal_invite_returns_403_without_customers_edit_permission():
    _insert_user("usr_invite_no_perm", permissions=["customers.view"])
    _make_customer()
    client = _admin_client("usr_invite_no_perm")

    response = client.post(
        "/api/admin/customers/portal-invite/", {"customerId": "cus_1"}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_portal_invite_returns_400_without_customer_id():
    _insert_user("usr_invite_no_id", permissions=["customers.edit"])
    client = _admin_client("usr_invite_no_id")

    response = client.post("/api/admin/customers/portal-invite/", {}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_portal_invite_sets_token_and_returns_activation_url(settings):
    settings.APP_URL = "https://torquetrackdiesel.com"
    _insert_user("usr_invite", permissions=["customers.edit"])
    _make_customer()
    client = _admin_client("usr_invite")

    response = client.post(
        "/api/admin/customers/portal-invite/", {"customerId": "cus_1"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["activationUrl"].startswith(
        "https://torquetrackdiesel.com/customer-login.html?token="
    )

    customer = Customer.objects.get(pk="cus_1")
    assert customer.portal_status == "INVITED"
    assert customer.activation_token_hash
    assert customer.activation_expires_at > timezone.now()
