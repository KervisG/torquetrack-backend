"""Separan 401 (sin sesión de staff) de 403 (staff sin `users.manage`)."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import has_role_permission, is_staff_user
from apps.authorization.services import (
    create_admin_role,
    delete_admin_user,
    list_admin_roles,
    list_admin_users,
    update_admin_role,
    update_admin_user,
)
from config.responses import service_response


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


class _UsersManageView(APIView):
    # Abierta a propósito: `_require_users_manage` separa el 401 del 403 para
    # que el SPA distinga sesión vencida de falta de permiso.
    permission_classes = [AllowAny]

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
        return service_response(update_admin_user(user_id, _body(request), request.user))

    def delete(self, request, user_id):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return service_response(delete_admin_user(user_id, request.user))


class AdminRolesView(_UsersManageView):
    def get(self, request):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return Response(list_admin_roles())

    def post(self, request):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return service_response(create_admin_role(_body(request), request.user), success_status=201)


class AdminRoleDetailView(_UsersManageView):
    def put(self, request, slug):
        denied = self._require_users_manage(request)
        if denied is not None:
            return denied
        return service_response(update_admin_role(slug, _body(request), request.user))
