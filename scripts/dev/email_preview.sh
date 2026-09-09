#!/usr/bin/env bash
# Sync the plugin to the pilot host and render the three EduLage e-mails to ~/elmail for review.
set -euo pipefail
HOST=${HOST:-devin-ops@165.22.82.204}
KEY=${KEY:-~/.ssh/edulage_do}
cd "$(dirname "$0")/../.."
rsync -a --delete --exclude __pycache__ -e "ssh -i $KEY" platform-plugin-edulage/ "$HOST:/tmp/ppe/"
ssh -i "$KEY" "$HOST" '
  sudo rsync -a --delete --exclude __pycache__ /tmp/ppe/ /home/tutor/platform-plugin-edulage/ &&
  sudo chown -R tutor:tutor /home/tutor/platform-plugin-edulage &&
  sudo docker exec tutor_local-lms-1 sh -c "cd /openedx/edx-platform && rm -rf /tmp/elmail &&
    ./manage.py lms edulage_email welcome edulage-admin --out /tmp/elmail 2>&1 | tail -3 &&
    ./manage.py lms edulage_email enrolment edulage-admin course-v1:UNIB+MGT101+2026 --out /tmp/elmail 2>&1 | tail -3 &&
    ./manage.py lms edulage_email certificate edulage-admin course-v1:UNIA+CS101+2026 --out /tmp/elmail 2>&1 | tail -3" &&
  sudo rm -rf /tmp/elmail && sudo docker cp tutor_local-lms-1:/tmp/elmail /tmp/elmail && sudo chown -R $(whoami) /tmp/elmail'
rsync -a --delete -e "ssh -i $KEY" "$HOST:/tmp/elmail/" ~/elmail/
ls ~/elmail
