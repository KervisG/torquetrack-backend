"""`POST /api/admin/quotes/vin/` y `/tax/` para el editor. El VIN inválido no
llama a NHTSA; el impuesto sin TaxJar usa la tabla de respaldo."""
import pytest

from tests.factories import create_staff_user, session_client


@pytest.mark.django_db
def test_vin_decode_requires_quotes_create_and_rejects_a_short_vin():
    create_staff_user("usr_vin_no", permissions=["quotes.view"])
    denied, _ = session_client("usr_vin_no")
    assert denied.post("/api/admin/quotes/vin/", {"vin": "1"}, format="json").status_code == 403

    create_staff_user("usr_vin", permissions=["quotes.create"])
    client, _ = session_client("usr_vin")
    response = client.post("/api/admin/quotes/vin/", {"vin": "SHORT"}, format="json")

    assert response.status_code == 400
    assert "17" in response.json()["error"]


@pytest.mark.django_db
def test_tax_estimate_uses_the_state_fallback():
    create_staff_user("usr_tax", permissions=["quotes.create"])
    client, _ = session_client("usr_tax")

    response = client.post(
        "/api/admin/quotes/tax/",
        {"subtotal": 100, "coreCharge": 0, "shipping": 0, "state": "FL", "zip": ""},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["tax"] == 6
