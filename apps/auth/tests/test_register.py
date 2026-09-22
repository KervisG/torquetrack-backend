"""`POST /api/register/` — alta general. El rol lo asigna el sistema."""
import json

import pytest
from django.contrib.auth.hashers import check_password
from django.db import connection
from rest_framework.test import APIClient

from apps.auth.models import EmployeeRole, User
from apps.backoffice.models import ActivityLog


def _insert_user(user_id, username):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into users (id, username, password_hash, role, active, "
            "permissions, created_at) values (%s, %s, %s, %s, %s, %s::jsonb, now())",
            [user_id, username, "scrypt$salt$hash", "authorized", True, json.dumps([])],
        )


@pytest.mark.django_db
def test_register_returns_400_without_required_fields():
    response = APIClient().post(
        "/api/register/", {"email": "nopass@example.com"}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "Email, password, first name and last name required"
    }


@pytest.mark.django_db
def test_register_stores_email_name_and_assigns_system_role():
    response = APIClient().post(
        "/api/register/",
        {
            "email": "ana.torres@example.com",
            "password": "s3cret-pass",
            "firstName": "Ana",
            "lastName": "Torres",
            "role": "admin",
            "permissions": ["users.manage"],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()["user"]
    assert body["email"] == "ana.torres@example.com"
    assert body["firstName"] == "Ana"
    assert body["lastName"] == "Torres"
    assert body["name"] == "Ana Torres"
    assert body["roleSlug"] == "employee"
    assert body["role"] != "admin"

    user = User.objects.get(username="ana.torres@example.com")
    assert user.first_name == "Ana"
    assert user.last_name == "Torres"
    assert check_password("s3cret-pass", user.password_hash)
    assert EmployeeRole.objects.get(user_id=user.pk).role.slug == "employee"
    assert ActivityLog.objects.filter(action="USER_CREATED", entity_id=user.pk).exists()


@pytest.mark.django_db
def test_register_returns_409_on_duplicate_email():
    _insert_user("usr_existing", "taken@example.com")

    response = APIClient().post(
        "/api/register/",
        {
            "email": "taken@example.com",
            "password": "s3cret-pass",
            "firstName": "Taken",
            "lastName": "User",
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.json() == {"error": "Email already exists"}
