#!/usr/bin/env bash
# Store the Paystack keys in Tutor's config (host-only, ~/.local/share/tutor/config.yml) and
# re-render the LMS settings. Run as the `tutor` user. Never commit keys to this repo.
#
#   PAYSTACK_SECRET_KEY=sk_test_... PAYSTACK_PUBLIC_KEY=pk_test_... scripts/paystack_apply.sh
#
# Afterwards set the webhook URL in the Paystack dashboard (Settings → API Keys & Webhooks):
#   https://<LMS_HOST>/edulage/pay/webhook/
set -euo pipefail
: "${PAYSTACK_SECRET_KEY:?set PAYSTACK_SECRET_KEY}"
: "${PAYSTACK_PUBLIC_KEY:?set PAYSTACK_PUBLIC_KEY}"
source "$HOME/venv/bin/activate"
tutor config save \
  --set "EDULAGE_PAYSTACK_SECRET_KEY=$PAYSTACK_SECRET_KEY" \
  --set "EDULAGE_PAYSTACK_PUBLIC_KEY=$PAYSTACK_PUBLIC_KEY"
tutor local restart lms lms-worker
echo "Paystack keys applied (mode: ${PAYSTACK_SECRET_KEY:0:7}...)"
