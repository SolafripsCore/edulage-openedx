#!/usr/bin/env bash
# Disable (default) or re-enable every spike test identity in the `edulage` realm (run on the server).
# Part of pre-pilot hardening: test identities must not be able to sign in once real users exist.
#
#   ./kc_disable_test_users.sh            # disable all users listed in realm-edulage.json
#   ./kc_disable_test_users.sh enable     # re-enable them for a test run
#
# Requires infra/keycloak/.env (KEYCLOAK_ADMIN_PASSWORD). Nothing is written to disk.
set -euo pipefail
cd "$(dirname "$0")/../../infra/keycloak"
set -a; . ./.env; set +a
enabled=false; [ "${1:-}" = "enable" ] && enabled=true

kc() { docker exec edulage-keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
docker exec -e KP="$KEYCLOAK_ADMIN_PASSWORD" edulage-keycloak sh -c \
  '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin --password "$KP"' >/dev/null

for u in $(python3 -c 'import json;print(" ".join(x["username"] for x in json.load(open("realm-edulage.json"))["users"]))'); do
  uid=$(kc get users -r edulage -q "username=$u" -q exact=true --fields id --format csv --noquotes)
  [ -n "$uid" ] || continue
  kc update "users/$uid" -r edulage -s "enabled=$enabled"
  echo "$u enabled=$enabled"
done
