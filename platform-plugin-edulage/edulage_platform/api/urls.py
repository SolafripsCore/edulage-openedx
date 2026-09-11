from django.urls import path

from .views import AdmissionsView, DashboardApplicationsView, DashboardCoursesView, ListingsView, MeView, PublicRunsView, RolesView, SupportLearnerView, UserStatusView

urlpatterns = [
    path("v1/admissions/", AdmissionsView.as_view(), name="admissions"),
    path("v1/roles/", RolesView.as_view(), name="roles"),
    path("v1/users/status/", UserStatusView.as_view(), name="user-status"),
    path("v1/support/learners/", SupportLearnerView.as_view(), name="support-learners"),
    path("v1/listings/", ListingsView.as_view(), name="listings"),
    path("v1/me/", MeView.as_view(), name="me"),
    path("v1/runs/", PublicRunsView.as_view(), name="runs"),
    path("v1/dashboard/courses/", DashboardCoursesView.as_view(), name="dashboard-courses"),
    path("v1/dashboard/applications/", DashboardApplicationsView.as_view(), name="dashboard-applications"),
]
