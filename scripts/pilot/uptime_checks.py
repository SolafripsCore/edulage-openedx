"""Create/refresh DigitalOcean Uptime checks + alerts for every public EduLage endpoint.

    DIGITALOCEAN_TOKEN=... python3 scripts/pilot/uptime_checks.py [alert@email ...]

Idempotent: existing checks (matched by name) are left in place; each check gets a
"down" alert (2 consecutive failures from 2+ regions, i.e. ~2 minutes) and an SSL-expiry alert
(14 days) e-mailed to the addresses given (default: the DigitalOcean account owner). Note: DigitalOcean
only accepts e-mails belonging to members of the DigitalOcean team; invite others under
Settings -> Team to add them as recipients.
"""
import json
import os
import sys
import urllib.request

API = "https://api.digitalocean.com/v2/uptime/checks"
TOKEN = os.environ["DIGITALOCEAN_TOKEN"]
REGIONS = ["eu_west", "us_east", "se_asia"]

TARGETS = {
    "edulage.org (site)": "https://edulage.org/",
    "learn.edulage.org (LMS)": "https://learn.edulage.org/heartbeat",
    "studio.edulage.org (Studio)": "https://studio.edulage.org/heartbeat",
    "apps.learn.edulage.org (learner apps)": "https://apps.learn.edulage.org/learning/",
    "auth.edulage.org (sign-in)": "https://auth.edulage.org/realms/edulage/.well-known/openid-configuration",
}


def call(method, url, body=None):
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r) if r.status != 204 else {}


EMAILS = sys.argv[1:] or [call("GET", "https://api.digitalocean.com/v2/account")["account"]["email"]]

existing = {c["name"]: c for c in call("GET", API + "?per_page=200")["checks"]}

for name, target in TARGETS.items():
    check = existing.get(name)
    if not check:
        check = call("POST", API, {
            "name": name, "type": "https", "target": target,
            "regions": REGIONS, "enabled": True,
        })["check"]
        print("created", name)
    else:
        print("exists ", name)
    alerts = {a["name"] for a in call("GET", f"{API}/{check['id']}/alerts")["alerts"]}
    for alert in (
        {"name": "down", "type": "down", "threshold": 2, "comparison": "greater_than", "period": "2m",
         "notifications": {"email": EMAILS, "slack": []}},
        {"name": "ssl-expiry", "type": "ssl_expiry", "threshold": 14, "comparison": "less_than", "period": "2m",
         "notifications": {"email": EMAILS, "slack": []}},
    ):
        if alert["name"] not in alerts:
            call("POST", f"{API}/{check['id']}/alerts", alert)
            print("   alert", alert["name"], "->", ", ".join(EMAILS))
