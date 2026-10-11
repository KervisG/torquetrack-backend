"""Columnas del perfil de `Customer`: nombre, empresa, teléfono y dirección
salen del JSON y `data` devuelve la misma forma que consume la API."""
import pytest

from apps.customers.models import Customer

PROFILE = {
    "name": "Ana Pérez",
    "company": "Diesel Works",
    "phone": "941-555-0100",
    "address1": "100 Main St",
    "address2": "Suite 2",
    "city": "Sarasota",
    "state": "FL",
    "zip": "34241",
    "taxCompany": "Diesel Works LLC",
}


@pytest.mark.django_db
def test_profile_fields_are_stored_in_columns():
    Customer.objects.create(id="C1", email="ana@example.com", data=dict(PROFILE))

    customer = Customer.objects.get(pk="C1")

    assert (customer.name, customer.company, customer.phone) == (
        "Ana Pérez",
        "Diesel Works",
        "941-555-0100",
    )
    assert (customer.address1, customer.address2) == ("100 Main St", "Suite 2")
    assert (customer.city, customer.state, customer.zip) == ("Sarasota", "FL", "34241")
    assert customer.details == {"taxCompany": "Diesel Works LLC"}


@pytest.mark.django_db
def test_data_rebuilds_the_api_shape():
    Customer.objects.create(id="C1", data=dict(PROFILE))

    assert Customer.objects.get(pk="C1").data == PROFILE


@pytest.mark.django_db
def test_data_omits_empty_profile_fields():
    Customer.objects.create(id="C1", data={"name": "Ana", "phone": ""})

    assert Customer.objects.get(pk="C1").data == {"name": "Ana"}


@pytest.mark.django_db
def test_patching_data_keeps_the_rest_of_the_profile():
    Customer.objects.create(id="C1", data=dict(PROFILE))
    customer = Customer.objects.get(pk="C1")

    customer.data = {**customer.data, "phone": "941-555-0199"}
    customer.save(update_fields=["data", "updated_at"])

    assert Customer.objects.get(pk="C1").data == {**PROFILE, "phone": "941-555-0199"}


@pytest.mark.django_db
def test_customers_can_be_searched_by_name_in_sql():
    Customer.objects.create(id="C1", data={"name": "Ana Pérez"})
    Customer.objects.create(id="C2", data={"name": "Luis Gómez"})

    assert list(Customer.objects.filter(name__icontains="ana").values_list("pk", flat=True)) == [
        "C1"
    ]
