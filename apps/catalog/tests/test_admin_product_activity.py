"""Crear, editar y desactivar un producto desde el panel deja rastro en la
bitácora (`GET /api/admin/activity/`), igual que pedidos y cotizaciones."""
import pytest
from django.utils import timezone

from apps.catalog.models import Product
from tests.factories import activity_count, create_staff_user, session_client


def _admin_client(user_id, permissions):
    create_staff_user(user_id, permissions=permissions)
    client, _ = session_client(user_id)
    return client


@pytest.mark.django_db
def test_put_create_records_product_created_activity():
    client = _admin_client("usr_act_new", ["products.edit", "pricing.edit"])

    response = client.put(
        "/api/admin/products/prod_act_new/",
        {"title": "CP3 Pump", "partNumber": "0445020150", "price": 10},
        format="json",
    )

    assert response.status_code == 200
    assert (
        activity_count(
            action="PRODUCT_CREATED",
            entity_type="PRODUCT",
            entity_id="prod_act_new",
            actor_id="usr_act_new@example.com",
        )
        == 1
    )


@pytest.mark.django_db
def test_put_edit_records_product_updated_activity():
    client = _admin_client("usr_act_edit", ["products.edit", "pricing.edit"])
    Product.objects.create(id="prod_act_edit", data={"title": "Old", "price": 5})

    response = client.put(
        "/api/admin/products/prod_act_edit/",
        {"title": "New", "partNumber": "X1", "price": 5},
        format="json",
    )

    assert response.status_code == 200
    assert activity_count(action="PRODUCT_UPDATED", entity_id="prod_act_edit") == 1
    assert activity_count(action="PRODUCT_CREATED", entity_id="prod_act_edit") == 0


@pytest.mark.django_db
def test_rejected_put_records_no_activity():
    client = _admin_client("usr_act_bad", ["products.edit", "pricing.edit"])

    response = client.put(
        "/api/admin/products/prod_act_bad/", {"title": "No price", "price": 0}, format="json"
    )

    assert response.status_code == 400
    assert activity_count(entity_id="prod_act_bad") == 0


@pytest.mark.django_db
def test_delete_records_product_deactivated_activity():
    client = _admin_client("usr_act_del", ["products.edit"])
    Product.objects.create(id="prod_act_del", data={}, active=True, updated_at=timezone.now())

    response = client.delete("/api/admin/products/prod_act_del/")

    assert response.status_code == 200
    assert (
        activity_count(
            action="PRODUCT_DEACTIVATED",
            entity_id="prod_act_del",
            actor_id="usr_act_del@example.com",
        )
        == 1
    )


@pytest.mark.django_db
def test_delete_of_unknown_product_records_no_activity():
    client = _admin_client("usr_act_del404", ["products.edit"])

    response = client.delete("/api/admin/products/prod_missing/")

    assert response.status_code == 404
    assert activity_count(entity_id="prod_missing") == 0
