"""Numeración de pedidos (`O<n>`) y cotizaciones (`Q<n>`).

Cada serie vive en una fila de `DocumentSequence` que se bloquea con
`select_for_update()`, así que dos requests concurrentes nunca reciben el
mismo número; estos
tests fijan el formato, el arranque en 10001, la independencia de las series
y la unicidad bajo concurrencia real (hilos con conexiones propias).
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from apps.checkout.models import Order
from apps.checkout.services import next_order_number
from apps.quotes.models import Quote
from apps.quotes.services import next_quote_number


@pytest.mark.django_db
def test_order_numbers_start_at_10001_and_increment():
    assert [next_order_number() for _ in range(3)] == ["O10001", "O10002", "O10003"]


@pytest.mark.django_db
def test_quote_numbers_start_at_10001_and_increment():
    assert [next_quote_number() for _ in range(2)] == ["Q10001", "Q10002"]


@pytest.mark.django_db
def test_order_and_quote_sequences_are_independent():
    next_order_number()
    next_order_number()

    assert next_quote_number() == "Q10001"
    assert next_order_number() == "O10003"


@pytest.mark.django_db
def test_order_number_column_is_unique():
    now = timezone.now()
    Order.objects.create(id="ord_a", number="O10001", data={}, created_at=now, updated_at=now)

    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.create(id="ord_b", number="O10001", data={}, created_at=now, updated_at=now)


@pytest.mark.django_db
def test_quote_number_column_is_unique():
    now = timezone.now()
    Quote.objects.create(id="quo_a", number="Q10001", data={}, created_at=now, updated_at=now)

    with pytest.raises(IntegrityError), transaction.atomic():
        Quote.objects.create(id="quo_b", number="Q10001", data={}, created_at=now, updated_at=now)


def _allocate_in_thread(allocate):
    try:
        return allocate()
    finally:
        # Cada hilo abre su propia conexión; cerrarla evita que el flush del
        # test transaccional quede bloqueado por una conexión colgada.
        connections.close_all()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("allocate", "prefix"), [(next_order_number, "O"), (next_quote_number, "Q")]
)
def test_concurrent_allocations_never_repeat_a_number(allocate, prefix):
    workers = 8
    per_worker = 5

    with ThreadPoolExecutor(max_workers=workers) as pool:
        numbers = list(
            pool.map(lambda _: _allocate_in_thread(allocate), range(workers * per_worker))
        )

    assert len(set(numbers)) == workers * per_worker
    assert sorted(int(n.removeprefix(prefix)) for n in numbers) == list(
        range(10001, 10001 + workers * per_worker)
    )
