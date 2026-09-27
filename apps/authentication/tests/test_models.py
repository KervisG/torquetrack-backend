import re

import pytest
from django.db import IntegrityError, connection
from django.db.models import ProtectedError

from apps.authentication.models import User
from apps.authorization.models import Role


@pytest.mark.django_db
def test_email_is_stored_lowercased_and_trimmed():
    user = User.objects.create(email="  Ana.Torres@Example.COM ", password="!")

    user.refresh_from_db()
    assert user.email == "ana.torres@example.com"


@pytest.mark.django_db
def test_email_is_unique_regardless_of_input_case():
    User.objects.create(email="ana@example.com", password="!")

    with pytest.raises(IntegrityError):
        User.objects.create(email="ANA@example.com", password="!")


@pytest.mark.django_db
def test_id_and_created_at_are_generated_by_the_server():
    user = User.objects.create(email="gen@example.com", password="!")

    assert re.fullmatch(r"U[0-9A-F]{12}", user.pk)
    assert user.created_at is not None


@pytest.mark.django_db
def test_role_is_optional_and_protected_from_deletion():
    role = Role.objects.create(name="Parts", slug="parts")
    customer = User.objects.create(email="c@example.com", password="!")
    staff = User.objects.create(email="s@example.com", password="!", role=role)

    assert customer.role is None
    assert staff.role == role
    with pytest.raises(ProtectedError):
        role.delete()


def test_user_has_no_username_or_permissions_field():
    field_names = {field.name for field in User._meta.get_fields()}

    assert "username" not in field_names
    assert "permissions" not in field_names
    assert User._meta.get_field("role").is_relation


@pytest.mark.django_db
def test_users_table_has_no_username_or_permissions_column():
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, "users")
        }

    assert "username" not in columns
    assert "permissions" not in columns
    assert {"email", "role_id", "password", "last_login"}.issubset(columns)
    assert "password_hash" not in columns
