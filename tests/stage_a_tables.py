"""Single source of truth for the Stage A table names bound by `managed =
False` models (design decision #3), shared between `conftest.py` (which
snapshots the pre-`schema.sql` table list) and the no-mutation test.

`users` y `customers` ya no están aquí: sus modelos son administrados por
Django y `migrate` crea esas tablas (ver `DJANGO_MANAGED_TABLES`).
"""
STAGE_A_TABLES = {
    "products",
    "applications",
    "carts",
    "quotes",
    "orders",
    "payments",
}

# Tablas que antes venían de `schema.sql` y ahora crea `migrate`.
DJANGO_MANAGED_TABLES = {"users", "customers"}
