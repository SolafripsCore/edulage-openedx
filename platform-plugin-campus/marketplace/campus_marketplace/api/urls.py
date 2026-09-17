from django.urls import path

from .views import ListingsView, PartnerRequestView, PublicCatalogueView, PublicInstitutionView, PublicRunsView

urlpatterns = [
    path("v1/listings/", ListingsView.as_view(), name="listings"),
    path("v1/partner-requests/", PartnerRequestView.as_view(), name="partner-requests"),
    path("v1/institutions/<str:code>/", PublicInstitutionView.as_view(), name="institution"),
    path("v1/catalogue/", PublicCatalogueView.as_view(), name="catalogue"),
    path("v1/runs/", PublicRunsView.as_view(), name="runs"),
]
