"""Las FKs aplican su `on_delete` también en Postgres, no solo en el ORM.

Django 5.2 crea toda FK como `NO ACTION` y resuelve `SET_NULL` y `CASCADE` en
Python; un `DELETE` hecho fuera del ORM (psql, un script de mantenimiento)
fallaría o dejaría filas huérfanas. Estos tests leen `pg_constraint` y borran
con SQL crudo a propósito, porque eso es lo que prueban. Si un `AlterField`
futuro recrea una de estas FKs, Django la vuelve a crear sin `ON DELETE` y el
primer test falla.
"""
import pytest
from django.db import connection

from apps.auth.models import AccountToken
from apps.checkout.models import Order, Payment
from apps.customers.models import Customer
from apps.quotes.models import Quote
from tests.factories import create_customer, create_user

# `confdeltype` de Postgres: n = SET NULL, c = CASCADE, a = NO ACTION.
EXPECTED_ON_DELETE = {
    ("orders", "customer_id"): "n",
    ("quotes", "customer_id"): "n",
    ("payments", "order_id"): "n",
    ("customers", "user_id"): "n",
    ("account_tokens", "user_id"): "c",
    # `PROTECT` en el ORM: la base también rechaza borrar un Role en uso.
    ("users", "role_id"): "a",
}


def _on_delete_actions():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rel.relname, att.attname, con.confdeltype, con.condeferred
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_attribute att
              ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
            WHERE con.contype = 'f'
            """
        )
        return {(table, column): (action, deferred) for table, column, action, deferred in cursor}


@pytest.mark.django_db
def test_domain_foreign_keys_declare_their_on_delete_in_the_database():
    actions = _on_delete_actions()

    assert {key: actions[key][0] for key in EXPECTED_ON_DELETE} == EXPECTED_ON_DELETE
    # Django las crea diferidas; recrearlas no puede cambiar eso.
    assert all(actions[key][1] for key in EXPECTED_ON_DELETE)


def _raw_delete(table, row_id):
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table} WHERE id = %s", [row_id])


@pytest.mark.django_db
def test_raw_delete_of_a_customer_keeps_its_orders_and_quotes():
    customer = create_customer("CUST1", email="ada@example.com")
    order = Order.objects.create(id="ORD1", number="O1", customer=customer)
    quote = Quote.objects.create(id="QID1", number="Q1", customer=customer)

    _raw_delete("customers", customer.id)

    order.refresh_from_db()
    quote.refresh_from_db()
    assert order.customer_id is None
    assert quote.customer_id is None


@pytest.mark.django_db
def test_raw_delete_of_an_order_keeps_its_payments():
    order = Order.objects.create(id="ORD1", number="O1")
    payment = Payment.objects.create(id="PAY1", order=order, provider="stripe", status="PAID")

    _raw_delete("orders", order.id)

    payment.refresh_from_db()
    assert payment.order_id is None


@pytest.mark.django_db
def test_raw_delete_of_a_user_unlinks_the_profile_and_drops_its_tokens():
    user = create_user("USR1", email="ada@example.com")
    customer = create_customer("CUST1", email="ada@example.com", user=user)
    AccountToken.objects.create(
        user=user,
        purpose=AccountToken.PASSWORD_RESET,
        token_hash="hash",
        email="ada@example.com",
        expires_at="2030-01-01T00:00:00Z",
    )

    _raw_delete("users", user.id)

    customer.refresh_from_db()
    assert customer.user_id is None
    assert Customer.objects.filter(id="CUST1").exists()
    assert not AccountToken.objects.filter(email="ada@example.com").exists()
