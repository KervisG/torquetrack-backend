"""`PUT` y `DELETE /api/admin/products/<id>/` con `products.edit`.

Los campos de precio (`price`, `compareAt`, `coreCharge`) solo cambian con
`pricing.edit`; los de costo (`purchaseCost`, `supplierCost`) también exigen
`pricing.edit` para cambiar y solo se devuelven con `costs.view`. Un campo
protegido ausente del body conserva su valor. Sin proveedores que mockear.
"""
import pytest
from django.utils import timezone

from apps.catalog.models import Product
from apps.common.business_day import store_today
from tests.factories import create_staff_user, session_client


def _insert_user(user_id, permissions=None, active=True, full_access=False):
    create_staff_user(
        user_id, permissions=permissions, active=active, full_access=full_access
    )


def _admin_client(user_id):
    client, _ = session_client(user_id)
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
def test_delete_returns_404_for_unknown_product():
    _insert_user("usr_del2", permissions=["products.edit"])
    client = _admin_client("usr_del2")

    response = client.delete("/api/admin/products/does-not-exist/")

    assert response.status_code == 404
    assert response.json() == {"error": "Product not found"}


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
    _insert_user("usr_put", permissions=["products.edit", "pricing.edit"])
    client = _admin_client("usr_put")

    response = client.put(
        "/api/admin/products/prod_new/",
        {"id": "ignored-client-id", "title": "New Part", "partNumber": "NP-1", "price": 99.5},
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
    _insert_user("usr_put2", permissions=["products.edit", "pricing.edit"])
    client = _admin_client("usr_put2")

    response = client.put(
        "/api/admin/products/prod_nested/",
        {"product": {"title": "Nested Part", "partNumber": "NP-2", "price": 25}},
        format="json",
    )

    assert response.status_code == 200
    product = Product.objects.get(pk="prod_nested")
    assert product.data["title"] == "Nested Part"


@pytest.mark.django_db
def test_put_keeps_a_deactivated_product_inactive():
    _insert_user("usr_put3", permissions=["products.edit"])
    Product.objects.create(
        id="prod_existing",
        data={"id": "prod_existing", "title": "Old", "price": 50},
        active=False,
        updated_at=timezone.now(),
    )
    client = _admin_client("usr_put3")

    response = client.put(
        "/api/admin/products/prod_existing/",
        {"title": "Updated", "partNumber": "UP-1"},
        format="json",
    )

    assert response.status_code == 200
    product = Product.objects.get(pk="prod_existing")
    assert product.active is False
    assert product.data["title"] == "Updated"


@pytest.mark.django_db
def test_put_with_explicit_active_reactivates_the_product():
    _insert_user("usr_put4", permissions=["products.edit"])
    Product.objects.create(id="prod_off", data={"id": "prod_off", "price": 50}, active=False)
    client = _admin_client("usr_put4")

    response = client.put(
        "/api/admin/products/prod_off/",
        {"title": "Back", "partNumber": "BK-1", "active": True},
        format="json",
    )

    assert response.status_code == 200
    product = Product.objects.get(pk="prod_off")
    assert product.active is True
    assert "active" not in product.data


@pytest.mark.django_db
def test_put_rejects_a_non_boolean_active():
    _insert_user("usr_put5", permissions=["products.edit"])
    client = _admin_client("usr_put5")

    response = client.put("/api/admin/products/prod_x/", {"active": "yes"}, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "active must be a boolean", "field": "active"}
    assert not Product.objects.exists()



@pytest.mark.django_db
@pytest.mark.parametrize("price", [None, 0, -5, "", "abc"])
def test_put_rejects_a_product_without_a_positive_price(price):
    # Todo producto se vende con precio: sin él, el checkout lo cobraría gratis.
    _insert_user("usr_put6", permissions=["products.edit", "pricing.edit"])
    body = {"title": "Unpriced Part"}
    if price is not None:
        body["price"] = price

    response = _admin_client("usr_put6").put(
        "/api/admin/products/prod_unpriced/", body, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {"error": "price must be greater than 0", "field": "price"}
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_put_on_a_stored_product_without_price_requires_setting_one():
    _insert_user("usr_put7", permissions=["products.edit", "pricing.edit"])
    Product.objects.create(id="prod_legacy", data={"id": "prod_legacy", "price": 0})
    client = _admin_client("usr_put7")

    rejected = client.put("/api/admin/products/prod_legacy/", {"title": "Pump"}, format="json")
    accepted = client.put(
        "/api/admin/products/prod_legacy/",
        {"title": "Pump", "partNumber": "PM-1", "price": 80},
        format="json",
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert Product.objects.get(pk="prod_legacy").data["price"] == 80


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field, error_field",
    [
        ("compareAt", "compare_at"),
        ("coreCharge", "core_charge"),
        ("purchaseCost", "purchase_cost"),
    ],
)
def test_put_rejects_money_that_is_not_a_number(field, error_field):
    _insert_user("usr_put8", permissions=["products.edit", "pricing.edit", "costs.view"])
    body = {"title": "Pump", "partNumber": "PM-1", "price": 80, field: "call us"}

    response = _admin_client("usr_put8").put(
        "/api/admin/products/prod_text/", body, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {"error": f"{field} must be a number", "field": error_field}
    assert not Product.objects.exists()

# --- precios y costos ------------------------------------------------------

STORED = {
    "id": "prod_priced",
    "title": "Injector",
    "partNumber": "INJ-1",
    "price": 100.0,
    "coreCharge": 20.0,
    "purchaseCost": 60.0,
    "supplierCost": 55.0,
}


def _insert_priced():
    Product.objects.create(id="prod_priced", data=dict(STORED), active=True)


def _put(client, body):
    body = {"partNumber": STORED["partNumber"], **body}
    return client.put("/api/admin/products/prod_priced/", body, format="json")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("price", 1.0),
        ("coreCharge", 0),
        ("compareAt", 500),
        ("purchaseCost", 1),
        ("supplierCost", 1),
    ],
)
def test_changing_price_or_cost_without_pricing_edit_returns_403(field, value):
    _insert_user("usr_no_pricing", permissions=["products.edit", "costs.view"])
    _insert_priced()

    response = _put(_admin_client("usr_no_pricing"), {"title": "Injector", field: value})

    assert response.status_code == 403
    assert Product.objects.get(pk="prod_priced").data == STORED


@pytest.mark.django_db
def test_creating_a_priced_product_without_pricing_edit_returns_403():
    _insert_user("usr_no_pricing2", permissions=["products.edit"])

    response = _admin_client("usr_no_pricing2").put(
        "/api/admin/products/prod_new/", {"title": "New", "price": 10}, format="json"
    )

    assert response.status_code == 403
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_editing_without_pricing_edit_keeps_prices_and_costs():
    _insert_user("usr_editor", permissions=["products.edit"])
    _insert_priced()

    response = _put(_admin_client("usr_editor"), {"title": "Renamed", "price": 100.0})

    assert response.status_code == 200
    assert Product.objects.get(pk="prod_priced").data == {**STORED, "title": "Renamed"}


@pytest.mark.django_db
def test_response_hides_costs_without_costs_view():
    _insert_user("usr_editor2", permissions=["products.edit"])
    _insert_priced()

    product = _put(_admin_client("usr_editor2"), {"title": "Renamed"}).json()["product"]

    assert product["price"] == 100.0
    assert "purchaseCost" not in product
    assert "supplierCost" not in product


@pytest.mark.django_db
def test_pricing_edit_changes_prices_and_costs_and_costs_view_shows_them():
    _insert_user("usr_pricing", permissions=["products.edit", "pricing.edit", "costs.view"])
    _insert_priced()

    response = _put(
        _admin_client("usr_pricing"), {"title": "Injector", "price": 120.0, "purchaseCost": 70.0}
    )

    assert response.status_code == 200
    stored = Product.objects.get(pk="prod_priced").data
    assert stored["price"] == 120.0
    assert stored["purchaseCost"] == 70.0
    assert stored["supplierCost"] == 55.0
    assert response.json()["product"]["purchaseCost"] == 70.0


@pytest.mark.django_db
def test_list_requires_products_view_and_hides_costs():
    _insert_user("usr_list_denied", permissions=["products.edit"])
    denied = _admin_client("usr_list_denied").get("/api/admin/products/")
    assert denied.status_code == 403

    _insert_user("usr_list", permissions=["products.view"])
    Product.objects.create(
        id="prod_listed",
        data={"title": "Turbo", "purchaseCost": 40, "internalNotes": "secret"},
        active=False,
        updated_at=timezone.now(),
    )
    response = _admin_client("usr_list").get("/api/admin/products/")

    assert response.status_code == 200
    row = response.json()[0]
    assert row["id"] == "prod_listed"
    assert row["active"] is False
    assert row["title"] == "Turbo"
    assert "purchaseCost" not in row
    assert "internalNotes" not in row


@pytest.mark.django_db
def test_put_without_costs_view_keeps_hidden_internal_fields():
    _insert_user("usr_keep", permissions=["products.edit", "pricing.edit"])
    Product.objects.create(
        id="prod_keep",
        data={"title": "Pump", "price": 10, "internalNotes": "secret", "supplier": "Bosch"},
        active=True,
        updated_at=timezone.now(),
    )

    response = _admin_client("usr_keep").put(
        "/api/admin/products/prod_keep/",
        {"title": "Pump rebuilt", "partNumber": "PM-2"},
        format="json",
    )

    assert response.status_code == 200
    stored = Product.objects.get(pk="prod_keep").data
    assert stored["title"] == "Pump rebuilt"
    assert stored["internalNotes"] == "secret"
    assert stored["supplier"] == "Bosch"


def test_cost_fields_are_hidden_from_the_storefront():
    from apps.catalog.serializers.storefront import RESTRICTED_PRODUCT_FIELDS
    from apps.catalog.services.admin import COST_FIELDS

    assert set(COST_FIELDS) <= set(RESTRICTED_PRODUCT_FIELDS)


# --- slug ---------------------------------------------------------------------
# Se genera al crear y no cambia al editar: las URLs públicas quedan estables.


@pytest.mark.django_db
def test_put_create_generates_the_slug_and_returns_it():
    _insert_user("usr_slug", permissions=["products.edit", "pricing.edit"])
    client = _admin_client("usr_slug")

    response = client.put(
        "/api/admin/products/prod_slug/",
        {"title": "Bosch CP3 Injection Pump", "partNumber": "0445020150", "price": 10},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["product"]["slug"] == "bosch-cp3-injection-pump-0445020150"
    assert Product.objects.get(pk="prod_slug").slug == "bosch-cp3-injection-pump-0445020150"


@pytest.mark.django_db
def test_put_edit_keeps_the_slug_and_ignores_a_slug_in_the_body():
    _insert_user("usr_slug_edit", permissions=["products.edit", "pricing.edit"])
    client = _admin_client("usr_slug_edit")
    Product.objects.create(id="prod_s", data={"title": "Old", "partNumber": "X", "price": 5})

    response = client.put(
        "/api/admin/products/prod_s/",
        {"title": "Renamed", "partNumber": "X", "price": 5, "slug": "hijack"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["product"]["slug"] == "old-x"
    product = Product.objects.get(pk="prod_s")
    assert product.slug == "old-x"
    assert "slug" not in product.data


@pytest.mark.django_db
def test_list_includes_the_slug():
    _insert_user("usr_slug_list", permissions=["products.view"])
    Product.objects.create(id="prod_l", data={"title": "Turbo", "partNumber": "T1"})

    row = _admin_client("usr_slug_list").get("/api/admin/products/").json()[0]

    assert row["slug"] == "turbo-t1"


# --- validación de campos ----------------------------------------------------
# Mismas reglas y mensajes que `src/lib/validators/admin-product.ts` del SPA.

VALID_PRODUCT = {"title": "CP3 Pump", "partNumber": "0445020150", "price": 100}


def _put_product(user_id, body):
    _insert_user(user_id, permissions=["products.edit", "pricing.edit"])
    return _admin_client(user_id).put("/api/admin/products/prod_v/", body, format="json")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "error", "field"),
    [
        ({"title": None}, "Title is required", "title"),
        ({"title": "   "}, "Title is required", "title"),
        ({"partNumber": ""}, "Part number is required", "part_number"),
        ({"partNumber": " \t"}, "Part number is required", "part_number"),
        ({"yearFrom": 98}, "Enter a 4-digit year", "year_from"),
        ({"yearTo": "20a1"}, "Enter a 4-digit year", "year_to"),
        ({"yearFrom": True}, "Enter a 4-digit year", "year_from"),
        ({"yearFrom": 2004.5}, "Enter a 4-digit year", "year_from"),
        ({"yearFrom": 1899}, "Enter a year between 1900 and {max_year}", "year_from"),
        ({"yearTo": "{too_late}"}, "Enter a year between 1900 and {max_year}", "year_to"),
        (
            {"yearFrom": 2010, "yearTo": 2004},
            "Year to must be the same as or after year from",
            "year_to",
        ),
    ],
)
def test_put_rejects_invalid_product_fields(overrides, error, field):
    max_year = store_today().year + 2
    overrides = {
        key: value.format(too_late=max_year + 1) if isinstance(value, str) else value
        for key, value in overrides.items()
    }
    merged = {**VALID_PRODUCT, **overrides}
    body = {key: value for key, value in merged.items() if value is not None}

    response = _put_product("usr_put_invalid", body)

    assert response.status_code == 400
    assert response.json() == {"error": error.format(max_year=max_year), "field": field}
    assert not Product.objects.filter(pk="prod_v").exists()


@pytest.mark.django_db
def test_put_accepts_years_as_numbers_or_digit_strings_and_stores_numbers():
    max_year = store_today().year + 2

    response = _put_product(
        "usr_put_years", {**VALID_PRODUCT, "yearFrom": "1994", "yearTo": max_year}
    )

    assert response.status_code == 200, response.content
    data = Product.objects.get(pk="prod_v").data
    assert (data["yearFrom"], data["yearTo"]) == (1994, max_year)


@pytest.mark.django_db
def test_put_treats_empty_years_as_no_year_and_trims_title_and_part_number():
    response = _put_product(
        "usr_put_trim",
        {
            "title": "  CP3 Pump ",
            "partNumber": " 0445020150 ",
            "price": 100,
            "yearFrom": "",
            "yearTo": None,
        },
    )

    assert response.status_code == 200, response.content
    data = Product.objects.get(pk="prod_v").data
    assert (data["title"], data["partNumber"]) == ("CP3 Pump", "0445020150")
    assert "yearFrom" not in data and "yearTo" not in data


@pytest.mark.django_db
def test_put_allows_a_part_number_already_used_by_another_product():
    # El catálogo de origen repite números de parte (un mismo núcleo para dos
    # aplicaciones): no hay unicidad que exigir.
    Product.objects.create(id="prod_other", data={"title": "Other", "partNumber": "0445020150"})

    response = _put_product("usr_put_dup", VALID_PRODUCT)

    assert response.status_code == 200
