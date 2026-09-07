"""
EduLage identity provider backend for Open edX third-party auth (python-social-auth).

The provider is registered in Django admin under Third Party Auth → Provider Configuration
(OAuth) with backend name ``edulage``; ``other_settings`` supplies ``OIDC_ENDPOINT`` (the
issuer URL, e.g. ``https://auth.edulage.org/realms/edulage``) and ``logout_url`` so that
Open edX logout also ends the EduLage session (``TPA_AUTOMATIC_LOGOUT_ENABLED``).

Claims expected from the EduLage IdP:
  sub (immutable EduLage user id), email, email_verified, given_name, family_name, preferred_username
  edulage_roles: compact global/institution claims ["learner", "institution_admin:UNIA", "oec_support:UNIA", ...]
                 (per-course-run entitlements are pushed through the roles API, not the token)
  edulage_status: "active" | "suspended"

The issuer is validated by social-core against ``OIDC_ENDPOINT`` (ID token ``iss`` + JWKS).
``edulage_status`` at login is a first line of defence only; suspension of a signed-in user is
pushed by EduLage through ``POST /edulage/api/v1/users/status/`` (see identity.set_account_status).
"""
from social_core.backends.open_id_connect import OpenIdConnectAuth
from social_core.exceptions import AuthForbidden


class EdulageOpenIdConnect(OpenIdConnectAuth):
    name = "edulage"
    DEFAULT_SCOPE = ["openid", "profile", "email"]
    EXTRA_DATA = OpenIdConnectAuth.EXTRA_DATA + ["edulage_roles", "edulage_status"]

    def oidc_endpoint(self):
        return self.setting("OIDC_ENDPOINT")

    def get_user_details(self, response):
        if response.get("edulage_status", "active") != "active":
            raise AuthForbidden(self)
        return super().get_user_details(response)
