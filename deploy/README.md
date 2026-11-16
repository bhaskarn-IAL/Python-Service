# Deployment

Service name: **data-processing**

## Linux (systemd)

```bash
sudo mkdir -p /opt/data-processing
sudo rsync -a ./ /opt/data-processing/
sudo deploy/linux/install.sh
sudo systemctl status data-processing
```

Logs land in `/var/log/data-processing/`. The control API listens on
`127.0.0.1:8000`; put nginx in front if it needs to be public.

## Windows (NSSM)

Install [NSSM](https://nssm.cc/download) first, then from an elevated
PowerShell:

```powershell
# Copy the project to the install directory first.
Copy-Item -Recurse .\* C:\Services\data-processing\
cd C:\Services\data-processing\deploy\windows
.\install_service.ps1 -AppDir C:\Services\data-processing -Nssm C:\tools\nssm.exe
```

The service runs `python main.py`, restarts on failure, gets up to 30 s
to shut down cleanly when stopped, and writes logs to
`C:\ProgramData\data-processing\logs`. Console logging is turned off
(`SERVICE_LOG_CONSOLE=0`), so `service.err.log` holds only uvicorn output
and real crash tracebacks, not copies of every log line. If you need public HTTP, point IIS
at `http://localhost:8000` using `web.config` (reverse proxy only — IIS
must not host the workers).

## Installing from a compiled package

Build it with `python build.py` (see the main README), copy the zip from
`dist\` to the target machine, and unpack it so that `main.pyc` sits directly
in the install folder. On Windows:

```powershell
Expand-Archive .\data-processing-0.1.0-py314.zip -DestinationPath C:\Services
Rename-Item C:\Services\data-processing-0.1.0-py314 data-processing
```

On Linux, unpack it to `/opt/data-processing` the same way. Then run the
same installer as above.

Both installers notice `BUILD_INFO.json`, run `main.pyc` instead of
`main.py`, and stop before installing anything if the machine's Python
version doesn't match the one the package was built with.

## Env vars honored by the service

| Variable            | Default | Purpose                      |
|---------------------|---------|------------------------------|
| `SERVICE_LOG_DIR`   | `logs`  | Where log files are written  |
| `SERVICE_LOG_LEVEL` | `INFO`  | Root log level               |
| `SERVICE_LOG_CONSOLE` | `true` | Also print log lines to the console |
