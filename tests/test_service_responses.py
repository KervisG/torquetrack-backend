"""`service_response` de `config/responses.py`: el único puente entre los dos
contratos de retorno de los services y el `Response` de DRF. Sin base de datos
ni proveedores.

Se assertea a propósito que un dict de error pierde toda clave que no sea
`error` (un service no filtra datos internos por accidente) y que el `status`
del dict de error nunca llega al body.
"""
from config.responses import service_response


def test_a_tuple_is_returned_as_is():
    response = service_response(({"configured": True}, 202))

    assert response.status_code == 202
    assert response.data == {"configured": True}


def test_an_error_tuple_keeps_its_body_and_status():
    response = service_response(({"error": "Parcel information required"}, 400))

    assert response.status_code == 400
    assert response.data == {"error": "Parcel information required"}


def test_an_error_dict_uses_its_status():
    response = service_response({"error": "Quote not found", "status": 404, "extra": 1})

    assert response.status_code == 404
    assert response.data == {"error": "Quote not found"}


def test_an_error_dict_without_status_is_a_400():
    response = service_response({"error": "Invalid"})

    assert response.status_code == 400
    assert response.data == {"error": "Invalid"}


def test_an_ok_dict_is_a_200_by_default():
    response = service_response({"ok": True, "status": "ACTIVE"})

    assert response.status_code == 200
    # Sin `error`, `status` es un dato del recurso y se conserva.
    assert response.data == {"ok": True, "status": "ACTIVE"}


def test_an_ok_dict_can_declare_its_success_status():
    response = service_response({"ok": True}, success_status=201)

    assert response.status_code == 201
