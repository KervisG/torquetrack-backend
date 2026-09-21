"""RED/GREEN evidence for the RBAC data migration (design decision #6,
task 3.3): the 26 permission strings from `lib/permissions.ts` become
Django `Permission` codenames 1:1, plus an `employee_default` Group
holding exactly the 15 `DEFAULT_EMPLOYEE_PERMISSIONS`.

Both lists below are copied verbatim from `lib/permissions.ts` (re-read
directly from the file in this session, not from memory/design-doc
paraphrase) so this test fails if the migration ever drifts from the
real source of truth.
"""
import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# Verbatim from lib/permissions.ts `PERMISSIONS` (26 entries), dot -> underscore.
PERMISSION_STRINGS = [
    "dashboard.view",
    "products.view",
    "products.edit",
    "pricing.edit",
    "costs.view",
    "quotes.view",
    "quotes.create",
    "quotes.edit",
    "quotes.send",
    "quotes.convert",
    "quotes.delete",
    "carts.view",
    "orders.view",
    "orders.status",
    "orders.cancel",
    "payments.take",
    "payments.refund",
    "payments.transaction_id",
    "cores.manage",
    "returns.manage",
    "customers.view",
    "customers.edit",
    "customers.delete",
    "tax_exemptions.review",
    "activity.view",
    "users.manage",
]

# Verbatim from lib/permissions.ts `DEFAULT_EMPLOYEE_PERMISSIONS` (15 entries).
DEFAULT_EMPLOYEE_PERMISSION_STRINGS = [
    "dashboard.view",
    "products.view",
    "quotes.view",
    "quotes.create",
    "quotes.edit",
    "quotes.send",
    "quotes.convert",
    "carts.view",
    "orders.view",
    "orders.status",
    "payments.take",
    "cores.manage",
    "returns.manage",
    "customers.view",
    "customers.edit",
]


def _codename(permission_string: str) -> str:
    return permission_string.replace(".", "_")


@pytest.mark.django_db
def test_lib_permissions_ts_source_lists_have_the_expected_counts():
    """Sanity check on the fixture data itself, not the migration."""
    assert len(PERMISSION_STRINGS) == 26
    assert len(DEFAULT_EMPLOYEE_PERMISSION_STRINGS) == 15
    assert set(DEFAULT_EMPLOYEE_PERMISSION_STRINGS).issubset(set(PERMISSION_STRINGS))


@pytest.mark.django_db
def test_migration_creates_all_26_permission_codenames_1_to_1():
    content_type = ContentType.objects.get(
        app_label="accounts", model="torquetrackpermission"
    )
    codenames = set(
        Permission.objects.filter(content_type=content_type).values_list(
            "codename", flat=True
        )
    )

    expected = {_codename(p) for p in PERMISSION_STRINGS}
    assert codenames == expected
    assert len(codenames) == 26


@pytest.mark.django_db
def test_migration_creates_employee_default_group_with_exactly_15_permissions():
    group = Group.objects.get(name="employee_default")
    codenames = set(group.permissions.values_list("codename", flat=True))

    expected = {_codename(p) for p in DEFAULT_EMPLOYEE_PERMISSION_STRINGS}
    assert codenames == expected
    assert group.permissions.count() == 15
