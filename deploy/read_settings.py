"""Read the settings the installers need from an app copy's settings.yaml.

Run as a script, it prints one value per line (used by deploy/linux/install.sh):

    1. service.name
    2. logging.path as a full path (a relative path is taken from the app
       folder, the same way main.py does it)

A missing value prints an empty line. It needs PyYAML, so run it with the
app's own venv Python:

    python read_settings.py <app folder> <settings.yaml>
"""
import os
import sys

import yaml


def read(app_dir: str, settings: str) -> tuple[str, str]:
    """Return (service.name, full logging.path); missing values are ''."""
    with open(settings, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    name = str((config.get("service") or {}).get("name") or "").strip()
    log_path = str((config.get("logging") or {}).get("path") or "").strip()
    if log_path:
        log_path = os.path.normpath(os.path.join(app_dir, log_path))
    return name, log_path


def main() -> None:
    name, log_path = read(sys.argv[1], sys.argv[2])
    print(name)
    print(log_path)


if __name__ == "__main__":
    main()
