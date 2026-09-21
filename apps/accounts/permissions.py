"""DRF permission class for the 26-string RBAC catalog (design decision
#6, task 3.3).

`apps.accounts.models.User` is a Stage A `managed = False` binding over
the existing `users` table (`role` text column, `permissions` jsonb
column) — it is NOT a Django `AbstractBaseUser`/`PermissionsMixin`
subclass (no login views exist yet; that conversion is out of this
phase's scope, see apply-progress deviations). `HasTorqueTrackPermission`
therefore checks `role`/`permissions` on that Stage A row directly,
mirroring `lib/auth.ts`'s `hasPermission()` exactly:

    if(!user) return false;
    if(role === "admin") return true;
    return permissions.includes(permission);

The 26 Django `Permission` codenames created by
`0003_rbac_permissions.py` back the admin UI / auditability side of
design decision #6 (native Django Groups/Permissions), while the
runtime authorization check below reads the jsonb `permissions` array
that the frozen Next.js app still owns during the strangler migration.
"""

from rest_framework.permissions import BasePermission

from apps.accounts.models import User

# The dotted 26-string RBAC catalog (`lib/permissions.ts`'s `PERMISSIONS`),
# re-derived and confirmed in `docs/migration/phase-0-infra-env-validation.md`
# (Phase 0, task 0.3). Distinct from `0003_rbac_permissions.py`'s
# underscored Django `Permission` codenames (`products.edit` ->
# `products_edit`), which back the admin-UI/auditability side of design
# decision #6 — THIS list is the runtime jsonb `users.permissions` string
# form that `HasTorqueTrackPermission` and `apps.accounts.services` both
# read/write directly, matching `lib/auth.ts`'s `hasPermission()`.
PERMISSIONS = [
    "dashboard.view", "products.view", "products.edit", "pricing.edit", "costs.view",
    "quotes.view", "quotes.create", "quotes.edit", "quotes.send", "quotes.convert",
    "quotes.delete", "carts.view", "orders.view", "orders.status", "orders.cancel",
    "payments.take", "payments.refund", "payments.transaction_id", "cores.manage",
    "returns.manage", "customers.view", "customers.edit", "customers.delete",
    "tax_exemptions.review", "activity.view", "users.manage",
]

DEFAULT_EMPLOYEE_PERMISSIONS = [
    "dashboard.view", "products.view", "quotes.view", "quotes.create", "quotes.edit",
    "quotes.send", "quotes.convert", "carts.view", "orders.view", "orders.status",
    "payments.take", "cores.manage", "returns.manage", "customers.view", "customers.edit",
]


def normalize_permissions(value) -> list[str]:
    """Mirror `lib/permissions.ts`'s `normalizePermissions`: dedupe while
    preserving first-seen order, keep only strings in the known catalog."""
    if not isinstance(value, list):
        value = []
    seen: dict[str, None] = {}
    for raw in value:
        candidate = str(raw)
        if candidate in PERMISSIONS:
            seen.setdefault(candidate, None)
    return list(seen)


def is_active_admin_user(user) -> bool:
    """Mirror `requireAdmin()`'s null-on-no-session/inactive-user check,
    independent of any specific permission."""
    return isinstance(user, User) and user.active


def has_torquetrack_permission(user, permission: str | None) -> bool:
    """Mirror `lib/auth.ts`'s `hasPermission()`. `permission=None` means
    "any active user", matching `HasTorqueTrackPermission`'s legacy
    default when a view sets no `required_permission`."""
    if not is_active_admin_user(user):
        return False
    if str(user.role).lower() == "admin":
        return True
    if permission is None:
        return True
    return permission in (user.permissions or [])


class HasTorqueTrackPermission(BasePermission):
    """Set `required_permission = "<permission.string>"` on the view.
    If unset, any active `apps.accounts.models.User` is allowed."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        required = getattr(view, "required_permission", None)
        return has_torquetrack_permission(user, required)
