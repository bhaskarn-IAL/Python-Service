#!/usr/bin/env bash
# Install this app as a systemd service. Run as root, using the copy of this
# script inside the app folder:
#   sudo bash /opt/data-processing-uat/deploy/linux/install.sh
#
# The service, its system user and its log folder are named after service.name
# in <app folder>/config/settings.yaml, so several copies (staging, uat, demo)
# can be installed side by side, each from its own folder.
#
# Optional overrides: APP_DIR, USER_NAME, LOG_DIR.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
APP_DIR=${APP_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}
SETTINGS="$APP_DIR/config/settings.yaml"
if [ ! -f "$SETTINGS" ]; then
  echo "No settings file at $SETTINGS" >&2
  exit 1
fi

# A compiled package (from build.py) ships main.pyc and only loads on the Python version that built it.
MAIN=main.py
if [ -f "$APP_DIR/BUILD_INFO.json" ]; then
  MAIN=main.pyc
  NEEDED=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['python'])" "$APP_DIR/BUILD_INFO.json")
  FOUND=$(python3 -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')")
  if [ "$NEEDED" != "$FOUND" ]; then
    echo "This package was built for Python $NEEDED, but python3 here is $FOUND. Install Python $NEEDED first." >&2
    exit 1
  fi
fi

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# The service name comes from settings.yaml (read with the venv's PyYAML).
SERVICE_NAME=$("$APP_DIR/venv/bin/python" -c "import sys, yaml; c = yaml.safe_load(open(sys.argv[1], encoding='utf-8')) or {}; print((c.get('service') or {}).get('name') or '')" "$SETTINGS")
if ! [[ "$SERVICE_NAME" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "service.name '$SERVICE_NAME' in $SETTINGS must be set and use only letters, digits, '_', '-' or '.'." >&2
  exit 1
fi
USER_NAME=${USER_NAME:-$SERVICE_NAME}
LOG_DIR=${LOG_DIR:-/var/log/$SERVICE_NAME}
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

# Never take over a service that belongs to another folder (another instance,
# or an unrelated service with the same name).
if [ -f "$UNIT_FILE" ] && ! grep -qxF "WorkingDirectory=$APP_DIR" "$UNIT_FILE"; then
  OTHER=$(grep '^WorkingDirectory=' "$UNIT_FILE" | cut -d= -f2- || true)
  echo "A service named $SERVICE_NAME already exists for '${OTHER:-another program}'." >&2
  echo "Give this copy a different service.name in $SETTINGS, or remove that service first." >&2
  exit 1
fi

echo "Installing service '$SERVICE_NAME' from $APP_DIR"

id -u "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$USER_NAME"
mkdir -p "$LOG_DIR"
chown -R "$USER_NAME:$USER_NAME" "$APP_DIR" "$LOG_DIR"

sed -e "s|@SERVICE_NAME@|$SERVICE_NAME|g" \
    -e "s|@APP_DIR@|$APP_DIR|g" \
    -e "s|@USER@|$USER_NAME|g" \
    -e "s|@MAIN@|$MAIN|g" \
    "$SCRIPT_DIR/service.template" > "$UNIT_FILE"
chmod 644 "$UNIT_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"   # restart, not just start, so a reinstall picks up changes
systemctl --no-pager status "$SERVICE_NAME"
