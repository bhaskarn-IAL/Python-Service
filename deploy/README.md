# Deployment

The installed service is named after `service.name` in the copy's
`config/settings.yaml`. Each copy (staging, uat, demo, ...) lives in its own
folder with its own `settings.yaml`, so several can run on one machine. See
"Running several instances" in the main README for which settings must differ.

## Linux (systemd)

```bash
sudo mkdir -p /opt/data-processing-uat
sudo rsync -a ./ /opt/data-processing-uat/
# set service.name, api.port, child_unit_prefix and logging.path in
# /opt/data-processing-uat/config/settings.yaml, then:
sudo bash /opt/data-processing-uat/deploy/linux/install.sh
sudo systemctl status data-processing-uat
```

`install.sh` creates a system user named after the service, creates the
folder of `logging.path` and makes the log file writable by that user, and
writes `/etc/systemd/system/<service.name>.service` from `service.template`.
On Linux, keep `service.name` lowercase (letters, digits, `-`, `_`), because
it is also the system user's name.

## Windows (NSSM)

Install [NSSM](https://nssm.cc/download) first, then from an elevated
PowerShell:

```powershell
# Copy the project to its own install folder first, and edit its settings.yaml.
Copy-Item -Recurse .\* C:\Services\data-processing-uat\
C:\Services\data-processing-uat\deploy\windows\install_service.ps1 -AppDir C:\Services\data-processing-uat -Nssm C:\tools\nssm.exe
```

The service runs `python main.py`, restarts on failure, and gets up to 30 s
to shut down cleanly when stopped. The installer creates the folder of
`logging.path`, and NSSM's console capture (`<service.name>.out.log`,
`<service.name>.err.log`) goes into that same folder.
If you need public HTTP, point IIS at the instance's port using `web.config`
(reverse proxy only; IIS must not host the workers).

To remove it: `uninstall_service.ps1 -AppDir C:\Services\data-processing-uat`.

Both installers refuse to install over a service of the same name that was
installed from a different folder.

## Installing from a compiled package

Build it with `python build.py` (see the main README), copy the zip from
`dist\` to the target machine, and unpack it so that `main.pyc` sits directly
in the install folder. On Windows:

```powershell
Expand-Archive .\data-processing-0.1.0-py314.zip -DestinationPath C:\Services
Rename-Item C:\Services\data-processing-0.1.0-py314 data-processing-uat
```

On Linux, unpack it to `/opt/data-processing-uat` the same way. Then run the
same installer as above.

Both installers notice `BUILD_INFO.json`, run `main.pyc` instead of
`main.py`, and stop before installing anything if the machine's Python
version doesn't match the one the package was built with.
