"""`/api/admin/users/` y `/api/admin/users/[id]/`.

Estas views separan 401 (sin sesión) de 403 (sin `users.manage`).
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.admin_services import (
    create_admin_user,
    delete_admin_user,
    list_admin_users,
    update_admin_user,
)
from apps.auth.authentication import AdminSessionAuthentication
from apps.auth.permissions import has_torquetrack_permission, is_active_admin_user


class _AdminUsersManageView(APIView):
    authentication_classes = [AdminSessionAuthentication]

    def _require_admin(self, request):
        """Devuelve `None` si pasa, o el `Response` de error."""
        if not is_active_admin_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)
        if not has_torquetrack_permission(request.user, "users.manage"):
            return Response({"error": "Forbidden"}, status=403)
        return None


class AdminUsersView(_AdminUsersManageView):
    def get(self, request):
        denied = self._require_admin(request)
        if denied is not None:
            return denied
        return Response(list_admin_users())

    def post(self, request):
        denied = self._require_admin(request)
        if denied is not None:
            return denied
        body = request.data if isinstance(request.data, dict) else {}
        result = create_admin_user(body, request.user)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result, status=201)


class AdminUserDetailView(_AdminUsersManageView):
    def put(self, request, user_id):
        denied = self._require_admin(request)
        if denied is not None:
            return denied
        body = request.data if isinstance(request.data, dict) else {}
        result = update_admin_user(user_id, body, request.user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)

    def delete(self, request, user_id):
        denied = self._require_admin(request)
        if denied is not None:
            return denied
        result = delete_admin_user(user_id, request.user.pk, request.user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)
