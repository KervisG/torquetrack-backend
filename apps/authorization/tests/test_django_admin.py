"""`/admin/` de Django con el registro de `User` y `Role` de `apps/authorization/admin.py`.

Sin proveedores que mockear. Regla que se assertea a propósito: `/admin/` solo
lo abre un usuario activo con Role de acceso total; un Role sin acceso total
(aunque tenga `users.manage`) o un cliente sin Role van al login.
"""
import pytest

from tests.factories import create_staff_user, create_user, session_client


@pytest.mark.django_db
def test_django_admin_accepts_a_full_access_user():
    create_staff_user("U_ADMIN", full_access=True)
    client, _ = session_client("U_ADMIN")

    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/authentication/user/").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "factory",
    [
        lambda: create_staff_user("U_EMPLOYEE", permissions=["users.manage", "orders.view"]),
        lambda: create_user("U_EMPLOYEE"),
    ],
    ids=["role-without-full-access", "customer"],
)
def test_django_admin_rejects_users_without_full_access(factory):
    factory()
    client, _ = session_client("U_EMPLOYEE")

    response = client.get("/admin/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
