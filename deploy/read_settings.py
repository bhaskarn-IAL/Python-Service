"""Print the settings the installers need, one per line:

    1. service.name
    2. logging.path as a full path (a relative path is taken from the app
       folder, the same way main.py does it)

A missing value prints an empty line. Used by deploy/windows/install_service.ps1
and deploy/linux/install.sh with the app's own venv Python (it needs PyYAML):

    python read_settings.py <app folder> <settings.yaml>
"""
import os
import sys

import yaml


def main() -> None:
    app_dir, settings = sys.argv[1], sys.argv[2]
    with open(settings, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    name = str((config.get("service") or {}).get("name") or "").strip()
    log_path = str((config.get("logging") or {}).get("path") or "").strip()
    if log_path:
        log_path = os.path.normpath(os.path.join(app_dir, log_path))

    print(name)
    print(log_path)


if __name__ == "__main__":
    main()
