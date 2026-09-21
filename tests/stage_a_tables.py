"""Single source of truth for the Stage A table names bound by `managed =
False` models (design decision #3), shared between `conftest.py` (which
snapshots the pre-`schema.sql` table list) and the no-mutation test.
"""
STAGE_A_TABLES = {
    "products",
    "applications",
    "users",
    "customers",
    "carts",
    "quotes",
    "orders",
    "payments",
}
