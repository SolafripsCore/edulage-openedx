from django.urls import path

from .views import AdmissionsView

urlpatterns = [
    path("v1/admissions/", AdmissionsView.as_view(), name="admissions"),
]
