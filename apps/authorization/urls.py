from django.urls import path

from apps.authorization.views import (
    AdminRoleDetailView,
    AdminRolesView,
    AdminUserDetailView,
    AdminUsersView,
)

urlpatterns = [
    path("admin/roles/", AdminRolesView.as_view(), name="admin-roles"),
    path("admin/roles/<slug:slug>/", AdminRoleDetailView.as_view(), name="admin-role-detail"),
    path("admin/users/", AdminUsersView.as_view(), name="admin-users"),
    path("admin/users/<str:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
]
