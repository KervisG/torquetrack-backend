"""`/api/admin/users/**` y `/api/admin/roles/` de `apps/authorization/`.

Sin proveedores que mockear. Reglas que se assertean a propósito: el panel no
crea cuentas (no hay `POST`) y el `PUT` solo acepta `role` y `active`; nadie
cambia su propio Role ni su estado; quien no tiene acceso total no reparte ni
toca permisos que no tiene; y las sesiones se revalidan en el request
siguiente (no se borran filas de `django_session`).
"""
import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.authorization.models import Role
from apps.customers.models import Customer
from tests.factories import (
    activity_count,
    create_customer,
    create_role,
    create_staff_user,
    create_user,
    session_client,
)


def _manager_client(user_id="U_MANAGER", full_access=True):
    if full_access:
        create_staff_user(user_id, full_access=True)
    else:
        create_staff_user(user_id, permissions=["users.manage"])
    client, _ = session_client(user_id)
    return client


# --- permisos -----------------------------------------------------------------


@pytest.mark.django_db
def test_list_returns_401_without_session():
    response = APIClient().get("/api/admin/users/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_list_returns_401_for_a_customer_without_role():
    create_user("U_CUSTOMER")
    client, _ = session_client("U_CUSTOMER")

    response = client.get("/api/admin/users/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_list_returns_403_without_users_manage_permission():
    create_staff_user("U_NO_PERM", permissions=["dashboard.view"])
    client, _ = session_client("U_NO_PERM")

    response = client.get("/api/admin/users/")

    assert response.status_code == 403


# --- list ---------------------------------------------------------------------


@pytest.mark.django_db
def test_list_returns_full_access_first_and_exposes_role_and_active():
    client = _manager_client("U_EMPLOYEE", full_access=False)
    create_staff_user("U_OWNER", full_access=True)
    create_user("U_CUSTOMER", first_name="Pat", last_name="Fleet")

    response = client.get("/api/admin/users/")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "U_OWNER"
    customer = next(item for item in body if item["id"] == "U_CUSTOMER")
    assert customer["role"] is None
    assert customer["isStaff"] is False
    assert customer["active"] is True
    assert customer["name"] == "Pat Fleet"
    employee = next(item for item in body if item["id"] == "U_EMPLOYEE")
    assert employee["role"]["slug"] == "role-U_EMPLOYEE"
    assert employee["permissions"] == ["users.manage"]


# --- sin alta desde el panel ------------------------------------------------


@pytest.mark.django_db
def test_create_is_not_allowed_from_the_panel():
    # Toda persona se registra como cliente (`/api/register/`); el panel solo
    # le asigna un Role.
    client = _manager_client("U_CREATOR")

    response = client.post(
        "/api/admin/users/",
        {
            "email": "ana.torres@example.com",
            "password": "s3cret-pass",
            "firstName": "Ana",
            "lastName": "Torres",
            "role": "employee",
        },
        format="json",
    )

    assert response.status_code == 405
    assert not User.objects.filter(email="ana.torres@example.com").exists()


# --- update -------------------------------------------------------------------


@pytest.mark.django_db
def test_update_returns_404_for_unknown_user():
    client = _manager_client("U_UPDATER")

    response = client.put("/api/admin/users/does-not-exist/", {"active": True}, format="json")

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_rejects_deactivating_a_full_access_user():
    client = _manager_client("U_UPDATER2")
    create_staff_user("U_TARGET_OWNER", full_access=True)

    response = client.put(
        "/api/admin/users/U_TARGET_OWNER/", {"active": False}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_update_non_full_access_actor_cannot_edit_a_full_access_user():
    client = _manager_client("U_MANAGER", full_access=False)
    create_staff_user("U_TARGET_OWNER", full_access=True)

    response = client.put(
        "/api/admin/users/U_TARGET_OWNER/", {"role": "employee"}, format="json"
    )

    assert response.status_code == 403
    assert response.json() == {
        "error": "Only a full access user can modify a full access user"
    }
    assert User.objects.get(pk="U_TARGET_OWNER").role.full_access is True


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_update_returns_400_for_a_non_boolean_active(value):
    client = _manager_client("U_UPDATER_BOOL")
    create_staff_user("U_TARGET_BOOL", permissions=["dashboard.view"])

    response = client.put(
        "/api/admin/users/U_TARGET_BOOL/", {"active": value}, format="json"
    )

    assert response.status_code == 400
    assert User.objects.get(pk="U_TARGET_BOOL").active is True


@pytest.mark.django_db
def test_update_deactivating_revokes_the_live_session():
    client = _manager_client("U_UPDATER3")
    create_staff_user("U_TARGET_EMP", permissions=["dashboard.view"])
    target, _ = session_client("U_TARGET_EMP")
    actor_key = client.cookies[settings.SESSION_COOKIE_NAME].value

    response = client.put(
        "/api/admin/users/U_TARGET_EMP/", {"active": False}, format="json"
    )

    assert response.status_code == 200
    assert User.objects.get(pk="U_TARGET_EMP").active is False
    # La fila de sesión sigue, pero en el request siguiente ya no autentica.
    assert target.get("/api/session/").status_code == 401
    assert Session.objects.filter(session_key=actor_key).exists()


@pytest.mark.django_db
def test_update_assigns_a_role_to_a_customer_and_their_session_sees_it():
    client = _manager_client("U_UPDATER_ROLE")
    create_user("U_PROMOTED")
    target, _ = session_client("U_PROMOTED")

    response = client.put(
        "/api/admin/users/U_PROMOTED/", {"role": "employee"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"]["slug"] == "employee"
    assert User.objects.get(pk="U_PROMOTED").role.slug == "employee"
    # Los permisos se leen del Role en cada request: la sesión abierta ya
    # tiene el acceso nuevo sin volver a entrar.
    session = target.get("/api/session/").json()["user"]
    assert session["isStaff"] is True
    assert session["role"]["slug"] == "employee"


@pytest.mark.django_db
def test_update_role_null_removes_panel_access():
    client = _manager_client("U_UPDATER_DEMOTE")
    create_staff_user("U_DEMOTED", permissions=["dashboard.view"])

    response = client.put("/api/admin/users/U_DEMOTED/", {"role": None}, format="json")

    assert response.status_code == 200
    assert User.objects.get(pk="U_DEMOTED").role is None


@pytest.mark.django_db
def test_update_rejects_granting_full_access_from_non_full_access_actor():
    client = _manager_client("U_MANAGER", full_access=False)
    create_user("U_TARGET_UP")

    response = client.put("/api/admin/users/U_TARGET_UP/", {"role": "admin"}, format="json")

    assert response.status_code == 403
    assert response.json() == {"error": "Only a full access user can grant full access"}
    assert User.objects.get(pk="U_TARGET_UP").role is None


@pytest.mark.django_db
def test_update_returns_400_for_an_unknown_role():
    client = _manager_client("U_UPDATER_UNKNOWN")
    create_staff_user("U_TARGET_UNKNOWN", permissions=["dashboard.view"])

    response = client.put(
        "/api/admin/users/U_TARGET_UNKNOWN/", {"role": "nope"}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    "extra",
    [
        {"email": "new@example.com"},
        {"password": "taken-over-123"},
        {"firstName": "Mallory"},
        {"lastName": "Mallory"},
    ],
    ids=["email", "password", "firstName", "lastName"],
)
def test_update_rejects_any_field_other_than_role_and_active(extra):
    client = _manager_client("U_UPDATER_FIELDS")
    target = create_user("U_TARGET_FIELDS", email="pat@example.com", password="Original-Pass-2026!")

    response = client.put(
        "/api/admin/users/U_TARGET_FIELDS/", {"role": "employee", **extra}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Only role and active can be changed"}
    target.refresh_from_db()
    assert target.role is None
    assert target.email == "pat@example.com"
    assert target.check_password("Original-Pass-2026!")
    assert target.first_name == ""


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{"role": None}, {"active": False}, {"role": "employee"}])
def test_update_rejects_changing_your_own_role_or_active_status(payload):
    client = _manager_client("U_SELF_EDIT")

    response = client.put("/api/admin/users/U_SELF_EDIT/", payload, format="json")

    assert response.status_code == 403
    assert response.json() == {"error": "You cannot change your own role or active status"}
    me = User.objects.get(pk="U_SELF_EDIT")
    assert me.active is True
    assert me.role.full_access is True


@pytest.mark.django_db
def test_update_non_full_access_actor_cannot_grant_permissions_it_lacks():
    create_staff_user("U_LIMITED", permissions=["users.manage", "orders.view"])
    client, _ = session_client("U_LIMITED")
    create_role("refunds", permissions=["orders.view", "payments.refund"])
    create_user("U_CUSTOMER_GRANT")

    response = client.put(
        "/api/admin/users/U_CUSTOMER_GRANT/", {"role": "refunds"}, format="json"
    )

    assert response.status_code == 403
    assert response.json() == {"error": "You cannot grant permissions you do not have"}
    assert User.objects.get(pk="U_CUSTOMER_GRANT").role is None


@pytest.mark.django_db
def test_update_non_full_access_actor_can_grant_a_subset_of_its_permissions():
    create_staff_user("U_LIMITED", permissions=["users.manage", "orders.view"])
    client, _ = session_client("U_LIMITED")
    create_role("order-desk", permissions=["orders.view"])
    create_user("U_CUSTOMER_SUBSET")

    response = client.put(
        "/api/admin/users/U_CUSTOMER_SUBSET/", {"role": "order-desk"}, format="json"
    )

    assert response.status_code == 200
    assert User.objects.get(pk="U_CUSTOMER_SUBSET").role.slug == "order-desk"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{"role": None}, {"active": False}])
def test_update_non_full_access_actor_cannot_touch_a_more_privileged_user(payload):
    create_staff_user("U_LIMITED", permissions=["users.manage", "orders.view"])
    client, _ = session_client("U_LIMITED")
    create_staff_user("U_REFUNDER", permissions=["orders.view", "payments.refund"])

    response = client.put("/api/admin/users/U_REFUNDER/", payload, format="json")

    assert response.status_code == 403
    assert response.json() == {
        "error": "You cannot modify a user with permissions you do not have"
    }
    target = User.objects.get(pk="U_REFUNDER")
    assert target.role.slug == "role-U_REFUNDER"
    assert target.active is True


# --- delete -------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_returns_400_when_deleting_own_account():
    client = _manager_client("U_SELF")

    response = client.delete("/api/admin/users/U_SELF/")

    assert response.status_code == 400


@pytest.mark.django_db
def test_delete_returns_403_for_a_full_access_account():
    client = _manager_client("U_DELETER")
    create_staff_user("U_OTHER_OWNER", full_access=True)

    response = client.delete("/api/admin/users/U_OTHER_OWNER/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_removes_the_user_revokes_sessions_and_keeps_the_customer():
    client = _manager_client("U_DELETER2")
    target = create_user("U_TO_DELETE")
    create_customer("C_KEEP", email="U_TO_DELETE@example.com", user=target)
    target, _ = session_client("U_TO_DELETE")

    response = client.delete("/api/admin/users/U_TO_DELETE/")

    assert response.status_code == 200
    assert not User.objects.filter(pk="U_TO_DELETE").exists()
    assert target.get("/api/session/").status_code == 401
    assert Customer.objects.get(pk="C_KEEP").user is None
    assert activity_count(action="USER_DELETED", entity_id="U_TO_DELETE") >= 1


@pytest.mark.django_db
def test_delete_returns_404_for_unknown_user():
    client = _manager_client("U_DELETER3")

    response = client.delete("/api/admin/users/does-not-exist/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_non_full_access_actor_cannot_delete_a_more_privileged_user():
    create_staff_user("U_LIMITED", permissions=["users.manage", "orders.view"])
    client, _ = session_client("U_LIMITED")
    create_staff_user("U_REFUNDER", permissions=["orders.view", "payments.refund"])

    response = client.delete("/api/admin/users/U_REFUNDER/")

    assert response.status_code == 403
    assert response.json() == {
        "error": "You cannot delete a user with permissions you do not have"
    }
    assert User.objects.filter(pk="U_REFUNDER").exists()


@pytest.mark.django_db
def test_delete_non_full_access_actor_can_delete_a_customer():
    create_staff_user("U_LIMITED", permissions=["users.manage"])
    client, _ = session_client("U_LIMITED")
    create_user("U_PLAIN_CUSTOMER")

    response = client.delete("/api/admin/users/U_PLAIN_CUSTOMER/")

    assert response.status_code == 200
    assert not User.objects.filter(pk="U_PLAIN_CUSTOMER").exists()


# --- roles --------------------------------------------------------------------


@pytest.mark.django_db
def test_roles_returns_401_without_session():
    assert APIClient().get("/api/admin/roles/").status_code == 401


@pytest.mark.django_db
def test_roles_returns_403_without_users_manage_permission():
    create_staff_user("U_ROLES_NO_PERM", permissions=["dashboard.view"])
    client, _ = session_client("U_ROLES_NO_PERM")

    assert client.get("/api/admin/roles/").status_code == 403


@pytest.mark.django_db
def test_roles_lists_every_role_with_slug_name_and_full_access():
    client = _manager_client("U_ROLES")
    create_role("parts-desk", name="Parts desk")

    response = client.get("/api/admin/roles/")

    assert response.status_code == 200
    body = response.json()
    assert {"slug": "admin", "name": "Admin", "fullAccess": True} == {
        key: value
        for key, value in body[0].items()
        if key not in {"id", "permissions"}
    }
    slugs = [item["slug"] for item in body]
    assert "employee" in slugs and "parts-desk" in slugs
    assert all(set(item) == {"id", "slug", "name", "fullAccess", "permissions"} for item in body)
    assert body[0]["id"] == Role.objects.get(slug="admin").pk
    assert "users.manage" in body[0]["permissions"]


@pytest.mark.django_db
def test_create_role_saves_the_name_as_a_slug_and_its_permissions():
    client = _manager_client("U_ROLE_CREATE")

    response = client.post(
        "/api/admin/roles/",
        {"name": "Parts Desk", "fullAccess": False, "permissions": ["orders.view", "orders.view"]},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "parts-desk"
    assert body["permissions"] == ["orders.view"]
    role = Role.objects.get(slug="parts-desk")
    assert role.name == "Parts Desk"
    assert activity_count(action="ROLE_CREATED", entity_id=str(role.pk)) == 1


@pytest.mark.django_db
def test_create_role_rejects_a_duplicate_name():
    client = _manager_client("U_ROLE_DUP")

    response = client.post(
        "/api/admin/roles/",
        {"name": "Admin", "permissions": []},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "A role with this name already exists"}


@pytest.mark.django_db
def test_create_role_rejects_permissions_the_actor_does_not_have():
    client = _manager_client("U_ROLE_LIMITED", full_access=False)

    response = client.post(
        "/api/admin/roles/",
        {"name": "Refunds", "fullAccess": False, "permissions": ["payments.refund"]},
        format="json",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "You cannot grant permissions you do not have"}
    assert not Role.objects.filter(slug="refunds").exists()


@pytest.mark.django_db
def test_update_role_renames_and_replaces_permissions_without_changing_the_slug():
    client = _manager_client("U_ROLE_EDIT")
    create_role("parts-desk", name="Parts desk", permissions=["orders.view"])

    response = client.put(
        "/api/admin/roles/parts-desk/",
        {"name": "Counter", "fullAccess": False, "permissions": ["quotes.view"]},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["slug"] == "parts-desk"
    assert response.json()["name"] == "Counter"
    assert response.json()["permissions"] == ["quotes.view"]
    role_id = str(Role.objects.get(slug="parts-desk").pk)
    assert activity_count(action="ROLE_UPDATED", entity_id=role_id) == 1


@pytest.mark.django_db
def test_update_role_refuses_to_remove_the_only_full_access_role():
    admin = Role.objects.get(slug="admin")
    create_user("U_ROLE_LAST", role=admin)
    client, _ = session_client("U_ROLE_LAST")

    response = client.put(
        "/api/admin/roles/admin/",
        {"name": "Admin", "fullAccess": False, "permissions": ["users.manage"]},
        format="json",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "At least one active full access user is required"}
    assert Role.objects.get(slug="admin").full_access is True
