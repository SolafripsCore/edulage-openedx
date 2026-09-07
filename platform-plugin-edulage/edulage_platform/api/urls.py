from django.urls import path

from .views import AdmissionsView, RolesView, SupportLearnerView, UserStatusView

urlpatterns = [
    path("v1/admissions/", AdmissionsView.as_view(), name="admissions"),
    path("v1/roles/", RolesView.as_view(), name="roles"),
    path("v1/users/status/", UserStatusView.as_view(), name="user-status"),
    path("v1/support/learners/", SupportLearnerView.as_view(), name="support-learners"),
]
