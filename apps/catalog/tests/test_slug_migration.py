"""Backfill del slug (`catalog/0004_product_slug` + `0005_product_slug_unique`).

Migra la base de test hacia atrás hasta `0003`, inserta productos con el
modelo histórico y vuelve a migrar hacia adelante: cada fila existente sale con
un slug único y la columna queda obligatoria. Sin proveedores que mockear.
"""
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("catalog", "0003_managed_catalog")]
AFTER = [("catalog", "0005_product_slug_unique")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_products_get_unique_slugs():
    old_apps = _migrate(BEFORE)
    OldProduct = old_apps.get_model("catalog", "Product")
    OldProduct.objects.create(id="a", data={"title": "Lift Pump", "partNumber": "LP-1"})
    OldProduct.objects.create(id="b", data={"title": "Lift Pump", "partNumber": "LP-1"})
    OldProduct.objects.create(id="Weird_ID", data={})
    try:
        new_apps = _migrate(AFTER)
        Product = new_apps.get_model("catalog", "Product")

        slugs = dict(Product.objects.values_list("id", "slug"))
        assert slugs == {"a": "lift-pump-lp-1", "b": "lift-pump-lp-1-2", "Weird_ID": "weird_id"}
    finally:
        _migrate(AFTER)
