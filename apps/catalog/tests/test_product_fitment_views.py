"""`applicationIds` en `GET /api/products/` y `/api/products/<id>/` (storefront)
y en `GET`/`PUT /api/admin/products/` (panel). Sin proveedores que mockear.

`applicationIds` sale de la relación `ProductFitment`, nunca de `data`: sin
filas la clave no aparece en la tienda (el SPA cae al texto, igual que el
checkout) y en el panel es una lista vacía para que el editor la muestre."""
import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Application, Product
from tests.factories import activity_count, create_staff_user, session_client

FORD_73_EARLY = {"id": "ford-73-powerstroke-1994-1997", "make": "Ford", "yearFrom": 1994,
                 "yearTo": 1997, "engine": "7.3", "models": ["F-250"]}
FORD_73_LATE = {**FORD_73_EARLY, "id": "ford-73-powerstroke-1998-2003", "yearFrom": 1998,
                "yearTo": 2003}


def _insert_product(product_id, **data):
    return Product.objects.create(
        id=product_id, data={"id": product_id, "title": "Injector", "price": 100, **data}
    )


def _admin_client(permissions=("products.view", "products.edit")):
    create_staff_user("usr_fitment", permissions=list(permissions))
    client, _ = session_client("usr_fitment")
    return client


# --- storefront ---------------------------------------------------------------


@pytest.mark.django_db
def test_product_detail_returns_application_ids_from_the_relation():
    late = Application.objects.create(data=FORD_73_LATE)
    early = Application.objects.create(data=FORD_73_EARLY)
    product = _insert_product("ford-73-injector", applicationIds=["stale-id"])
    product.applications.set([late, early])

    body = APIClient().get("/api/products/ford-73-injector/").json()

    assert body["applicationIds"] == [
        "ford-73-powerstroke-1994-1997",
        "ford-73-powerstroke-1998-2003",
    ]


@pytest.mark.django_db
def test_product_without_fitment_rows_omits_application_ids():
    _insert_product("ford-73-injector", applicationIds=["ford-73-powerstroke-1994-1997"],
                    make="Ford")

    body = APIClient().get("/api/products/ford-73-injector/").json()

    assert "applicationIds" not in body
    assert body["make"] == "Ford"


@pytest.mark.django_db
def test_product_list_returns_application_ids_per_product():
    early = Application.objects.create(data=FORD_73_EARLY)
    _insert_product("a-linked").applications.set([early])
    _insert_product("b-unlinked")

    body = APIClient().get("/api/products/").json()

    assert body[0]["applicationIds"] == ["ford-73-powerstroke-1994-1997"]
    assert "applicationIds" not in body[1]


@pytest.mark.django_db
def test_application_list_uses_the_code_as_id():
    Application.objects.create(data={"make": "Ford"})

    body = APIClient().get("/api/applications/").json()

    assert body[0]["id"] == Application.objects.get().code


# --- panel --------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_list_includes_application_ids():
    early = Application.objects.create(data=FORD_73_EARLY)
    _insert_product("a-linked").applications.set([early])
    _insert_product("b-unlinked")

    body = _admin_client().get("/api/admin/products/").json()

    assert body[0]["applicationIds"] == ["ford-73-powerstroke-1994-1997"]
    assert body[1]["applicationIds"] == []


@pytest.mark.django_db
def test_admin_put_sets_the_compatible_applications():
    Application.objects.create(data=FORD_73_EARLY)
    Application.objects.create(data=FORD_73_LATE)
    _insert_product("ford-73-injector")

    response = _admin_client().put(
        "/api/admin/products/ford-73-injector/",
        {"title": "Injector", "partNumber": "AP63992", "price": 100,
         "applicationIds": ["ford-73-powerstroke-1998-2003", "ford-73-powerstroke-1994-1997"]},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["product"]["applicationIds"] == [
        "ford-73-powerstroke-1994-1997",
        "ford-73-powerstroke-1998-2003",
    ]
    product = Product.objects.get(pk="ford-73-injector")
    assert sorted(product.applications.values_list("code", flat=True)) == [
        "ford-73-powerstroke-1994-1997",
        "ford-73-powerstroke-1998-2003",
    ]
    # La relación es la fuente: `data` no guarda una copia que se desactualice.
    assert "applicationIds" not in product.data
    assert activity_count(action="PRODUCT_UPDATED", entity_id="ford-73-injector") == 1


@pytest.mark.django_db
def test_admin_put_with_empty_list_clears_the_applications():
    early = Application.objects.create(data=FORD_73_EARLY)
    _insert_product("ford-73-injector").applications.set([early])

    response = _admin_client().put(
        "/api/admin/products/ford-73-injector/",
        {"title": "Injector", "partNumber": "AP63992", "price": 100, "applicationIds": []},
        format="json",
    )

    assert response.status_code == 200
    assert Product.objects.get(pk="ford-73-injector").applications.count() == 0


@pytest.mark.django_db
def test_admin_put_without_application_ids_keeps_the_relation():
    early = Application.objects.create(data=FORD_73_EARLY)
    _insert_product("ford-73-injector").applications.set([early])

    response = _admin_client().put(
        "/api/admin/products/ford-73-injector/",
        {"title": "Injector v2", "partNumber": "AP63992", "price": 100},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["product"]["applicationIds"] == ["ford-73-powerstroke-1994-1997"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("value", "error"),
    [
        (["missing-application"], "Unknown application: missing-application"),
        ("ford-73-powerstroke-1994-1997", "applicationIds must be a list of application ids"),
        ([7], "applicationIds must be a list of application ids"),
    ],
)
def test_admin_put_rejects_invalid_application_ids(value, error):
    Application.objects.create(data=FORD_73_EARLY)
    _insert_product("ford-73-injector", title="Original")

    response = _admin_client().put(
        "/api/admin/products/ford-73-injector/",
        {"title": "Changed", "partNumber": "AP63992", "price": 100, "applicationIds": value},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == error
    assert response.json()["field"] == "application_ids"
    product = Product.objects.get(pk="ford-73-injector")
    assert product.data["title"] == "Original"
    assert product.applications.count() == 0


@pytest.mark.django_db
def test_admin_applications_lists_codes_for_the_editor():
    Application.objects.create(data=FORD_73_LATE)
    Application.objects.create(data=FORD_73_EARLY)

    response = _admin_client(permissions=("products.view",)).get("/api/admin/applications/")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [
        "ford-73-powerstroke-1994-1997",
        "ford-73-powerstroke-1998-2003",
    ]
    assert response.json()[0]["make"] == "Ford"


@pytest.mark.django_db
def test_admin_applications_requires_products_view():
    response = _admin_client(permissions=("orders.view",)).get("/api/admin/applications/")

    assert response.status_code == 403
