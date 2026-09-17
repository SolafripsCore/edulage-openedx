"""
python-social-auth pipeline steps for the control-plane IdP backend.

``link_verified_account`` runs before Open edX's ``associate_by_email_if_oauth`` and decides
whether an existing LMS account may be linked to the control-plane identity:

* only when the IdP asserts ``email_verified=true`` (issuer is already validated by the OIDC
  backend against the configured ``OIDC_ENDPOINT``);
* by case-normalised e-mail, only if exactly one active account matches;
* never if that account is already linked to a different control-plane identity;
* every decision (link / refusal) is written to ``IdentityAudit``.

Unverified or ambiguous matches are refused rather than silently creating a duplicate or linking
the wrong account; recovery is manual via Django admin. A refusal returns a redirect to the
branded ``/campus/account/link-refused/`` page instead of raising: the LMS runs views in a
transaction (``ATOMIC_REQUESTS``), so raising would roll the audit row back.

``refuse_suspended_identity`` runs first and sends identities the IdP reports as not ``active``
to ``/campus/account/suspended/`` (a first line of defence; suspension of signed-in users is
pushed through the status API and enforced by ``AccountStatusMiddleware``).

``create_provisioned_account`` (``CAMPUS_JIT_ACCOUNTS``) runs before Open edX's
``ensure_user_information`` and creates the LMS account straight from the IdP claims, so a deployment
can keep ``ALLOW_PUBLIC_ACCOUNT_CREATION`` off (accounts originate from the control plane) without
bouncing first-time learners through the authn MFE registration form.

``sync_campus_identity`` runs after the account exists: it projects the compact
``campus_roles`` claim onto Open edX roles (source ``token``), applies admissions that were
recorded before the learner's first login, and shortens the session for staff.
"""
import re
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
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
    if backend.name != identity.CAMPUS_BACKEND or response is None:
        return {}
    if response.get("campus_status", "active") == "active":
        return {}
    identity.audit("login_refused", sub=uid, email=response.get("email", ""), detail=f"campus_status={response['campus_status']}")
    return HttpResponseRedirect(page_url("suspended"))


def link_verified_account(backend, details, response=None, user=None, uid=None, *args, **kwargs):  # pylint: disable=unused-argument,keyword-arg-before-vararg
    if backend.name != identity.CAMPUS_BACKEND or user is not None or response is None:
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
    return {"user": existing, "is_new": False, "campus_linked": True}


def _unique_username(seed):
    base = re.sub(r"[^\w.+-]", "", (seed or "").split("@")[0])[:24] or "learner"
    username, n = base, 1
    while User.objects.filter(username__iexact=username).exists():
        n += 1
        username = f"{base}{n}"
    return username


def create_provisioned_account(backend, details, response=None, user=None, uid=None, *args, **kwargs):  # pylint: disable=unused-argument,keyword-arg-before-vararg
    if backend.name != identity.CAMPUS_BACKEND or user is not None or response is None:
        return {}
    if not settings.CAMPUS_JIT_ACCOUNTS:
        return {}
    email = (details.get("email") or "").strip().lower()
    if not email or response.get("email_verified") is not True:
        return _refuse(backend, "cannot create account: e-mail missing or not verified by IdP", sub=uid, email=email)
    from common.djangoapps.student.models import UserProfile

    with transaction.atomic():
        new_user = User.objects.create(
            username=_unique_username(details.get("username") or email.split("@")[0]),
            email=email,
            first_name=(details.get("first_name") or "")[:150],
            last_name=(details.get("last_name") or "")[:150],
            is_active=True,
        )
        # Open edX treats an unusable password as a disabled account (``set_logged_in_cookies``),
        # so give the SSO-only account a random one that is never disclosed.
        new_user.set_password(secrets.token_urlsafe(32))
        new_user.save(update_fields=["password"])
        UserProfile.objects.create(user=new_user, name=(details.get("fullname") or new_user.username)[:255])
    return {"user": new_user, "is_new": True}


def sync_campus_identity(backend, user=None, response=None, uid=None, new_association=False, campus_linked=False, *args, **kwargs):  # pylint: disable=unused-argument,keyword-arg-before-vararg
    if backend.name != identity.CAMPUS_BACKEND or user is None or response is None:
        return {}
    claims = response.get("campus_roles", [])
    # Open edX creates the Django user in its registration view, so social-core's ``is_new`` is
    # unreliable here; a fresh link that was not made by ``link_verified_account`` is a new account.
    if new_association and not campus_linked:
        identity.audit("created", user=user, sub=uid, email=user.email, detail=user.username)
        emails.send_welcome(user)
    identity.apply_roles(user, claims, ManagedRole.SOURCE_TOKEN)
    identity.apply_pending_admissions(user, uid)

    request = getattr(backend.strategy, "request", None)
    if request is not None and (user.is_staff or identity.is_staff_claimset(claims) or ManagedRole.objects.filter(user=user).exists()):
        # enforced on every request by AccountStatusMiddleware (login views reset the expiry)
        request.session[STAFF_SESSION_KEY] = True
    return {}
