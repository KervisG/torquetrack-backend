from django.urls import path

from apps.auth.views import AdminLoginView, AdminLogoutView, AdminSessionView

urlpatterns = [
    path("admin/login/", AdminLoginView.as_view(), name="admin-login"),
    path("admin/logout/", AdminLogoutView.as_view(), name="admin-logout"),
    path("admin/session/", AdminSessionView.as_view(), name="admin-session"),
]
