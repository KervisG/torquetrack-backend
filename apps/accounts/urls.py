from django.urls import path

from apps.accounts.views import AdminUserDetailView, AdminUsersView

urlpatterns = [
    path("admin/users/", AdminUsersView.as_view(), name="admin-users"),
    path("admin/users/<str:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
]
