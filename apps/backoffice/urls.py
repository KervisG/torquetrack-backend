from django.urls import path

from apps.backoffice.views import AdminActivityView, AdminDashboardView

urlpatterns = [
    path("admin/dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path("admin/activity/", AdminActivityView.as_view(), name="admin-activity"),
]
