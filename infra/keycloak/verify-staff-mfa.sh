#!/usr/bin/env bash
# Prove staff MFA enforcement on the `edulage` realm without a browser: sign in as a staff user
# and a learner through the real browser flow (curl) and check where each lands.
#   staff   -> "Mobile Authenticator Setup" page (CONFIGURE_TOTP forced)
#   learner -> redirected straight back to the openedx client with ?code=
# The two test identities are enabled with a random password only for the duration of the check.
# Run on the host next to the Keycloak container.
set -euo pipefail
KCDIR=$(sudo docker inspect edulage-keycloak --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}')
PW=$(sudo grep -E '^KEYCLOAK_ADMIN_PASSWORD=' "$KCDIR/.env" | cut -d= -f2-)
STAFF=${STAFF:-unia.admin}
LEARNER=${LEARNER:-ada.learner}
TMP=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
kc() { sudo docker exec edulage-keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
sudo docker exec -e KP="$PW" edulage-keycloak sh -c \
  '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin --password "$KP"' >/dev/null

uid() { kc get users -r edulage -q username="$1" -q exact=true --fields id --format csv --noquotes; }
S=$(uid "$STAFF"); L=$(uid "$LEARNER")
cleanup() {
  kc update "users/$S" -r edulage -s enabled=false >/dev/null
  kc update "users/$L" -r edulage -s enabled=false >/dev/null
  # invalidate the temporary password
  kc set-password -r edulage --userid "$S" --new-password "$(head -c 24 /dev/urandom | base64)" >/dev/null
  kc set-password -r edulage --userid "$L" --new-password "$(head -c 24 /dev/urandom | base64)" >/dev/null
  kc logout -r edulage --userid "$S" 2>/dev/null || true
  kc logout -r edulage --userid "$L" 2>/dev/null || true
  rm -f /tmp/kcjar.*
}
trap cleanup EXIT
for u in "$S" "$L"; do
  kc update "users/$u" -r edulage -s enabled=true -s 'requiredActions=[]' >/dev/null
  kc set-password -r edulage --userid "$u" --new-password "$TMP"
done

login() {  # $1 username -> prints final landing summary
  local jar; jar=$(mktemp /tmp/kcjar.XXXX)
  local page action
  page=$(curl -s -c "$jar" -b "$jar" \
    "https://auth.edulage.org/realms/edulage/protocol/openid-connect/auth?client_id=openedx&response_type=code&scope=openid&redirect_uri=https%3A%2F%2Flearn.edulage.org%2Fauth%2Fcomplete%2Fedulage%2F&state=mfa-check")
  action=$(printf '%s' "$page" | grep -o 'action="[^"]*"' | head -1 | sed 's/action="//;s/"$//;s/&amp;/\&/g')
  curl -s -o /tmp/kcjar.body -w '%{http_code} %{redirect_url}\n' -c "$jar" -b "$jar" \
    --data-urlencode "username=$1" --data-urlencode "password=$TMP" --data-urlencode "credentialId=" "$action" \
    > /tmp/kcjar.head
  read -r code redir < /tmp/kcjar.head
  if [[ "$code" == 302 && "$redir" == https://learn.edulage.org/auth/complete/edulage/*code=* ]]; then
    echo "$1: signed in without OTP (redirected to LMS with code)"
  elif [[ "$redir" == *required-action*execution=CONFIGURE_TOTP* ]]; then
    echo "$1: forced to set up an authenticator (CONFIGURE_TOTP)"
  else
    echo "$1: unexpected ($code $redir) $(grep -o '<title>[^<]*' /tmp/kcjar.body | head -1)"
  fi
}
login "$STAFF"
login "$LEARNER"
