from django.urls import path

from apps.dashboard.views import AdminDashboardView

urlpatterns = [
    path("admin/dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
]
