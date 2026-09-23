"""`/api/admin/users/` y `/api/admin/users/[id]/`.

Separa 401 (sin sesión) de 403 (sesión sin `users.manage`).
"""
import json
import re
from importlib import import_module

import pytest
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import connection
from rest_framework.test import APIClient

from apps.auth.models import EmployeeRole, User
from apps.backoffice.models import ActivityLog


def _insert_user(user_id, role="authorized", permissions=None, active=True, username=None):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into users (id, username, password_hash, role, active, "
            "permissions, created_at) values (%s, %s, %s, %s, %s, %s::jsonb, now())",
            [
                user_id,
                username or f"{user_id}@example.com",
                "scrypt$salt$hash",
                role,
                active,
                json.dumps(permissions or []),
            ],
        )


def _admin_client(user_id):
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store["user_id"] = user_id
    store.save()
    client = APIClient()
    client.cookies["tt_admin"] = store.session_key
    return client


@pytest.mark.django_db
def test_list_returns_401_without_session():
    response = APIClient().get("/api/admin/users/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_list_returns_403_without_users_manage_permission():
    _insert_user("usr_list_no_perm", permissions=["dashboard.view"])
    client = _admin_client("usr_list_no_perm")

    response = client.get("/api/admin/users/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_list_returns_admin_first_then_by_created_at():
    _insert_user("usr_employee", role="authorized", permissions=["users.manage"])
    _insert_user("usr_admin", role="admin")
    client = _admin_client("usr_employee")

    response = client.get("/api/admin/users/")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "usr_admin"


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
    assert not User.objects.filter(username="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_returns_403_without_users_manage_permission():
    _insert_user("usr_create_no_perm", permissions=["dashboard.view"])
    client = _admin_client("usr_create_no_perm")

    response = client.post("/api/admin/users/", _create_payload(), format="json")

    assert response.status_code == 403
    assert not User.objects.filter(username="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_stores_user_with_explicit_role():
    _insert_user("usr_creator", role="admin")
    client = _admin_client("usr_creator")

    response = client.post("/api/admin/users/", _create_payload(), format="json")

    assert response.status_code == 201
    body = response.json()["user"]
    assert body["email"] == "ana.torres@example.com"
    assert body["name"] == "Ana Torres"
    assert body["roleSlug"] == "employee"

    user = User.objects.get(username="ana.torres@example.com")
    assert user.first_name == "Ana"
    assert user.last_name == "Torres"
    assert check_password("s3cret-pass", user.password_hash)
    assert EmployeeRole.objects.get(user_id=user.pk).role.slug == "employee"
    assert ActivityLog.objects.filter(
        action="USER_CREATED", entity_id=user.pk, actor_id="usr_creator@example.com"
    ).exists()


@pytest.mark.django_db
def test_create_ignores_client_chosen_id():
    _insert_user("usr_creator_id", role="admin")
    client = _admin_client("usr_creator_id")

    response = client.post(
        "/api/admin/users/", _create_payload(id="usr_chosen"), format="json"
    )

    assert response.status_code == 201
    user_id = response.json()["user"]["id"]
    assert user_id != "usr_chosen"
    assert re.fullmatch(r"U[0-9A-F]{12}", user_id)
    assert not User.objects.filter(pk="usr_chosen").exists()


@pytest.mark.django_db
def test_create_returns_400_without_required_fields():
    _insert_user("usr_creator_req", role="admin")
    client = _admin_client("usr_creator_req")

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
    _insert_user("usr_creator_role", role="admin")
    client = _admin_client("usr_creator_role")

    response = client.post("/api/admin/users/", _create_payload(role=role), format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "Valid role required"}
    assert not User.objects.filter(username="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_rejects_full_access_role_from_non_full_access_actor():
    _insert_user("usr_manager", role="authorized", permissions=["users.manage"])
    client = _admin_client("usr_manager")

    response = client.post("/api/admin/users/", _create_payload(role="admin"), format="json")

    assert response.status_code == 403
    assert not User.objects.filter(username="ana.torres@example.com").exists()


@pytest.mark.django_db
def test_create_returns_409_on_duplicate_email():
    _insert_user("usr_creator_dup", role="admin")
    _insert_user("usr_existing", username="ana.torres@example.com")
    client = _admin_client("usr_creator_dup")

    response = client.post("/api/admin/users/", _create_payload(), format="json")

    assert response.status_code == 409
    assert response.json() == {"error": "Email already exists"}


@pytest.mark.django_db
def test_update_returns_404_for_unknown_user():
    _insert_user("usr_updater", role="admin")
    client = _admin_client("usr_updater")

    response = client.put("/api/admin/users/does-not-exist/", {"name": "X"}, format="json")

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_rejects_deactivating_the_primary_admin():
    _insert_user("usr_updater2", role="admin")
    _insert_user("usr_target_admin", role="admin", username="target-admin")
    client = _admin_client("usr_updater2")

    response = client.put(
        "/api/admin/users/usr_target_admin/", {"active": False}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_update_non_admin_can_deactivate():
    _insert_user("usr_updater3", role="admin")
    _insert_user("usr_target_emp", role="authorized", permissions=["dashboard.view"])
    client = _admin_client("usr_updater3")

    response = client.put(
        "/api/admin/users/usr_target_emp/",
        {"active": False},
        format="json",
    )

    assert response.status_code == 200
    user = User.objects.get(pk="usr_target_emp")
    assert user.active is False


@pytest.mark.django_db
def test_delete_returns_400_when_deleting_own_account():
    _insert_user("usr_self", role="admin")
    client = _admin_client("usr_self")

    response = client.delete("/api/admin/users/usr_self/")

    assert response.status_code == 400


@pytest.mark.django_db
def test_delete_returns_403_for_primary_admin_account():
    _insert_user("usr_deleter", role="admin")
    _insert_user("usr_other_admin", role="admin")
    client = _admin_client("usr_deleter")

    response = client.delete("/api/admin/users/usr_other_admin/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_removes_employee_and_logs_activity():
    _insert_user("usr_deleter2", role="admin")
    _insert_user("usr_employee_to_delete", role="authorized")
    client = _admin_client("usr_deleter2")

    response = client.delete("/api/admin/users/usr_employee_to_delete/")

    assert response.status_code == 200
    assert not User.objects.filter(pk="usr_employee_to_delete").exists()
    assert not EmployeeRole.objects.filter(user_id="usr_employee_to_delete").exists()
    assert ActivityLog.objects.filter(
        action="USER_DELETED", entity_id="usr_employee_to_delete"
    ).exists()


@pytest.mark.django_db
def test_delete_returns_404_for_unknown_user():
    _insert_user("usr_deleter3", role="admin")
    client = _admin_client("usr_deleter3")

    response = client.delete("/api/admin/users/does-not-exist/")

    assert response.status_code == 404
