"""Windows service setup, called by install_service.cmd and uninstall_service.cmd.

    python service_setup.py check-python <app folder>
    python service_setup.py install      <app folder> <nssm>
    python service_setup.py uninstall    <app folder> <nssm>
    python service_setup.py uninstall    --name <service name> <nssm>

Everything for an install comes from <app folder>\\config\\settings.yaml:
  service.name  -> the Windows service name, so several copies (staging, uat,
                   demo) can be installed side by side, each from its own folder
  logging.path  -> the app's log file; its folder is created, and NSSM's console
                   capture (<service.name>.out.log / .err.log) goes there too

``check-python`` uses only the standard library, so it runs before the venv
exists. ``install`` needs PyYAML, so run it with the app's venv Python.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SERVICES_KEY = r"SYSTEM\CurrentControlSet\Services"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def same_dir(a: str, b: str) -> bool:
    def norm(p: str) -> str:
        return os.path.normcase(os.path.normpath(p)).rstrip("\\")
    return norm(a) == norm(b)


# -- registry (read only) --------------------------------------------------

def service_exists(name: str) -> bool:
    try:
        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{SERVICES_KEY}\{name}").Close()
        return True
    except OSError:
        return False


def app_directory_of(name: str) -> str | None:
    """The folder an NSSM service runs from, or None if it isn't an NSSM service."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, rf"{SERVICES_KEY}\{name}\Parameters"
        ) as key:
            return str(winreg.QueryValueEx(key, "AppDirectory")[0])
    except OSError:
        return None


def services_installed_from(app_dir: str) -> list[str]:
    found = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SERVICES_KEY) as services:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(services, i)
            except OSError:
                break
            i += 1
            directory = app_directory_of(name)
            if directory and same_dir(directory, app_dir):
                found.append(name)
    return found


# -- nssm --------------------------------------------------------------------

def find_nssm(nssm: str) -> str:
    path = nssm if os.path.isfile(nssm) else shutil.which(nssm)
    if not path:
        fail(
            f"NSSM not found ('{nssm}'). Install it with 'winget install NSSM.NSSM' "
            "and open a new Command Prompt, or pass the full path to nssm.exe."
        )
    return path


def run_nssm(nssm: str, *args: str, check: bool = True) -> None:
    result = subprocess.run(
        [nssm, *args],
        stdout=None if check else subprocess.DEVNULL,
        stderr=None if check else subprocess.DEVNULL,
    )
    if check and result.returncode != 0:
        fail(f"'nssm {' '.join(args)}' failed with exit code {result.returncode}.")


# -- commands -----------------------------------------------------------------

def check_python(app_dir: Path) -> None:
    """A compiled package (from build.py) only loads on the Python that built it."""
    build_info = app_dir / "BUILD_INFO.json"
    if not build_info.exists():
        return
    needed = json.loads(build_info.read_text(encoding="utf-8"))["python"]
    found = f"{sys.version_info[0]}.{sys.version_info[1]}"
    if needed != found:
        fail(
            f"This package was built for Python {needed}, but 'python' here is "
            f"{found}. Install Python {needed} first."
        )


def install(app_dir: Path, nssm: str) -> None:
    settings = app_dir / "config" / "settings.yaml"
    if not settings.exists():
        fail(f"No settings file at '{settings}'.")

    sys.path.insert(0, str(app_dir / "deploy"))
    from read_settings import read  # needs PyYAML from the app's venv

    name, log_file = read(str(app_dir), str(settings))
    if not NAME_RE.match(name):
        fail(
            f"service.name '{name}' in '{settings}' must be set and use only "
            "letters, digits, '_', '-' or '.'."
        )
    if not log_file:
        fail(f"logging.path is not set in '{settings}'.")

    nssm = find_nssm(nssm)

    # Never take over a service that belongs to another folder (another
    # instance, or an unrelated Windows service with the same name).
    exists = service_exists(name)
    if exists:
        existing_dir = app_directory_of(name)
        if not existing_dir or not same_dir(existing_dir, str(app_dir)):
            fail(
                f"A service named '{name}' already exists for "
                f"'{existing_dir or 'another program'}'. Give this copy a different "
                f"service.name in '{settings}', or uninstall that service first."
            )

    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    python = app_dir / "venv" / "Scripts" / "python.exe"
    main = app_dir / "main.pyc"  # compiled package
    if not main.exists():
        main = app_dir / "main.py"  # source checkout

    print(f"Installing service '{name}' from '{app_dir}', logging to '{log_file}'")

    if exists:  # reinstall of this same instance
        run_nssm(nssm, "stop", name, check=False)
        run_nssm(nssm, "remove", name, "confirm", check=False)

    run_nssm(nssm, "install", name, str(python), str(main))
    run_nssm(nssm, "set", name, "AppDirectory", str(app_dir))
    run_nssm(nssm, "set", name, "Description",
             f"{name} (data-processing supervisor + units) from {app_dir}")
    # The app writes its own log to logging.path. NSSM's capture of the console
    # (startup errors, crash tracebacks) goes next to it, named after the
    # service so instances sharing a log folder don't collide.
    run_nssm(nssm, "set", name, "AppEnvironmentExtra", "PYTHONUNBUFFERED=1")
    run_nssm(nssm, "set", name, "AppStdout", str(log_dir / f"{name}.out.log"))
    run_nssm(nssm, "set", name, "AppStderr", str(log_dir / f"{name}.err.log"))
    run_nssm(nssm, "set", name, "AppRotateFiles", "1")
    run_nssm(nssm, "set", name, "AppRotateBytes", "5242880")
    run_nssm(nssm, "set", name, "Start", "SERVICE_AUTO_START")
    run_nssm(nssm, "set", name, "AppExit", "Default", "Restart")
    run_nssm(nssm, "set", name, "AppRestartDelay", "5000")
    # Wait up to 30 s after Ctrl+C before force-killing (NSSM default is 1.5 s),
    # so every unit gets to run teardown(). Matches TimeoutStopSec on Linux.
    run_nssm(nssm, "set", name, "AppStopMethodConsole", "30000")

    # Show start/status output; a unit that fails at startup is reported in
    # <service.name>.err.log, not as an install error.
    subprocess.run([nssm, "start", name])
    subprocess.run([nssm, "status", name])


def uninstall(app_dir: Path | None, name: str | None, nssm: str) -> None:
    if not name:
        found = services_installed_from(str(app_dir))
        if not found:
            fail(f"No service is installed from '{app_dir}'.")
        if len(found) > 1:
            fail(
                f"Several services are installed from '{app_dir}': "
                f"{', '.join(found)}. Use: uninstall_service.cmd /name <service name>"
            )
        name = found[0]
    elif not service_exists(name):
        fail(f"No service named '{name}'.")

    nssm = find_nssm(nssm)
    print(f"Removing service '{name}' (files and logs are kept)")
    run_nssm(nssm, "stop", name, check=False)
    run_nssm(nssm, "remove", name, "confirm")


def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[0] == "check-python":
        check_python(Path(argv[1]))
    elif len(argv) == 3 and argv[0] == "install":
        install(Path(argv[1]).resolve(), argv[2])
    elif len(argv) == 4 and argv[0] == "uninstall" and argv[1] == "--name":
        uninstall(None, argv[2], argv[3])
    elif len(argv) == 3 and argv[0] == "uninstall":
        uninstall(Path(argv[1]).resolve(), None, argv[2])
    else:
        fail("bad arguments; see the usage at the top of service_setup.py")


if __name__ == "__main__":
    main(sys.argv[1:])
