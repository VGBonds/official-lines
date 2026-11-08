#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server for Official Lines. Run as root:
#   bash setup-server.sh your-domain.example
# Safe to re-run. See docs/deployment.md for the full walkthrough.
set -euo pipefail

DOMAIN="${1:?usage: bash setup-server.sh <domain, or the server IP if you have no domain yet>}"
APP_USER=official-lines
APP_DIR=/home/$APP_USER/official-lines

echo "==> System packages and automatic security updates"
apt-get update
apt-get install -y curl sqlite3 rsync ufw unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https gnupg
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Firewall: SSH, HTTP, HTTPS only"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> SSH: key login only (no passwords), once a key is installed"
if [ -s /root/.ssh/authorized_keys ]; then
  # 00- sorts before the image's own files (e.g. 50-cloud-init.conf); sshd keeps the first value
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
    > /etc/ssh/sshd_config.d/00-key-only.conf
  sshd -t && systemctl reload ssh
else
  echo "    no SSH key in /root/.ssh/authorized_keys: password login left on (see docs/deployment.md)"
fi

echo "==> Caddy web server (serves the site, gets HTTPS certificates automatically)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

echo "==> App user '$APP_USER' (the pipeline does not run as root)"
id -u $APP_USER >/dev/null 2>&1 || useradd --create-home --shell /bin/bash $APP_USER
usermod -aG systemd-journal $APP_USER  # lets it read the pipeline's logs
mkdir -p $APP_DIR/data $APP_DIR/site
if [ -d /root/.ssh ]; then  # let the same SSH key log in as the app user (used by push.sh)
  mkdir -p /home/$APP_USER/.ssh
  cp /root/.ssh/authorized_keys /home/$APP_USER/.ssh/
  chmod 700 /home/$APP_USER/.ssh && chmod 600 /home/$APP_USER/.ssh/authorized_keys
fi
chown -R $APP_USER:$APP_USER /home/$APP_USER
chmod 755 /home/$APP_USER  # Caddy must be able to read the site folder

echo "==> uv (Python package manager) for $APP_USER"
sudo -u $APP_USER bash -c 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "==> Caddy config"
SITE_ADDR="$DOMAIN"
if [[ "$DOMAIN" =~ ^[0-9.]+$ ]]; then SITE_ADDR=":80"; fi  # bare IP: plain HTTP until you have a domain
sed "s/YOUR_DOMAIN/$SITE_ADDR/" "$(dirname "$0")/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

echo "==> systemd timers (pipeline every 3 hours, backup nightly)"
cp "$(dirname "$0")"/official-lines-*.service "$(dirname "$0")"/official-lines-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now official-lines-run.timer official-lines-backup.timer

echo
echo "Done. Next: from your laptop run deploy/push.sh, then create $APP_DIR/.env (docs/deployment.md, step 6)."
