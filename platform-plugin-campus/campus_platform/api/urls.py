from django.urls import path

from .views import (
    AdmissionsView, DashboardApplicationsView, DashboardCoursesView, EventReplayView, EventsView, InstitutionsView, MeView,
    PublicCredentialView,
    RolesView, SupportLearnerView, TenantHostCheckView, UserStatusView,
)

urlpatterns = [
    path("v1/admissions/", AdmissionsView.as_view(), name="admissions"),
    path("v1/roles/", RolesView.as_view(), name="roles"),
    path("v1/users/status/", UserStatusView.as_view(), name="user-status"),
    path("v1/institutions/", InstitutionsView.as_view(), name="institutions"),
    path("v1/events/", EventsView.as_view(), name="events"),
    path("v1/events/replay/", EventReplayView.as_view(), name="events-replay"),
    path("v1/support/learners/", SupportLearnerView.as_view(), name="support-learners"),
    path("v1/me/", MeView.as_view(), name="me"),
    path("v1/tenant-hosts/check/", TenantHostCheckView.as_view(), name="tenant-host-check"),
    path("v1/credentials/<str:uuid>/", PublicCredentialView.as_view(), name="credential"),
    path("v1/dashboard/courses/", DashboardCoursesView.as_view(), name="dashboard-courses"),
    path("v1/dashboard/applications/", DashboardApplicationsView.as_view(), name="dashboard-applications"),
]
