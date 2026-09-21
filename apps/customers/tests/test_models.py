"""Stage A binding tests for the `customers` table (design decision #3/#9).

Tax-exemption certificates stay base64-encoded inside `data` jsonb (design
decision #9) — these tests prove that blob round-trips through `JSONField`
unchanged, plus the plain relational columns already on the table.
"""
import json

import pytest
from django.db import connection

from apps.customers.models import Customer


def _insert_customer(customer_id, email, tax_status, data):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into customers (id, email, password_hash, data,
                                    portal_status, tax_status)
            values (%s, %s, %s, %s, %s, %s)
            """,
            [customer_id, email, "scrypt$abc$def", json.dumps(data),
             "ACTIVE", tax_status],
        )


@pytest.mark.django_db
def test_reads_customer_with_tax_exemption_certificate_in_jsonb():
    data = {
        "name": "Diesel Fleet LLC",
        "phone": "555-0100",
        "taxExemptCertificateBase64": "JVBERi0xLjQK...",
    }
    _insert_customer("cus_1", "fleet@example.com", "VERIFIED", data)

    customer = Customer.objects.get(pk="cus_1")

    assert customer.email == "fleet@example.com"
    assert customer.tax_status == "VERIFIED"
    assert customer.data["taxExemptCertificateBase64"] == "JVBERi0xLjQK..."
    assert customer.data["name"] == "Diesel Fleet LLC"


@pytest.mark.django_db
def test_reads_customer_not_yet_submitted_tax_status():
    _insert_customer("cus_2", "retail@example.com", "NOT SUBMITTED", {"name": "Retail Buyer"})

    customer = Customer.objects.get(pk="cus_2")

    assert customer.tax_status == "NOT SUBMITTED"
    assert "taxExemptCertificateBase64" not in customer.data
