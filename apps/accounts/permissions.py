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


class HasTorqueTrackPermission(BasePermission):
    """Set `required_permission = "<permission.string>"` on the view.
    If unset, any active `apps.accounts.models.User` is allowed."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not isinstance(user, User) or not user.active:
            return False
        if str(user.role).lower() == "admin":
            return True

        required = getattr(view, "required_permission", None)
        if required is None:
            return True

        permissions = user.permissions or []
        return required in permissions
