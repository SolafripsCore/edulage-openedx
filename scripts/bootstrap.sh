#!/usr/bin/env bash
# Provision a fresh Ubuntu 24.04 host for Tutor. Run as root.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl ufw fail2ban
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
V=$(curl -s https://api.github.com/repos/overhangio/tutor/releases/latest | grep -m1 tag_name | cut -d'"' -f4)
curl -fsSL "https://github.com/overhangio/tutor/releases/download/$V/tutor-$(uname -s)_$(uname -m)" -o /usr/local/bin/tutor
chmod 0755 /usr/local/bin/tutor
id tutor >/dev/null 2>&1 || useradd -m -s /bin/bash -G docker tutor
echo "Tutor $V installed. Next: su - tutor, then run scripts/deploy.sh"
