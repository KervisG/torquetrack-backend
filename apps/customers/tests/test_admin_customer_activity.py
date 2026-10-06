"""Crear, editar y borrar un cliente desde el panel deja rastro en la bitácora
(`GET /api/admin/activity/`), igual que productos, pedidos y cotizaciones."""
import pytest
from django.utils import timezone

from apps.customers.models import Customer
from tests.factories import activity_count, create_staff_user, session_client


def _admin_client(user_id, permissions):
    create_staff_user(user_id, permissions=permissions)
    client, _ = session_client(user_id)
    return client


def _make_customer(customer_id, email):
    return Customer.objects.create(
        id=customer_id,
        email=email,
        data={},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )


@pytest.mark.django_db
def test_post_create_records_customer_created_activity():
    client = _admin_client("usr_cact_new", ["customers.edit"])

    response = client.post(
        "/api/admin/customers/", {"email": "cact-new@example.com", "name": "New"}, format="json"
    )

    assert response.status_code == 200
    customer_id = response.json()["customer"]["id"]
    assert (
        activity_count(
            action="CUSTOMER_CREATED",
            entity_type="CUSTOMER",
            entity_id=customer_id,
            actor_id="usr_cact_new@example.com",
        )
        == 1
    )


@pytest.mark.django_db
def test_post_edit_records_customer_updated_activity():
    client = _admin_client("usr_cact_edit", ["customers.edit"])
    _make_customer("cus_cact_edit", "cact-edit@example.com")

    response = client.post(
        "/api/admin/customers/",
        {"id": "cus_cact_edit", "email": "cact-edit@example.com", "name": "Edited"},
        format="json",
    )

    assert response.status_code == 200
    assert (
        activity_count(
            action="CUSTOMER_UPDATED",
            entity_type="CUSTOMER",
            entity_id="cus_cact_edit",
            actor_id="usr_cact_edit@example.com",
        )
        == 1
    )
    assert activity_count(action="CUSTOMER_CREATED", entity_id="cus_cact_edit") == 0


@pytest.mark.django_db
def test_post_reusing_customer_by_email_records_customer_updated_activity():
    client = _admin_client("usr_cact_reuse", ["customers.edit"])
    _make_customer("cus_cact_reuse", "cact-reuse@example.com")

    response = client.post(
        "/api/admin/customers/",
        {"email": "cact-reuse@example.com", "name": "Reused"},
        format="json",
    )

    assert response.status_code == 200
    assert activity_count(action="CUSTOMER_UPDATED", entity_id="cus_cact_reuse") == 1
    assert activity_count(action="CUSTOMER_CREATED") == 0


@pytest.mark.django_db
def test_rejected_post_records_no_activity():
    client = _admin_client("usr_cact_bad", ["customers.edit"])
    _make_customer("cus_cact_taken", "cact-taken@example.com")
    _make_customer("cus_cact_other", "cact-other@example.com")

    invalid = client.post(
        "/api/admin/customers/",
        {"email": "cact-bad@example.com", "state": "Florida"},
        format="json",
    )
    missing = client.post("/api/admin/customers/", {"id": "cus_missing"}, format="json")
    conflict = client.post(
        "/api/admin/customers/",
        {"id": "cus_cact_other", "email": "cact-taken@example.com"},
        format="json",
    )

    assert invalid.status_code == 400
    assert missing.status_code == 404
    assert conflict.status_code == 409
    assert activity_count(entity_type="CUSTOMER") == 0


@pytest.mark.django_db
def test_delete_records_customer_deleted_activity():
    client = _admin_client("usr_cact_del", ["customers.delete"])
    _make_customer("cus_cact_del", "cact-del@example.com")

    response = client.delete("/api/admin/customers/cus_cact_del/")

    assert response.status_code == 200
    assert (
        activity_count(
            action="CUSTOMER_DELETED",
            entity_type="CUSTOMER",
            entity_id="cus_cact_del",
            actor_id="usr_cact_del@example.com",
        )
        == 1
    )


@pytest.mark.django_db
def test_delete_of_unknown_customer_records_no_activity():
    client = _admin_client("usr_cact_del404", ["customers.delete"])

    response = client.delete("/api/admin/customers/cus_missing/")

    assert response.status_code == 404
    assert activity_count(entity_id="cus_missing") == 0
