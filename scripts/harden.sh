#!/usr/bin/env bash
# Baseline host hardening for the pilot droplet (idempotent; run as root once, re-run after changes).
#
#   ADMIN_USER=<name> ADMIN_KEY="ssh-ed25519 AAAA... comment" scripts/harden.sh
#
# - creates a named administrative user (sudo + docker) with the given public key
# - SSH: key-only, no root login, no password auth, limited auth attempts
# - firewall: only 80/443 public; SSH restricted to ADMIN_CIDRS if given (comma-separated), else open
# - fail2ban sshd jail
# Run once per administrator with a different ADMIN_USER/ADMIN_KEY; shared accounts are not allowed.
set -euo pipefail
: "${ADMIN_USER:?name of the administrator, e.g. ada-ops}"
: "${ADMIN_KEY:?public SSH key for the administrator}"

if ! id "$ADMIN_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$ADMIN_USER"
fi
usermod -aG sudo,docker "$ADMIN_USER"
install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
touch "/home/$ADMIN_USER/.ssh/authorized_keys"
grep -qxF "$ADMIN_KEY" "/home/$ADMIN_USER/.ssh/authorized_keys" || echo "$ADMIN_KEY" >> "/home/$ADMIN_USER/.ssh/authorized_keys"
chmod 600 "/home/$ADMIN_USER/.ssh/authorized_keys"
chown "$ADMIN_USER:$ADMIN_USER" "/home/$ADMIN_USER/.ssh/authorized_keys"
echo "$ADMIN_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$ADMIN_USER"
chmod 440 "/etc/sudoers.d/90-$ADMIN_USER"

cat > /etc/ssh/sshd_config.d/00-edulage-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
sshd -t
systemctl reload ssh

apt-get install -y -qq fail2ban ufw >/dev/null
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl enable --now fail2ban
systemctl reload fail2ban

ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
if [ -n "${ADMIN_CIDRS:-}" ]; then
  IFS=, read -ra cidrs <<< "$ADMIN_CIDRS"
  for c in "${cidrs[@]}"; do ufw allow from "$c" to any port 22 proto tcp; done
else
  ufw allow 22/tcp
fi
ufw --force enable
ufw status verbose
echo "hardening applied; administrators: $(ls /home | grep -v '^tutor$' | tr '\n' ' ')"
