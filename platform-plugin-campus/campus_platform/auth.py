"""
Control-plane identity provider (OIDC) backend for Open edX third-party auth (python-social-auth).

The provider is registered in Django admin under Third Party Auth → Provider Configuration
(OAuth) with backend name ``campus``; ``other_settings`` supplies ``OIDC_ENDPOINT`` (the
issuer URL, e.g. ``https://auth.example.org/realms/campus``) and ``logout_url`` so that
Open edX logout also ends the IdP session (``TPA_AUTOMATIC_LOGOUT_ENABLED``).

Claims expected from the control-plane IdP:
  sub (immutable control-plane user id), email, email_verified, given_name, family_name, preferred_username
  campus_roles: compact global/institution claims ["learner", "institution_admin:UNIA", "platform_support:UNIA", ...]
                 (per-course-run entitlements are pushed through the roles API, not the token)
  campus_status: "active" | "suspended"

The issuer is validated by social-core against ``OIDC_ENDPOINT`` (ID token ``iss`` + JWKS).
``campus_status`` at login is a first line of defence only (enforced by the
``pipeline.refuse_suspended_identity`` step, which shows the branded suspended page); suspension of
a signed-in user is pushed by the control plane through ``POST /campus/api/v1/users/status/``
(see identity.set_account_status).
"""
from social_core.backends.open_id_connect import OpenIdConnectAuth

# Query flag on ``/auth/login/campus/`` that sends the learner to the IdP's registration form
# (Keycloak ``/protocol/openid-connect/registrations``) instead of its sign-in form. The rest of the
# flow is identical: on return the LMS account is JIT-created (``skip_registration_form``).
REGISTER_PARAM = "campus_register"


class CampusOpenIdConnect(OpenIdConnectAuth):
    name = "campus"
    DEFAULT_SCOPE = ["openid", "profile", "email"]
    EXTRA_DATA = OpenIdConnectAuth.EXTRA_DATA + ["campus_roles", "campus_status"]

    def oidc_endpoint(self):
        return self.setting("OIDC_ENDPOINT")

    def auth_url(self):
        # Only the redirect target changes; authorization_url() stays canonical because it is the
        # key under which the OIDC nonce is stored and later looked up on /auth/complete/.
        url = super().auth_url()
        request = self.strategy.request
        if request is not None and request.GET.get(REGISTER_PARAM) == "1":
            return url.replace("/protocol/openid-connect/auth?", "/protocol/openid-connect/registrations?", 1)
        return url
