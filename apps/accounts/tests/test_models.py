"""Stage A binding tests for the `users` table (design decision #3).

`User` is `managed = False`: these tests prove Django can read a row shaped
like production data (written here via raw SQL, the same way the frozen
Next.js app writes it) without any schema mutation on Django's side.
"""
import pytest
from django.db import connection

from apps.accounts.models import User


def _insert_user(user_id, username, permissions):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into users (id, username, password_hash, role, active,
                                display_name, permissions)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            [user_id, username, "scrypt$abc$def", "authorized", True,
             "Ana Torres", permissions],
        )


@pytest.mark.django_db
def test_reads_authorized_employee_with_permission_list():
    import json

    _insert_user("usr_1", "ana.torres", json.dumps(["products.edit", "carts.view"]))

    user = User.objects.get(pk="usr_1")

    assert user.username == "ana.torres"
    assert user.role == "authorized"
    assert user.active is True
    assert user.permissions == ["products.edit", "carts.view"]


@pytest.mark.django_db
def test_reads_admin_role_bypassing_permission_list():
    import json

    _insert_user("usr_admin", "admin.root", json.dumps([]))
    with connection.cursor() as cursor:
        cursor.execute("update users set role = %s where id = %s", ["admin", "usr_admin"])

    user = User.objects.get(pk="usr_admin")

    assert user.role == "admin"
    assert user.permissions == []
