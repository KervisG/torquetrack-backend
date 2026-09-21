"""`PUT/DELETE /api/admin/products/[id]` (task 7.3), pinned against
`app/api/admin/products/[id]/route.ts`.

Task 7.3 literally names only `admin/products/[id]`, not the collection
`admin/products` (GET/POST) — see the apply-progress note flagging that
collection route as a new scope gap, same precedent as Phase 6's task 7.6
flag for admin quotes list/create.
"""
import json
from importlib import import_module

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Product


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


# --- DELETE (soft delete) ----------------------------------------------


@pytest.mark.django_db
def test_delete_returns_403_without_products_edit_permission():
    _insert_user("usr_del_no_perm", permissions=["products.view"])
    Product.objects.create(
        id="prod_1", data={"id": "prod_1"}, active=True, updated_at=timezone.now()
    )
    client = _admin_client("usr_del_no_perm")

    response = client.delete("/api/admin/products/prod_1/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_soft_deletes_by_setting_active_false():
    _insert_user("usr_del", permissions=["products.edit"])
    Product.objects.create(
        id="prod_2", data={"id": "prod_2"}, active=True, updated_at=timezone.now()
    )
    client = _admin_client("usr_del")

    response = client.delete("/api/admin/products/prod_2/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    product = Product.objects.get(pk="prod_2")
    assert product.active is False


@pytest.mark.django_db
def test_delete_is_a_silent_no_op_for_unknown_product():
    _insert_user("usr_del2", permissions=["products.edit"])
    client = _admin_client("usr_del2")

    response = client.delete("/api/admin/products/does-not-exist/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


# --- PUT (upsert) ---------------------------------------------------------


@pytest.mark.django_db
def test_put_returns_403_without_products_edit_permission():
    _insert_user("usr_put_no_perm", permissions=["products.view"])
    client = _admin_client("usr_put_no_perm")

    response = client.put(
        "/api/admin/products/prod_3/", {"title": "New Part"}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_put_creates_product_forcing_id_from_url():
    _insert_user("usr_put", permissions=["products.edit"])
    client = _admin_client("usr_put")

    response = client.put(
        "/api/admin/products/prod_new/",
        {"id": "ignored-client-id", "title": "New Part", "price": 99.5},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["product"]["id"] == "prod_new"
    product = Product.objects.get(pk="prod_new")
    assert product.active is True
    assert product.data["title"] == "New Part"
    assert product.data["id"] == "prod_new"


@pytest.mark.django_db
def test_put_reads_nested_product_key_when_present():
    _insert_user("usr_put2", permissions=["products.edit"])
    client = _admin_client("usr_put2")

    response = client.put(
        "/api/admin/products/prod_nested/",
        {"product": {"title": "Nested Part"}},
        format="json",
    )

    assert response.status_code == 200
    product = Product.objects.get(pk="prod_nested")
    assert product.data["title"] == "Nested Part"


@pytest.mark.django_db
def test_put_updates_and_reactivates_existing_product():
    _insert_user("usr_put3", permissions=["products.edit"])
    Product.objects.create(
        id="prod_existing",
        data={"id": "prod_existing", "title": "Old"},
        active=False,
        updated_at=timezone.now(),
    )
    client = _admin_client("usr_put3")

    response = client.put(
        "/api/admin/products/prod_existing/", {"title": "Updated"}, format="json"
    )

    assert response.status_code == 200
    product = Product.objects.get(pk="prod_existing")
    assert product.active is True
    assert product.data["title"] == "Updated"
