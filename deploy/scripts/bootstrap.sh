#!/usr/bin/env bash
# =============================================================================
# Foodies AWS Ubuntu 24.04 Production Host Bootstrap Script
# =============================================================================
# Creates the dedicated service user, production directories, virtualenv,
# and configures system group memberships for Nginx and CloudWatch agent.
# Must be executed as root (or with sudo).

set -euo pipefail

echo "===================================================================="
echo " Starting Foodies Production Host Bootstrap on Ubuntu 24.04"
echo "===================================================================="

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use: sudo ./bootstrap.sh)." >&2
    exit 1
fi

# 1. Install prerequisite system packages
echo "[1/7] Installing required OS packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3-pip \
    python3-venv \
    nginx \
    git \
    rsync \
    certbot \
    curl \
    ca-certificates \
    sqlite3

# 2. Configure Swap (2GB) for t3.micro to prevent OOM errors during pip install & gunicorn
echo "[2/7] Checking and configuring swap space..."
if [ ! -f /swapfile ] && [ "$(swapon --show | wc -l)" -le 1 ]; then
    echo "Creating 2GB swapfile at /swapfile..."
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    echo "2GB swapfile activated successfully."
else
    echo "Swap is already configured."
fi

# 3. Create the dedicated 'foodies' service account and group
echo "[3/7] Configuring service account and groups..."
if ! getent group foodies >/dev/null 2>&1; then
    groupadd --system foodies
    echo "Created system group: foodies"
fi

if ! id -u foodies >/dev/null 2>&1; then
    useradd --system --gid foodies --home-dir /opt/foodies --shell /bin/bash foodies
    echo "Created system user: foodies"
fi

# 4. Create production directories with strict mode 750
echo "[4/7] Setting up production directory tree..."
# Application root (/opt/foodies, mode 750)
mkdir -p /opt/foodies
chown -R foodies:foodies /opt/foodies
chmod 750 /opt/foodies

# Database directory outside served root (/var/lib/foodies, mode 750)
mkdir -p /var/lib/foodies
chown -R foodies:foodies /var/lib/foodies
chmod 750 /var/lib/foodies

# Application logs directory (/var/log/foodies, mode 750)
mkdir -p /var/log/foodies
chown -R foodies:foodies /var/log/foodies
chmod 750 /var/log/foodies

# Secret configuration directory (/etc/foodies, mode 750)
mkdir -p /etc/foodies
chown root:foodies /etc/foodies
chmod 750 /etc/foodies

# ACME webroot challenge directory (/var/www/certbot, mode 755)
mkdir -p /var/www/certbot
chmod 755 /var/www/certbot
chown -R www-data:www-data /var/www/certbot

# 5. Configure group permissions for www-data (Nginx) and restart Nginx
echo "[5/7] Adding www-data to foodies group and restarting Nginx..."
if id -u www-data >/dev/null 2>&1; then
    usermod -a -G foodies www-data
    echo "Added www-data to group: foodies"
    # Restart Nginx so running worker processes pick up the new supplementary group
    systemctl restart nginx || true
    echo "Nginx restarted with updated group permissions."
fi

# 6. Configure CloudWatch Agent user (cwagent)
echo "[6/7] Configuring CloudWatch agent user permissions..."
if ! getent group cwagent >/dev/null 2>&1; then
    groupadd --system cwagent || true
fi

if ! id -u cwagent >/dev/null 2>&1; then
    useradd --system --gid cwagent --shell /usr/sbin/nologin cwagent || true
fi

# Add cwagent to foodies and adm groups so it can read application & system/nginx logs
usermod -a -G foodies cwagent || true
usermod -a -G adm cwagent || true
echo "Added cwagent to groups: foodies, adm"

# Restart amazon-cloudwatch-agent if it exists so its daemon inherits new groups
if systemctl list-unit-files amazon-cloudwatch-agent.service >/dev/null 2>&1 || [ -f /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl ]; then
    systemctl restart amazon-cloudwatch-agent || true
    echo "Restarted amazon-cloudwatch-agent with updated group permissions."
fi

# 7. Initialize Python virtual environment in /opt/foodies/venv
echo "[7/7] Initializing Python virtual environment in /opt/foodies/venv..."
if [ ! -d "/opt/foodies/venv" ]; then
    python3 -m venv /opt/foodies/venv
    chown -R foodies:foodies /opt/foodies/venv
    echo "Virtual environment created at /opt/foodies/venv"
fi

echo "===================================================================="
echo " Bootstrap Complete! Next steps:"
echo " 1. Clone repository into ~/foodies-repo (git clone <repo_url> ~/foodies-repo)."
echo " 2. Copy .env.example to /etc/foodies/foodies.env and set chmod 640."
echo " 3. Deploy code with: sudo bash ~/foodies-repo/deploy/scripts/update-foodies.sh ~/foodies-repo"
echo " 4. Run: sudo -u foodies /opt/foodies/venv/bin/python /opt/foodies/manage.py create-admin"
echo " 5. Follow deploy/DEPLOY.md to configure Nginx and SSL."
echo "===================================================================="
