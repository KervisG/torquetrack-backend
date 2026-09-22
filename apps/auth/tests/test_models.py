"""Binding Stage A de `users`: Django lee una fila escrita con SQL crudo
sin mutar el esquema.
"""
import json

import pytest
from django.db import connection

from apps.auth.models import User


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
    _insert_user("usr_1", "ana.torres", json.dumps(["products.edit", "carts.view"]))

    user = User.objects.get(pk="usr_1")

    assert user.username == "ana.torres"
    assert user.role == "authorized"
    assert user.active is True
    assert user.permissions == ["products.edit", "carts.view"]


@pytest.mark.django_db
def test_reads_admin_role_bypassing_permission_list():
    _insert_user("usr_admin", "admin.root", json.dumps([]))
    with connection.cursor() as cursor:
        cursor.execute("update users set role = %s where id = %s", ["admin", "usr_admin"])

    user = User.objects.get(pk="usr_admin")

    assert user.role == "admin"
    assert user.permissions == []
