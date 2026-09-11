from django.urls import path

from .views import AdmissionsView, DashboardApplicationsView, DashboardCoursesView, ListingsView, MeView, PartnerRequestView, PublicCredentialView, PublicInstitutionView, PublicRunsView, RolesView, SupportLearnerView, TenantHostCheckView, UserStatusView

urlpatterns = [
    path("v1/admissions/", AdmissionsView.as_view(), name="admissions"),
    path("v1/roles/", RolesView.as_view(), name="roles"),
    path("v1/users/status/", UserStatusView.as_view(), name="user-status"),
    path("v1/support/learners/", SupportLearnerView.as_view(), name="support-learners"),
    path("v1/listings/", ListingsView.as_view(), name="listings"),
    path("v1/me/", MeView.as_view(), name="me"),
    path("v1/partner-requests/", PartnerRequestView.as_view(), name="partner-requests"),
    path("v1/tenant-hosts/check/", TenantHostCheckView.as_view(), name="tenant-host-check"),
    path("v1/institutions/<str:code>/", PublicInstitutionView.as_view(), name="institution"),
    path("v1/credentials/<str:uuid>/", PublicCredentialView.as_view(), name="credential"),
    path("v1/runs/", PublicRunsView.as_view(), name="runs"),
    path("v1/dashboard/courses/", DashboardCoursesView.as_view(), name="dashboard-courses"),
    path("v1/dashboard/applications/", DashboardApplicationsView.as_view(), name="dashboard-applications"),
]
