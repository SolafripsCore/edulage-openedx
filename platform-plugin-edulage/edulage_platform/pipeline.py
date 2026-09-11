"""
python-social-auth pipeline steps for the EduLage IdP backend.

``link_verified_account`` runs before Open edX's ``associate_by_email_if_oauth`` and decides
whether an existing LMS account may be linked to the EduLage identity:

* only when the IdP asserts ``email_verified=true`` (issuer is already validated by the OIDC
  backend against the configured ``OIDC_ENDPOINT``);
* by case-normalised e-mail, only if exactly one active account matches;
* never if that account is already linked to a different EduLage identity;
* every decision (link / refusal) is written to ``IdentityAudit``.

Unverified or ambiguous matches are refused rather than silently creating a duplicate or linking
the wrong account; recovery is manual via Django admin. A refusal returns a redirect to the
branded ``/edulage/account/link-refused/`` page instead of raising: the LMS runs views in a
transaction (``ATOMIC_REQUESTS``), so raising would roll the audit row back.

``refuse_suspended_identity`` runs first and sends identities the IdP reports as not ``active``
to ``/edulage/account/suspended/`` (a first line of defence; suspension of signed-in users is
pushed through the status API and enforced by ``AccountStatusMiddleware``).

``sync_edulage_identity`` runs after the account exists: it projects the compact
``edulage_roles`` claim onto Open edX roles (source ``token``), applies admissions that were
recorded before the learner's first login, and shortens the session for staff.
"""
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect

from . import emails, identity
from .middleware import STAFF_SESSION_KEY
from .models import ManagedRole
from .status import page_url

User = get_user_model()


def _refuse(backend, reason, **audit_kwargs):
    identity.audit("link_refused", detail=reason, **audit_kwargs)
    return HttpResponseRedirect(page_url("link-refused"))


def refuse_suspended_identity(backend, response=None, uid=None, *args, **kwargs):  # pylint: disable=unused-argument,keyword-arg-before-vararg
    if backend.name != identity.EDULAGE_BACKEND or response is None:
        return {}
    if response.get("edulage_status", "active") == "active":
        return {}
    identity.audit("login_refused", sub=uid, email=response.get("email", ""), detail=f"edulage_status={response['edulage_status']}")
    return HttpResponseRedirect(page_url("suspended"))


def link_verified_account(backend, details, response=None, user=None, uid=None, *args, **kwargs):  # pylint: disable=unused-argument,keyword-arg-before-vararg
    if backend.name != identity.EDULAGE_BACKEND or user is not None or response is None:
        return {}
    email = (details.get("email") or "").strip().lower()
    if not email:
        return {}
    matches = list(User.objects.filter(email__iexact=email))
    if not matches:
        return {}
    if response.get("email_verified") is not True:
        return _refuse(backend, "email not verified by IdP", sub=uid, email=email)
    if len(matches) > 1:
        return _refuse(backend, f"{len(matches)} accounts share this e-mail", sub=uid, email=email)
    existing = matches[0]
    other_sub = identity.sub_for_user(existing)
    if other_sub and other_sub != uid:
        return _refuse(backend, "account linked to another identity", user=existing, sub=uid, email=email)
    if not existing.is_active:
        return _refuse(backend, "account is deactivated", user=existing, sub=uid, email=email)
    if not other_sub:
        identity.audit("linked", user=existing, sub=uid, email=email, detail=f"linked {existing.username} by verified e-mail")
    return {"user": existing, "is_new": False, "edulage_linked": True}


def sync_edulage_identity(backend, user=None, response=None, uid=None, new_association=False, edulage_linked=False, *args, **kwargs):  # pylint: disable=unused-argument,keyword-arg-before-vararg
    if backend.name != identity.EDULAGE_BACKEND or user is None or response is None:
        return {}
    claims = response.get("edulage_roles", [])
    # Open edX creates the Django user in its registration view, so social-core's ``is_new`` is
    # unreliable here; a fresh link that was not made by ``link_verified_account`` is a new account.
    if new_association and not edulage_linked:
        identity.audit("created", user=user, sub=uid, email=user.email, detail=user.username)
        emails.send_welcome(user)
    identity.apply_roles(user, claims, ManagedRole.SOURCE_TOKEN)
    identity.apply_pending_admissions(user, uid)

    request = getattr(backend.strategy, "request", None)
    if request is not None and (user.is_staff or identity.is_staff_claimset(claims) or ManagedRole.objects.filter(user=user).exists()):
        # enforced on every request by AccountStatusMiddleware (login views reset the expiry)
        request.session[STAFF_SESSION_KEY] = True
    return {}
