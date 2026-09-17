"""Marketplace layer settings; plugs the enrolment-policy and course-metadata hooks into the core."""


def plugin_settings(settings):
    settings.CAMPUS_ENROLMENT_POLICY_PROVIDER = "campus_marketplace.policy.enrolment_policy"
    settings.CAMPUS_COURSE_METADATA_PROVIDER = "campus_marketplace.policy.course_metadata"
    # Paystack (test or live secret; never logged). Empty disables checkout.
    if not hasattr(settings, "MARKETPLACE_PAYSTACK_SECRET_KEY"):
        settings.MARKETPLACE_PAYSTACK_SECRET_KEY = ""
    if not hasattr(settings, "MARKETPLACE_PAYSTACK_PUBLIC_KEY"):
        settings.MARKETPLACE_PAYSTACK_PUBLIC_KEY = ""
    if not hasattr(settings, "MARKETPLACE_BILLING_EMAIL"):
        settings.MARKETPLACE_BILLING_EMAIL = ""
    if not hasattr(settings, "MARKETPLACE_PARTNERS_EMAIL"):
        settings.MARKETPLACE_PARTNERS_EMAIL = ""
    # Institution course admins set enrolment policy/price in Studio → Advanced settings → Other course settings.
    settings.FEATURES["ENABLE_OTHER_COURSE_SETTINGS"] = True
