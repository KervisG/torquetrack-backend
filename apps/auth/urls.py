from django.urls import path

from apps.auth.admin_views import AdminRolesView, AdminUserDetailView, AdminUsersView
from apps.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetConfirmView,
    PasswordResetView,
    RegisterView,
    SessionView,
    VerifyEmailResendView,
    VerifyEmailView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("session/", SessionView.as_view(), name="session"),
    path("password-reset/", PasswordResetView.as_view(), name="password-reset"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("verify-email/resend/", VerifyEmailResendView.as_view(), name="verify-email-resend"),
    path("admin/roles/", AdminRolesView.as_view(), name="admin-roles"),
    path("admin/users/", AdminUsersView.as_view(), name="admin-users"),
    path("admin/users/<str:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
]
