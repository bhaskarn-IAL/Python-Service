#!/usr/bin/env bash
# Install data-processing as a systemd service. Run as root.
set -euo pipefail

SERVICE_NAME=${SERVICE_NAME:-data-processing}
APP_DIR=${APP_DIR:-/opt/${SERVICE_NAME}}
USER_NAME=${USER_NAME:-${SERVICE_NAME}}
LOG_DIR=${LOG_DIR:-/var/log/${SERVICE_NAME}}

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

id -u "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$USER_NAME"
mkdir -p "$APP_DIR" "$LOG_DIR"
chown -R "$USER_NAME:$USER_NAME" "$APP_DIR" "$LOG_DIR"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

sed "s|python main.py|python ${MAIN}|" "$(dirname "$0")/${SERVICE_NAME}.service" > "/etc/systemd/system/${SERVICE_NAME}.service"
chmod 644 "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl --no-pager status "${SERVICE_NAME}"
