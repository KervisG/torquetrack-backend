from django.urls import path

from apps.audit.admin_views import AdminActivityView

urlpatterns = [
    path("admin/activity/", AdminActivityView.as_view(), name="admin-activity"),
]
