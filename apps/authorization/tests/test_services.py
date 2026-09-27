"""Reglas de `apps/authorization/services/` que se prueban sin pasar por
la view: las que dependen de filas bloqueadas y de la concurrencia.

Sin proveedores que mockear. Reglas que se assertean a propósito:

- la regla del último usuario activo con acceso total se evalúa contra la base
  con las filas bloqueadas (`SELECT ... FOR UPDATE`), no contra el `actor` que
  cargó el request: si otro request ya le quitó el acceso total, su cambio no
  pasa;
- dos admins que se quitan el acceso total a la vez no dejan la tienda sin
  ningún usuario activo con acceso total (hilos con `transaction=True`, igual
  que `apps/checkout/tests/test_document_numbers.py`).
"""
import threading

import pytest
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext

from apps.authentication.models import User
from apps.authorization.services import delete_admin_user, update_admin_user
from tests.factories import create_staff_user, create_user


def _locking_user_queries(queries):
    return [
        query["sql"]
        for query in queries
        if 'FROM "users"' in query["sql"] and "FOR UPDATE" in query["sql"]
    ]


@pytest.mark.django_db
def test_update_locks_the_affected_accounts():
    actor = create_staff_user("U_ADMIN", full_access=True)
    create_user("U_PAT")

    with CaptureQueriesContext(connection) as queries:
        result = update_admin_user("U_PAT", {"role": "employee"}, actor)

    assert result.get("ok") is True
    assert _locking_user_queries(queries.captured_queries)


@pytest.mark.django_db
def test_delete_locks_the_affected_accounts():
    actor = create_staff_user("U_ADMIN", full_access=True)
    create_user("U_PAT")

    with CaptureQueriesContext(connection) as queries:
        result = delete_admin_user("U_PAT", actor)

    assert result.get("ok") is True
    assert _locking_user_queries(queries.captured_queries)


@pytest.mark.django_db
def test_last_full_access_rule_reads_the_database_not_the_stale_actor():
    # `actor` sigue en memoria con acceso total, pero otro request ya lo
    # desactivó: B es el último activo con acceso total y no puede perderlo.
    actor = create_staff_user("U_ADMIN_A", full_access=True)
    create_staff_user("U_ADMIN_B", full_access=True)
    User.objects.filter(pk="U_ADMIN_A").update(active=False)

    result = update_admin_user("U_ADMIN_B", {"role": "employee"}, actor)

    assert result.get("status") == 403
    assert User.objects.get(pk="U_ADMIN_B").role.full_access is True


@pytest.mark.django_db
def test_a_demoted_actor_loses_its_privileges_within_the_same_request():
    # El actor perdió el acceso total después de que su request lo cargó: el
    # service vuelve a leer su Role con la fila bloqueada.
    actor = create_staff_user("U_ADMIN_A", full_access=True)
    create_staff_user("U_ADMIN_B", full_access=True)
    create_staff_user("U_ADMIN_C", full_access=True)
    User.objects.filter(pk="U_ADMIN_A").update(role=None)

    result = update_admin_user("U_ADMIN_B", {"role": "employee"}, actor)

    assert result.get("status") == 403
    assert User.objects.get(pk="U_ADMIN_B").role.full_access is True


@pytest.mark.django_db(transaction=True)
def test_two_admins_demoting_each_other_keep_one_full_access_user():
    admin_a = create_staff_user("U_ADMIN_A", full_access=True)
    admin_b = create_staff_user("U_ADMIN_B", full_access=True)
    barrier = threading.Barrier(2)
    results = {}

    def demote(target_id, actor):
        try:
            barrier.wait(timeout=5)
            results[target_id] = update_admin_user(target_id, {"role": "employee"}, actor)
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=demote, args=("U_ADMIN_B", admin_a)),
        threading.Thread(target=demote, args=("U_ADMIN_A", admin_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(result.get("status", 200) for result in results.values()) == [200, 403]
    assert User.objects.filter(active=True, role__full_access=True).count() == 1
