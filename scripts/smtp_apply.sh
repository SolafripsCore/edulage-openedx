#!/usr/bin/env bash
# Point outgoing platform mail at Resend's SMTP relay and re-render the LMS/CMS config.
# Run as the `tutor` user on the host. The SMTP password is a Resend *send-only* API key
# scoped to edulage.org; it lives only in ~/.local/share/tutor/config.yml (never in this repo).
# Port 2587 (STARTTLS) because DigitalOcean blocks outbound 25/465/587 on droplets.
#
#   RESEND_SMTP_KEY=re_... scripts/smtp_apply.sh
set -euo pipefail
: "${RESEND_SMTP_KEY:?set RESEND_SMTP_KEY to a Resend sending-access API key}"
source "$HOME/venv/bin/activate"
tutor config save \
  --set RUN_SMTP=false \
  --set SMTP_HOST=smtp.resend.com \
  --set SMTP_PORT=2587 \
  --set SMTP_USE_TLS=true \
  --set SMTP_USE_SSL=false \
  --set SMTP_USERNAME=resend \
  --set "SMTP_PASSWORD=$RESEND_SMTP_KEY" \
  --set CONTACT_EMAIL=support@edulage.org
tutor local stop smtp 2>/dev/null || true
tutor local start -d lms cms lms-worker cms-worker
for k in SMTP_HOST SMTP_PORT SMTP_USE_TLS SMTP_USERNAME RUN_SMTP CONTACT_EMAIL; do
  echo "$k=$(tutor config printvalue "$k")"
done
