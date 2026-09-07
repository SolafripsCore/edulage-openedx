#!/usr/bin/env bash
# Provision a fresh Ubuntu 24.04 host for Tutor. Run as root.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl ufw fail2ban python3-venv python3-yaml rsync
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
id tutor >/dev/null 2>&1 || useradd -m -s /bin/bash -G docker tutor
# pip install (not the single-file binary): Tutor plugins such as Indigo are Python packages.
su - tutor -c 'python3 -m venv ~/venv && ~/venv/bin/pip install -q "tutor[full]==22.0.2"'
grep -q 'venv/bin' /home/tutor/.profile || echo 'export PATH="$HOME/venv/bin:$PATH"' >> /home/tutor/.profile
echo "Tutor installed in /home/tutor/venv. Next: su - tutor, then run scripts/deploy.sh"
