from django.urls import path

from apps.dashboard.views import AdminDashboardAnalyticsView, AdminDashboardView

urlpatterns = [
    path("admin/dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path(
        "admin/dashboard/analytics/",
        AdminDashboardAnalyticsView.as_view(),
        name="admin-dashboard-analytics",
    ),
]
