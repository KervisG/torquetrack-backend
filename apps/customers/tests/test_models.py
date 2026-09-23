"""`Customer` es el perfil comercial. Las credenciales viven solo en `User`;
el vínculo es 1:1 y opcional (los clientes invitados no tienen cuenta).

Los certificados de exención siguen en base64 dentro de `data`.
"""
import json

import pytest
from django.db import IntegrityError, connection, transaction

from apps.customers.models import Customer
from tests.factories import create_customer, create_user


@pytest.mark.django_db
def test_raw_insert_relies_on_database_defaults_for_timestamps_and_tax_status():
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into customers (id, email, data) values (%s, %s, %s)",
            ["cus_raw", "fleet@example.com", json.dumps({"name": "Diesel Fleet LLC"})],
        )

    customer = Customer.objects.get(pk="cus_raw")

    assert customer.tax_status == "NOT SUBMITTED"
    assert customer.created_at is not None
    assert customer.updated_at is not None
    assert customer.data["name"] == "Diesel Fleet LLC"


@pytest.mark.django_db
def test_certificate_blob_round_trips_through_jsonb():
    create_customer(
        "cus_cert",
        email="cert@example.com",
        data={"certificateData": "JVBERi0xLjQK..."},
        tax_status="VERIFIED",
    )

    customer = Customer.objects.get(pk="cus_cert")

    assert customer.tax_status == "VERIFIED"
    assert customer.data["certificateData"] == "JVBERi0xLjQK..."


@pytest.mark.django_db
def test_customer_links_one_to_one_to_a_user():
    user = create_user("U_LINK")
    create_customer("cus_link", email=user.email, user=user)

    assert user.customer.pk == "cus_link"
    with pytest.raises(IntegrityError), transaction.atomic():
        create_customer("cus_link_2", email="x@example.com", user=user)


@pytest.mark.django_db
def test_deleting_the_user_keeps_the_customer_and_its_history():
    user = create_user("U_GONE")
    create_customer("cus_orphan", email=user.email, user=user)

    user.delete()

    assert Customer.objects.get(pk="cus_orphan").user is None


@pytest.mark.django_db
def test_guest_emails_are_unique_but_a_registered_profile_can_share_one():
    create_customer("cus_guest", email="shared@example.com")
    owner = create_user("U_SHARED", email="shared@example.com")
    create_customer("cus_registered", email="shared@example.com", user=owner)

    with pytest.raises(IntegrityError), transaction.atomic():
        create_customer("cus_guest_2", email="shared@example.com")


def test_credential_fields_are_gone():
    field_names = {field.name for field in Customer._meta.get_fields()}

    assert "password_hash" not in field_names
    assert "portal_status" not in field_names
