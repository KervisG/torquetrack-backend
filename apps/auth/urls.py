from django.urls import path

from apps.auth.admin_views import AdminUserDetailView, AdminUsersView
from apps.auth.views import AdminLoginView, AdminLogoutView, AdminSessionView

urlpatterns = [
    path("admin/login/", AdminLoginView.as_view(), name="admin-login"),
    path("admin/logout/", AdminLogoutView.as_view(), name="admin-logout"),
    path("admin/session/", AdminSessionView.as_view(), name="admin-session"),
    path("admin/users/", AdminUsersView.as_view(), name="admin-users"),
    path("admin/users/<str:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
]
