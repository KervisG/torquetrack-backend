"""Services del carrito: listado del panel, contadores por estado y purga.

El listado es de solo lectura: omite los carritos vacíos sin borrarlos; el
borrado es explícito con `purge_empty_carts` (`manage.py purge_carts`).
`count_carts_by_status` usa la misma clasificación que el listado, así los
contadores del dashboard nunca discrepan de la tabla de carritos.
"""

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.cart.models import Cart
from apps.cart.services import count_carts_by_status, list_admin_carts, purge_empty_carts

EMPTY_DATA = [
    {},
    {"items": None},
    {"items": []},
    {"items": "p1"},
    {"items": 3},
    {"items": {"0": {"id": "p1"}}},
]
EMPTY_IDS = ["missing", "json-null", "empty-array", "string", "number", "object"]
ITEM = [{"id": "p1", "qty": 1}]


@pytest.mark.django_db
@pytest.mark.parametrize("data", EMPTY_DATA, ids=EMPTY_IDS)
def test_listing_omits_empty_carts_without_deleting_them(data):
    Cart.objects.create(id="cart_empty", data=data, updated_at=timezone.now())

    rows = list_admin_carts()

    assert rows == []
    assert Cart.objects.filter(pk="cart_empty").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("data", EMPTY_DATA, ids=EMPTY_IDS)
def test_purge_deletes_carts_whose_items_are_missing_non_array_or_empty(data):
    Cart.objects.create(id="cart_empty", data=data, updated_at=timezone.now())

    assert purge_empty_carts() == 1
    assert not Cart.objects.filter(pk="cart_empty").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "items", [ITEM, [None], [[]]], ids=["object", "null-element", "nested"]
)
def test_listing_and_purge_keep_carts_with_a_non_empty_items_array(items):
    Cart.objects.create(id="cart_full", data={"items": items}, updated_at=timezone.now())

    assert [row["id"] for row in list_admin_carts()] == ["cart_full"]
    assert purge_empty_carts() == 0
    assert Cart.objects.filter(pk="cart_full").exists()


@pytest.mark.django_db
def test_purge_carts_command_deletes_only_empty_carts(capsys):
    Cart.objects.create(id="cart_empty", data={"items": []})
    Cart.objects.create(id="cart_full", data={"items": ITEM})

    call_command("purge_carts")

    assert list(Cart.objects.values_list("pk", flat=True)) == ["cart_full"]
    assert "1" in capsys.readouterr().out


@pytest.mark.django_db
def test_status_counts_agree_with_the_listing():
    now = timezone.now()
    old = now - timezone.timedelta(minutes=45)
    Cart.objects.create(id="c_active", data={"items": ITEM, "stage": "CART"}, updated_at=now)
    Cart.objects.create(id="c_no_stage", data={"items": ITEM}, updated_at=now)
    Cart.objects.create(id="c_abandoned", data={"items": ITEM, "stage": "CART"}, updated_at=old)
    Cart.objects.create(id="c_checkout", data={"items": ITEM, "stage": "CHECKOUT"}, updated_at=old)
    Cart.objects.create(
        id="c_quote", data={"items": ITEM, "stage": "BUILDING_QUOTE"}, updated_at=now
    )
    Cart.objects.create(id="c_empty_old", data={"items": []}, updated_at=old)

    listed = {}
    for row in list_admin_carts():
        listed[row["status"]] = listed.get(row["status"], 0) + 1

    assert dict(count_carts_by_status()) == listed
    assert listed == {"ACTIVE": 2, "ABANDONED": 1, "CHECKOUT": 1, "BUILDING_QUOTE": 1}
