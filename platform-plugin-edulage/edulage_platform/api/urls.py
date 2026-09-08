from django.urls import path

from .views import AdmissionsView, DashboardCoursesView, ListingsView, RolesView, SupportLearnerView, UserStatusView

urlpatterns = [
    path("v1/admissions/", AdmissionsView.as_view(), name="admissions"),
    path("v1/roles/", RolesView.as_view(), name="roles"),
    path("v1/users/status/", UserStatusView.as_view(), name="user-status"),
    path("v1/support/learners/", SupportLearnerView.as_view(), name="support-learners"),
    path("v1/listings/", ListingsView.as_view(), name="listings"),
    path("v1/dashboard/courses/", DashboardCoursesView.as_view(), name="dashboard-courses"),
]
