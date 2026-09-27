from django.urls import path

from apps.audit.views import AdminActivityView

urlpatterns = [
    path("admin/activity/", AdminActivityView.as_view(), name="admin-activity"),
]
