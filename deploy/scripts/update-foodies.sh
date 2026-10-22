#!/usr/bin/env bash
# =============================================================================
# Foodies Application Deployment & Update Script
# =============================================================================
# Syncs code from the git repository (~/foodies-repo) into production (/opt/foodies),
# preserving the existing virtual environment (/opt/foodies/venv), updating pip
# dependencies, running idempotent database migrations, and restarting the service.
#
# Usage:
#   sudo bash deploy/scripts/update-foodies.sh [SOURCE_DIR]
# Example:
#   sudo bash ~/foodies-repo/deploy/scripts/update-foodies.sh ~/foodies-repo
# =============================================================================

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use: sudo ./update-foodies.sh)." >&2
    exit 1
fi

SRC_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
TARGET_DIR="/opt/foodies"
VENV_DIR="$TARGET_DIR/venv"

echo "===================================================================="
echo " Updating Foodies application from $SRC_DIR to $TARGET_DIR"
echo "===================================================================="

if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: Source directory '$SRC_DIR' does not exist." >&2
    exit 1
fi

# 1. Pull latest changes if source is a git repository
if [ -d "$SRC_DIR/.git" ]; then
    echo "[1/6] Pulling latest changes in $SRC_DIR..."
    git -C "$SRC_DIR" pull --ff-only
fi

# 2. Sync code into /opt/foodies (excluding git metadata, existing venv, env files, logs, dbs)
echo "[2/6] Syncing application code..."
mkdir -p "$TARGET_DIR"

rsync -a --delete \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='logs' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env*' \
    --exclude='*.db' \
    "$SRC_DIR/" "$TARGET_DIR/"

# 3. Fix directory ownership and permissions
echo "[3/6] Setting file ownership to foodies:foodies (mode 750)..."
chown -R foodies:foodies "$TARGET_DIR"
chmod 750 "$TARGET_DIR"

# Ensure venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    chown -R foodies:foodies "$VENV_DIR"
fi

# 4. Install / update pinned Python dependencies
echo "[4/6] Installing / updating Python dependencies..."
"$VENV_DIR/bin/pip" install --no-cache-dir -r "$TARGET_DIR/requirements.txt"

# 5. Run idempotent database migration with environment loaded
echo "[5/6] Running database migrations with /etc/foodies/foodies.env..."
sudo -u foodies bash -c 'set -a; . /etc/foodies/foodies.env; set +a; exec /opt/foodies/venv/bin/python /opt/foodies/manage.py migrate'

# 6. Restart systemd service and verify readiness
echo "[6/6] Checking foodies.service status and readiness probe..."
if systemctl is-active --quiet foodies.service; then
    echo "Restarting foodies.service..."
    systemctl restart foodies.service
    echo "foodies.service restarted successfully."
else
    echo "Starting foodies.service..."
    systemctl enable --now foodies.service || true
fi

# Verify application readiness
echo "Testing application readiness endpoint..."
sleep 1
curl -fsS http://127.0.0.1:8080/ready
echo ""
echo "Readiness probe passed (200 OK)."

echo "===================================================================="
echo " Foodies update completed successfully!"
echo "===================================================================="
