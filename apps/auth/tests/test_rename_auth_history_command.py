"""`rename_auth_history`: una base con el historial de las apps viejas queda
con el de `accounts` y `roles`, y correrlo de nuevo no cambia nada."""
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection

from apps.auth.management.commands.rename_auth_history import RENAMED_MIGRATIONS


def _rows(app):
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM django_migrations WHERE app = %s ORDER BY name", [app])
        return [row[0] for row in cursor.fetchall()]


@pytest.mark.django_db
def test_renames_old_history_and_content_types_and_is_idempotent():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM django_migrations WHERE app IN ('accounts', 'roles')")
        for old_app, old_name in RENAMED_MIGRATIONS:
            cursor.execute(
                "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, NOW())",
                [old_app, old_name],
            )
        cursor.execute(
            "UPDATE django_content_type SET app_label = 'authentication' "
            "WHERE app_label = 'accounts' AND model = 'user'"
        )
        cursor.execute(
            "UPDATE django_content_type SET app_label = 'authorization' "
            "WHERE app_label = 'roles' AND model = 'role'"
        )
    ContentType.objects.clear_cache()

    call_command("rename_auth_history")
    call_command("rename_auth_history")

    expected = sorted(RENAMED_MIGRATIONS.values())
    assert [("accounts", n) for n in _rows("accounts")] + [
        ("roles", n) for n in _rows("roles")
    ] == expected
    assert _rows("authentication") == [] and _rows("authorization") == []
    assert ContentType.objects.filter(app_label="accounts", model="user").exists()
    assert ContentType.objects.filter(app_label="roles", model="role").exists()
    old_labels = ["authentication", "authorization"]
    assert not ContentType.objects.filter(app_label__in=old_labels).exists()
