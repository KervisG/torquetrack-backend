from django.urls import path

from apps.authentication.views import (
    LoginView,
    LogoutView,
    PasswordResetConfirmView,
    PasswordResetView,
    SessionView,
    VerifyEmailResendView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("session/", SessionView.as_view(), name="session"),
    path("password-reset/", PasswordResetView.as_view(), name="password-reset"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("verify-email/resend/", VerifyEmailResendView.as_view(), name="verify-email-resend"),
]
