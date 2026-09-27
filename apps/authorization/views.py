"""Separan 401 (sin sesión de staff) de 403 (staff sin `users.manage`)."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import has_role_permission, is_staff_user
from apps.authorization.services import (
    delete_admin_user,
    list_admin_roles,
    list_admin_users,
    update_admin_user,
)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _result_response(result: dict) -> Response:
    if "error" in result:
        return Response({"error": result["error"]}, status=result.get("status", 400))
    return Response(result)


class _UsersManageView(APIView):
    def _require_users_manage(self, request):
        """Devuelve `None` si pasa, o el `Response` de error."""
        if not is_staff_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)
        if not has_role_permission(request.user, "users.manage"):
            return Response({"error": "Forbidden"}, status=403)
        return None


class AdminUsersView(_UsersManageView):
    def get(self, request):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return Response(list_admin_users())


class AdminUserDetailView(_UsersManageView):
    def put(self, request, user_id):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return _result_response(update_admin_user(user_id, _body(request), request.user))

    def delete(self, request, user_id):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return _result_response(delete_admin_user(user_id, request.user))


class AdminRolesView(_UsersManageView):
    def get(self, request):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return Response(list_admin_roles())
