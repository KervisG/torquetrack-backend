"""`/api/admin/users/`, `/api/admin/users/[id]/` y `/api/admin/roles/`.

Separa 401 (sin sesión de staff) de 403 (staff sin `users.manage`). El Role
se identifica por `slug` en todo el contrato. Cambiar el Role, la
contraseña o desactivar corta las sesiones vivas del usuario.
"""
import re

import pytest
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.sessions.models import Session
from rest_framework.test import APIClient

from apps.auth.models import Role, User
from apps.backoffice.models import ActivityLog
from apps.customers.models import Customer
from tests.factories import (
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


# --- create -------------------------------------------------------------------


def _create_payload(**overrides):
    payload = {
        "email": "Ana.Torres@example.com",
        "password": "s3cret-pass",
        "firstName": "Ana",
        "lastName": "Torres",
        "role": "employee",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_create_returns_401_without_session():
    response = APIClient().post("/api/admin/users/", _create_payload(), format="json")

    assert response.status_code == 401
    assert not User.objects.filter(email="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_returns_403_without_users_manage_permission():
    create_staff_user("U_CREATE_NO_PERM", permissions=["dashboard.view"])
    client, _ = session_client("U_CREATE_NO_PERM")

    response = client.post("/api/admin/users/", _create_payload(), format="json")

    assert response.status_code == 403
    assert not User.objects.filter(email="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_stores_user_with_explicit_role():
    client = _manager_client("U_CREATOR")

    response = client.post("/api/admin/users/", _create_payload(), format="json")

    assert response.status_code == 201
    body = response.json()["user"]
    assert body["email"] == "ana.torres@example.com"
    assert body["name"] == "Ana Torres"
    assert body["role"]["slug"] == "employee"
    assert body["active"] is True

    user = User.objects.get(email="ana.torres@example.com")
    assert user.first_name == "Ana"
    assert user.last_name == "Torres"
    assert user.role.slug == "employee"
    assert check_password("s3cret-pass", user.password_hash)
    assert ActivityLog.objects.filter(
        action="USER_CREATED", entity_id=user.pk, actor_id="U_CREATOR@example.com".lower()
    ).exists()


@pytest.mark.django_db
def test_create_ignores_client_chosen_id():
    client = _manager_client("U_CREATOR_ID")

    response = client.post(
        "/api/admin/users/", _create_payload(id="usr_chosen"), format="json"
    )

    assert response.status_code == 201
    user_id = response.json()["user"]["id"]
    assert user_id != "usr_chosen"
    assert re.fullmatch(r"U[0-9A-F]{12}", user_id)


@pytest.mark.django_db
def test_create_returns_400_without_required_fields():
    client = _manager_client("U_CREATOR_REQ")

    response = client.post(
        "/api/admin/users/", {"email": "nopass@example.com", "role": "employee"}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "Email, password, first name and last name required"
    }


@pytest.mark.django_db
@pytest.mark.parametrize("role", [None, "", "does-not-exist"])
def test_create_returns_400_for_missing_or_unknown_role(role):
    client = _manager_client("U_CREATOR_ROLE")

    response = client.post("/api/admin/users/", _create_payload(role=role), format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "Valid role required"}
    assert not User.objects.filter(email="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_rejects_full_access_role_from_non_full_access_actor():
    client = _manager_client("U_MANAGER", full_access=False)

    response = client.post("/api/admin/users/", _create_payload(role="admin"), format="json")

    assert response.status_code == 403
    assert not User.objects.filter(email="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_returns_400_for_a_non_boolean_active():
    client = _manager_client("U_CREATOR_ACTIVE")

    response = client.post(
        "/api/admin/users/", _create_payload(active="false"), format="json"
    )

    assert response.status_code == 400
    assert not User.objects.filter(email="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_returns_409_on_duplicate_email():
    client = _manager_client("U_CREATOR_DUP")
    create_user("U_EXISTING", email="ana.torres@example.com")

    response = client.post("/api/admin/users/", _create_payload(), format="json")

    assert response.status_code == 409
    assert response.json() == {"error": "Email already exists"}


# --- update -------------------------------------------------------------------


@pytest.mark.django_db
def test_update_returns_404_for_unknown_user():
    client = _manager_client("U_UPDATER")

    response = client.put("/api/admin/users/does-not-exist/", {"firstName": "X"}, format="json")

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
        "/api/admin/users/U_TARGET_OWNER/", {"password": "taken-over-123"}, format="json"
    )

    assert response.status_code == 403


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
    _, target_key = session_client("U_TARGET_EMP")
    actor_key = client.cookies[settings.SESSION_COOKIE_NAME].value

    response = client.put(
        "/api/admin/users/U_TARGET_EMP/", {"active": False}, format="json"
    )

    assert response.status_code == 200
    assert User.objects.get(pk="U_TARGET_EMP").active is False
    assert not Session.objects.filter(session_key=target_key).exists()
    assert Session.objects.filter(session_key=actor_key).exists()


@pytest.mark.django_db
def test_update_password_change_revokes_the_live_session():
    client = _manager_client("U_UPDATER_PW")
    create_staff_user("U_TARGET_PW", permissions=["dashboard.view"])
    _, target_key = session_client("U_TARGET_PW")

    response = client.put(
        "/api/admin/users/U_TARGET_PW/", {"password": "new-pass-456"}, format="json"
    )

    assert response.status_code == 200
    assert check_password("new-pass-456", User.objects.get(pk="U_TARGET_PW").password_hash)
    assert not Session.objects.filter(session_key=target_key).exists()


@pytest.mark.django_db
def test_update_assigns_a_role_to_a_customer_and_revokes_their_session():
    client = _manager_client("U_UPDATER_ROLE")
    create_user("U_PROMOTED")
    _, target_key = session_client("U_PROMOTED")

    response = client.put(
        "/api/admin/users/U_PROMOTED/", {"role": "employee"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"]["slug"] == "employee"
    assert User.objects.get(pk="U_PROMOTED").role.slug == "employee"
    assert not Session.objects.filter(session_key=target_key).exists()


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
    create_staff_user("U_TARGET_UP", permissions=["dashboard.view"])

    response = client.put("/api/admin/users/U_TARGET_UP/", {"role": "admin"}, format="json")

    assert response.status_code == 403
    assert User.objects.get(pk="U_TARGET_UP").role.full_access is False


@pytest.mark.django_db
def test_update_returns_400_for_an_unknown_role():
    client = _manager_client("U_UPDATER_UNKNOWN")
    create_staff_user("U_TARGET_UNKNOWN", permissions=["dashboard.view"])

    response = client.put(
        "/api/admin/users/U_TARGET_UNKNOWN/", {"role": "nope"}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_update_cannot_demote_the_last_full_access_user():
    client = _manager_client("U_ONLY_OWNER")

    response = client.put(
        "/api/admin/users/U_ONLY_OWNER/", {"role": "employee"}, format="json"
    )

    assert response.status_code == 403
    assert User.objects.get(pk="U_ONLY_OWNER").role.full_access is True


@pytest.mark.django_db
def test_update_returns_409_on_duplicate_email():
    client = _manager_client("U_UPDATER_DUP")
    create_user("U_TAKEN", email="taken@example.com")
    create_staff_user("U_RENAMED", permissions=["dashboard.view"])

    response = client.put(
        "/api/admin/users/U_RENAMED/", {"email": "Taken@Example.com"}, format="json"
    )

    assert response.status_code == 409
    assert response.json() == {"error": "Email already exists"}


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
    _, target_key = session_client("U_TO_DELETE")

    response = client.delete("/api/admin/users/U_TO_DELETE/")

    assert response.status_code == 200
    assert not User.objects.filter(pk="U_TO_DELETE").exists()
    assert not Session.objects.filter(session_key=target_key).exists()
    assert Customer.objects.get(pk="C_KEEP").user is None
    assert ActivityLog.objects.filter(action="USER_DELETED", entity_id="U_TO_DELETE").exists()


@pytest.mark.django_db
def test_delete_returns_404_for_unknown_user():
    client = _manager_client("U_DELETER3")

    response = client.delete("/api/admin/users/does-not-exist/")

    assert response.status_code == 404


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
        key: value for key, value in body[0].items() if key != "id"
    }
    slugs = [item["slug"] for item in body]
    assert "employee" in slugs and "parts-desk" in slugs
    assert all(set(item) == {"id", "slug", "name", "fullAccess"} for item in body)
    assert body[0]["id"] == Role.objects.get(slug="admin").pk
