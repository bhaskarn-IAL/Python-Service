# data-processing

A Python background service that runs several independent workers, called
**units**, side by side. Each unit gets its own process, and the service
keeps them all running. It also has a small HTTP API to check on the units
and start or stop them, plus installers to run it as a Windows Service or a
Linux systemd service. You can ship it as compiled `.pyc` code instead of
source.

- [Quick start](#quick-start-windows)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Control API](#control-api)
- [Adding a unit](#adding-a-unit)
- [Pros](#pros)
- [Cons and limits](#cons-and-limits)
- [Deployment](#deployment)
- [Stopping and cleaning up](#stopping-and-cleaning-up)

## Quick start (Windows)

```powershell
cd "E:\Project\Python Service"
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

In a second PowerShell window:

```powershell
curl.exe http://127.0.0.1:8000/health
```

You should get `{"status":"ok","units_alive":4,"units_total":4}`. Press
`Ctrl+C` in the first window to stop.

## How it works

Here is what happens from start to stop:

1. **Start.** `python main.py` starts one process, the **supervisor**. It
   reads [`config/settings.yaml`](config/settings.yaml), opens the text log
   at `logging.path`, and logs `starting data-processing`.
2. **Find the units.** For every unit marked `enabled: true`,
   [`core/registry.py`](core/registry.py) looks up its Python class. For
   example, `ingestion` maps to `IngestionUnit` in `units/ingestion/unit.py`.
3. **Give each unit its own process.** The supervisor starts every unit as a
   brand-new Python process. Each one has its own memory, its own Python
   interpreter, and writes to the same text log as everything else, with
   its name on each line. On Windows,
   when run from a venv, each shows up in Task Manager as
   `<child_unit_prefix>_<name>.exe`, for example `data_processing_ingestion.exe`.
4. **Each unit runs its loop.** Inside its process a unit runs `setup()`
   once. Then it runs `run()`, a loop that does its work and waits
   `interval_seconds`, over and over until it's told to stop. Last it runs
   `teardown()`, which always runs, even after an error.
5. **The supervisor keeps watch.** Every 5 seconds it checks each unit's
   process. If one has died (crashed, hit an error, or got killed), the
   supervisor starts a fresh one after a growing delay: 2 s, 4 s, 8 s, 16 s,
   32 s, then 60 s for every later restart. The other units carry on
   undisturbed. A unit you stopped on purpose through the API is left alone.
6. **The API answers questions.** Inside the same supervisor process, a
   FastAPI server on `http://127.0.0.1:8000` reports status and can start
   or stop units.
7. **Stop.** `Ctrl+C` (or Windows/systemd stopping the service) makes the
   API server exit. The supervisor then sets each unit's stop signal, so
   each unit finishes its current loop, runs `teardown()` and exits. The
   supervisor waits up to 10 seconds per unit, force-stops any that are
   still running, and exits itself.
8. **If the supervisor is killed instead.** "End task", `taskkill /F`,
   `kill -9` or a crash skip step 7, but the units still don't outlive it
   (see [Units never outlive the supervisor](#units-never-outlive-the-supervisor)).

The units never talk to each other. The only thing shared between the
processes is that stop signal.

### Units never outlive the supervisor

If the supervisor process is force-killed, its units are stopped too, on
Windows and Linux. Two layers in [`core/child_guard.py`](core/child_guard.py)
make sure of it:

| Layer | Where | What happens when the supervisor is killed | `teardown()` runs? |
|---|---|---|---|
| **Job Object** | Windows only, set up by the supervisor | Windows itself kills every unit (and anything a unit started) the moment the supervisor ends | No |
| **Parent watcher** | Every unit, Windows and Linux | A thread in the unit notices the supervisor is gone and sets the stop signal; the unit finishes its loop and runs `teardown()`. If it hasn't exited 10 s later, it is ended | Yes, unless it hangs |

So on Windows units stop immediately, and on Linux they stop cleanly within
10 seconds. This also means a service manager that restarts a killed
supervisor (NSSM, systemd) never ends up running two copies of a unit.

Right now the four units are placeholders that each write a log line on
their own timer:

| Unit              | Every | Logs (placeholder)                            |
|-------------------|-------|-----------------------------------------------|
| `ingestion`       | 3 s   | `ingestion: pulled batch #N from source`      |
| `pre_processing`  | 4 s   | `pre_processing: cleaned+validated cycle #N`  |
| `processing`      | 5 s   | `processing: completed run #N`                |
| `post_processing` | 6 s   | `post_processing: published result #N`        |

## Architecture

### Processes

```
python main.py → supervisor process ─────────────────────────────────┐
│  • reads config/settings.yaml                                      │
│  • watch thread: checks the units every 5 s, restarts dead ones    │
│  • FastAPI control API on 127.0.0.1:8000                           │
│  • opens the text log at logging.path                              │
└──┬─────────────────┬──────────────────┬──────────────────┬─────────┘
   │ starts          │ starts           │ starts           │ starts
   ▼                 ▼                  ▼                  ▼
ingestion        pre_processing      processing        post_processing
own process      own process         own process       own process
   │                 │                  │                  │
   └─────────────────┴───── all append to ─────────────────┘
                     one text log (logging.path)
```

Five real operating-system processes, shown in Task Manager or `ps`.

### Components

| File | Runs in | Job |
|---|---|---|
| [`main.py`](main.py) | supervisor | Entry point. Loads config, sets up logging, builds the unit list, starts the supervisor and the API, handles `Ctrl+C`. |
| [`core/supervisor.py`](core/supervisor.py) | supervisor | Starts, watches, restarts and stops the unit processes. Reports their status to the API. |
| [`core/base_unit.py`](core/base_unit.py) | each unit | The `BaseUnit` contract (`setup` / `run` / `teardown`) and `unit_entry`, the first code a unit process runs. |
| [`core/registry.py`](core/registry.py) | both | Maps each unit name to its class. |
| [`core/child_guard.py`](core/child_guard.py) | both | Stops units if the supervisor is force-killed: a Windows Job Object, plus a parent watcher in each unit. |
| [`core/log.py`](core/log.py) | both | The text log: `log.info(message)` and `log.error(message)`. |
| [`api/control.py`](api/control.py) | supervisor | The HTTP endpoints. |
| `units/<name>/unit.py` | that unit | The unit's actual work. |
| [`config/settings.yaml`](config/settings.yaml) | — | All settings. |
| [`build.py`](build.py) | build machine | Makes the compiled package. |
| [`deploy/`](deploy/) | target machine | Windows and Linux service installers. |

### Project layout

```
data-processing/
├── main.py
├── build.py                      # makes the compiled package in dist/
├── config/
│   └── settings.yaml
├── core/
│   ├── base_unit.py
│   ├── supervisor.py
│   ├── registry.py
│   └── log.py
├── api/
│   └── control.py
├── units/
│   ├── ingestion/unit.py
│   ├── pre_processing/unit.py
│   ├── processing/unit.py
│   └── post_processing/unit.py
├── deploy/
│   ├── read_settings.py          # used by both installers to read settings.yaml
│   ├── windows/                  # install_service.cmd, uninstall_service.cmd, service_setup.py, web.config
│   └── linux/                    # install.sh, service.template
├── shared/                       # reserved for code the units share
├── tests/
├── requirements.txt
├── pyproject.toml                # package name and version
├── logs/                         # created when it runs (git-ignored)
└── dist/                         # created by build.py (git-ignored)
```

### How settings reach each process

The unit processes start fresh, so they can't see anything the supervisor
loaded into memory. So `main.py` reads `settings.yaml` and hands each unit
its own `cfg` block when starting it, along with the log file path.

## Logging

Everything goes to one plain text file, set by `logging.path`. The
supervisor and every unit append to it, and each line says who wrote it:

```
2026-11-16 16:47:24.616 INFO  [supervisor pid=4120] started unit ingestion pid=20060
2026-11-16 16:47:25.690 INFO  [ingestion pid=20060] ingestion: pulled batch #1 from source
2026-11-16 16:47:31.002 ERROR [processing pid=18812] unit crashed
Traceback (most recent call last):
  ...
```

There are two calls, each taking just a message:

```python
from core import log          # in a unit, self.log is the same thing

log.info("pulled batch #3")
log.error("could not reach the source")
```

Called inside an `except` block, `log.error` adds the traceback below the
message. A lock file next to the log (`<log file>.lock`) makes sure lines
from different processes never get mixed up.

The file is never rotated or trimmed, so it grows until you clear it.
Delete or archive it while the service is stopped.

## Configuration

Everything is in [`config/settings.yaml`](config/settings.yaml):

```yaml
service:
  name: "data-processing"      # shown in the API title and the startup log
  child_unit_prefix: "data_processing"  # Windows: units run as <prefix>_<unit>.exe; defaults to "unit"

logging:
  # Full path of the text log. Forward slashes work on Windows too.
  # A relative path is taken from the app folder.
  path: "C:/Services/data-processing/logs/data-processing.txt"

api:
  host: "127.0.0.1"            # 127.0.0.1 = only this machine can connect
  port: 8000
  version: "0.1.0"
  # title: "custom title"      # optional; defaults to "<service.name> control"

units:
  ingestion:
    enabled: true
    cfg:
      interval_seconds: 3.0
  pre_processing:
    enabled: true
    cfg:
      interval_seconds: 4.0
  processing:
    enabled: true
    cfg:
      interval_seconds: 5.0
  post_processing:
    enabled: true
    cfg:
      interval_seconds: 6.0
```

- Turn a unit off: set `enabled: false`.
- Change how often a unit runs: edit `interval_seconds`.
- Changes take effect only after a restart.
- `service.name` is also the name of the installed Windows or Linux
  service. To run staging, UAT and demo on one machine, see
  [Running several instances](#running-several-instances).

## Control API

It runs on `http://127.0.0.1:8000`. Open `http://127.0.0.1:8000/docs` in a
browser for a clickable page with every endpoint.

| Method | Path                  | What it does |
|--------|-----------------------|--------------|
| GET    | `/health`             | `"ok"` if every unit is alive, otherwise `"degraded"`, plus counts |
| GET    | `/units`              | Each unit's process ID, whether it's alive, whether you stopped it (`stopped`), and how many times it restarted |
| POST   | `/units/{name}/start` | Starts a unit that isn't running |
| POST   | `/units/{name}/stop`  | Stops a unit and keeps it stopped until you start it again or the service restarts |
| GET    | `/docs`               | Swagger UI |

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/units
curl.exe -X POST http://127.0.0.1:8000/units/ingestion/stop
curl.exe -X POST http://127.0.0.1:8000/units/ingestion/start
```

Use `curl.exe`, not `curl`. In Windows PowerShell, `curl` is a different
command.

A unit you stop counts as not alive, so `/health` says `"degraded"` until you
start it again. Stopping through the API isn't remembered after a restart.
To keep a unit off for good, set `enabled: false` in `settings.yaml`.

## Adding a unit

1. Create `units/my_unit/__init__.py` (empty) and `units/my_unit/unit.py`:

   ```python
   from core.base_unit import BaseUnit

   class MyUnit(BaseUnit):
       name = "my_unit"

       def setup(self):
           self._interval = float(self.cfg.get("interval_seconds", 5.0))

       def run(self):
           while not self.stop.is_set():
               self.log.info("hello from my_unit")
               if self.stop.wait(self._interval):
                   return
   ```

2. Add one line to `UNIT_PATHS` in [`core/registry.py`](core/registry.py):

   ```python
   "my_unit": "units.my_unit.unit:MyUnit",
   ```

3. Add it to [`config/settings.yaml`](config/settings.yaml):

   ```yaml
   units:
     my_unit:
       enabled: true
       cfg:
         interval_seconds: 5.0
   ```

4. Restart. Nothing else needs to change.

Use `self.stop.wait(seconds)` to pause, not `time.sleep`. It returns right
away when the service is stopping, so shutdown stays fast.

## Pros

- **A crash stays contained.** A unit that crashes or hangs only affects
  its own process. The other units and the API keep running.
- **It heals itself.** Dead units come back on their own, with a growing
  delay so a broken unit can't restart in a tight loop.
- **Real parallel work.** Each unit has its own Python interpreter, so a
  CPU-heavy unit doesn't slow the others down. Threads in a single Python
  process couldn't do that.
- **One thing to run and deploy.** One command, one service, one folder.
  The supervisor manages everything else.
- **Easy to extend.** A new unit is one folder, one registry line and one
  settings entry.
- **Configured, not coded.** Which units run, how often, ports and logging
  all live in `settings.yaml`.
- **Easy to see what's going on.** One text log with the source on every line, `/health` and
  `/units` in the API, and named processes in Task Manager.
- **Same behaviour on Windows and Linux,** with an installer for each.
- **Can ship without source code** as a compiled package.

## Cons and limits

- **One machine only.** There's no clustering and no failover. If the
  machine goes down, everything does. Running two copies would just do
  every job twice.
- **"Alive" doesn't mean "working".** The supervisor only checks that a
  unit's process exists. A unit stuck forever on a frozen network call
  still counts as healthy.
- **Restarts never give up, and the delay never resets.** A permanently
  broken unit restarts every 60 seconds forever. Once a unit has crashed
  six times, every later restart waits 60 seconds, even if it ran fine for
  weeks in between.
- **No built-in way to pass data between stages.** The units are
  independent on purpose. A real pipeline needs somewhere outside them,
  like a database, a folder or blob storage, to hand data from one stage to
  the next.
- **The API has no security.** There's no login and no HTTPS. Anyone who
  can reach port 8000 can stop units. Keep it on `127.0.0.1`, or put a
  proxy with authentication in front.
- **Each unit costs a full Python process.** That's typically tens of MB
  of memory per unit.
- **Starting a unit is slow on Windows,** about 1 to 3 seconds per unit,
  because each new process loads everything from scratch.
- **Settings need a restart.** Editing `settings.yaml` doesn't change a
  service that's already running.
- **Force-killing the supervisor on Windows skips `teardown()`.** The
  units are stopped with it, but Windows kills them outright, so they
  can't clean up. On Linux they get up to 10 seconds to run `teardown()`.
  Stopping it normally with `Ctrl+C` or by stopping the service always
  runs `teardown()`.
- **The log file is never rotated.** It keeps growing until you delete or
  archive it, and there's no log level to turn messages down.
- **`teardown()` is skipped for a unit that has to be force-stopped,**
  meaning one that doesn't exit within 10 seconds at shutdown.
- **The compiled package needs the exact same Python version** (3.14 for
  the current build). It also only hides the code; tools exist that can
  turn `.pyc` back into readable source.

## Deployment

There are four ways to run it, from simplest to most permanent:

| Way | Good for | Keeps running when you log out? |
|---|---|---|
| [1. In a terminal](#1-run-it-in-a-terminal) | development, testing | No |
| [2. Compiled package](#2-build-a-compiled-package) | shipping without source | depends on 3 or 4 |
| [3. Windows Service](#3-install-as-a-windows-service) | Windows servers | Yes, and starts on boot |
| [4. Linux systemd service](#4-install-as-a-linux-service) | Linux servers | Yes, and starts on boot |

### 1. Run it in a terminal

See [Quick start](#quick-start-windows). It runs only while that terminal
is open. The log goes to `logging.path`; only the API server's own startup
lines show in the terminal.

### 2. Build a compiled package

On your development machine:

```powershell
cd "E:\Project\Python Service"
python build.py
```

This creates `dist\data-processing-0.1.0-py314.zip`, named from the name
and `version` in `pyproject.toml` plus the Python version used to build it.
Inside:

```
data-processing-0.1.0-py314\
├── main.pyc
├── api\  core\  units\  shared\     ← compiled .pyc only, no .py source
├── config\settings.yaml             ← still editable on the server
├── deploy\                          ← installers
├── requirements.txt
└── BUILD_INFO.json                  ← name, version, Python version, build time
```

To try it by hand on any machine with the same Python version:

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python main.pyc
```

Good to know:

- **The server needs the same Python version** as the build (3.14 here).
  Any other version fails with "bad magic number". Both installers check
  this before installing anything.
- **Dependencies aren't inside the zip.** FastAPI and the rest install from
  `requirements.txt` on the server, so it needs internet access during
  install.
- **One zip works for Windows and Linux.**
- **For a new release,** bump `version` in `pyproject.toml` and run
  `python build.py` again.

### 3. Install as a Windows Service

**What you get:** Windows starts it on boot, keeps it running after you log
out, and restarts it 5 seconds after a crash. It shows up in
`services.msc` under its `service.name` from `settings.yaml`
(`data-processing` in these examples). A small tool called
[NSSM](https://nssm.cc) wraps `python main.py` so Windows can manage it as
a service.

**Before you start**

Everything below runs in a **Command Prompt** (`cmd.exe`), not PowerShell,
so it works where PowerShell is blocked.

- Python 3.14 installed, with `python --version` working in a new Command
  Prompt.
- Port 8000 free (or whatever `api.port` you set). Don't also run
  `python main.py` in a terminal at the same time.
- A Command Prompt opened **as Administrator** (Start, type `cmd`,
  right-click "Command Prompt", then "Run as administrator") for every
  command below.

**Step 1: Install NSSM**

```bat
winget install NSSM.NSSM
```

Then close and reopen the admin Command Prompt, so `nssm` is found. If
`winget` isn't available, download NSSM from [nssm.cc](https://nssm.cc),
unzip it, and pass the path to `nssm.exe` to the installer in step 3.

**Step 2: Put the app in its permanent folder.** Pick one:

From a compiled package (copy the zip to the server first):

```bat
tar -xf data-processing-0.1.0-py314.zip -C C:\Services
ren C:\Services\data-processing-0.1.0-py314 data-processing
```

Or from source:

```bat
robocopy "E:\Project\Python Service" "C:\Services\data-processing" /E /XD .venv logs dist __pycache__ .git
```

**Step 3: Install the service**

First check `service.name`, `api.port` and `logging.path` in
`C:\Services\data-processing\config\settings.yaml`. Then:

```bat
C:\Services\data-processing\deploy\windows\install_service.cmd "C:\Services\data-processing"
```

Or, without typing anything: open `C:\Services\data-processing\deploy\windows`
in Explorer, right-click `install_service.cmd` and choose **Run as
administrator**. With no folder given, it installs the app folder it sits in.
Either way, the window stays open at the end ("Press any key to close") so
you can read the result.

If `nssm` isn't on the PATH, add its location as a second argument, for
example `... "C:\Services\data-processing" C:\tools\nssm.exe`.

The installer checks the Python version (for packages), creates
`C:\Services\data-processing\venv`, installs the requirements, creates the
log folder from `logging.path`, registers the service under `service.name`,
and starts it. It runs `main.pyc` for a package or `main.py` for source. It
also gives the service 30 seconds to shut down cleanly. If a service with
that name already exists from a different folder, it stops without
touching it. The `.cmd` file only checks the basics and creates the venv;
the rest is done by
[`deploy/windows/service_setup.py`](deploy/windows/service_setup.py).

**Step 4: Check it**

```bat
sc query data-processing
curl.exe http://127.0.0.1:8000/health
```

You should see `STATE : 4 RUNNING` and `{"status":"ok","units_alive":4,"units_total":4}`.

**Where things live**

| What | Where |
|---|---|
| App and settings | `C:\Services\data-processing\` |
| Python environment | `C:\Services\data-processing\venv\` |
| Log | `logging.path` in `settings.yaml` (the installer creates its folder) |
| Startup errors and crash tracebacks | `<service.name>.err.log` in the same folder as the log |

**Day to day**

```bat
net stop data-processing
net start data-processing
sc query data-processing
type C:\Services\data-processing\logs\data-processing.txt
```

To change settings, edit `C:\Services\data-processing\config\settings.yaml`,
then run `net stop data-processing` and `net start data-processing`.

**Upgrade to a new package version**

```bat
net stop data-processing
mkdir C:\Services\_new
tar -xf data-processing-0.2.0-py314.zip -C C:\Services\_new
robocopy C:\Services\_new\data-processing-0.2.0-py314 C:\Services\data-processing /MIR /XD venv logs /XF settings.yaml
C:\Services\data-processing\venv\Scripts\python.exe -m pip install -r C:\Services\data-processing\requirements.txt
net start data-processing
rmdir /s /q C:\Services\_new
```

`/MIR` makes the folder match the new version exactly, but `/XD venv logs`
keeps the installed Python environment and any log folder inside the app
folder, and `/XF settings.yaml` keeps your server's settings. If the new
release adds settings, copy them in by hand. If you're switching from a
source install to a package (or back), run the installer from step 3 again
instead, because the file it starts changes between `main.py` and
`main.pyc`.

**Uninstall**

```bat
C:\Services\data-processing\deploy\windows\uninstall_service.cmd "C:\Services\data-processing"
```

(or right-click `uninstall_service.cmd` > **Run as administrator**). That
removes the service installed from that folder, even if
`service.name` was changed since. To remove one by name instead:
`uninstall_service.cmd /name data-processing`. The files and logs are kept.
To delete those too, remove the app folder and the log folder from
`logging.path` (here, the `logs` folder is inside the app folder):

```bat
rmdir /s /q C:\Services\data-processing
```

**Optional: reach the API from other machines through IIS.** Don't host
the Python app inside IIS, because IIS recycles its processes and would
kill the units. Use IIS only as a reverse proxy: install the URL Rewrite
and Application Request Routing modules, then use
[`deploy/windows/web.config`](deploy/windows/web.config), which forwards
everything to `http://localhost:8000`. Add authentication in IIS, because
the API has none.

### 4. Install as a Linux service

You need Python 3.14 as `python3` (on Debian/Ubuntu also the `python3-venv`
package), and root access.

```bash
sudo mkdir -p /opt/data-processing
unzip data-processing-0.1.0-py314.zip -d /tmp/dp
sudo cp -r /tmp/dp/data-processing-0.1.0-py314/. /opt/data-processing/
sudo bash /opt/data-processing/deploy/linux/install.sh
```

For a source install, copy the project folder to `/opt/data-processing`
instead of unzipping.

The script works on the folder it sits in and reads that folder's
`config/settings.yaml`:

- `service.name` names the systemd service and its system user.
- `logging.path` is the log file. The script creates its folder if needed
  and makes the file writable by the service user, for example
  `/var/log/data-processing/data-processing.txt`.

It installs the requirements, writes
`/etc/systemd/system/<service.name>.service` from
[`deploy/linux/service.template`](deploy/linux/service.template), and
(re)starts the service. If a service with that name already exists from a
different folder, it stops without touching it. Keep `service.name`
lowercase (letters, digits, `-`, `_`), because it is also the system user's
name. Check and manage it with:

```bash
systemctl status data-processing
sudo systemctl restart data-processing
journalctl -u data-processing -f
```

To remove it:

```bash
sudo systemctl disable --now data-processing
sudo rm /etc/systemd/system/data-processing.service
sudo systemctl daemon-reload
```

### Running several instances

You can run staging, UAT and demo side by side on one machine, on Windows or
Linux. Each instance is a separate copy of the app in its own folder, with
its own `config/settings.yaml`, installed with the normal installer. These
settings must be different in each copy:

| Setting | Why | Staging | UAT | Demo |
|---|---|---|---|---|
| `service.name` | Name of the Windows/Linux service | `data-processing-staging` | `data-processing-uat` | `data-processing-demo` |
| `service.child_unit_prefix` | Unit process names in Task Manager | `dp_staging` | `dp_uat` | `dp_demo` |
| `api.port` | Two instances can't share a port | `8001` | `8002` | `8003` |
| `logging.path` | Each instance gets its own log | `.../staging/data-processing.txt` | `.../uat/data-processing.txt` | `.../demo/data-processing.txt` |

For example, on Windows:

```bat
rem one folder per instance, each with its own edited settings.yaml
C:\Services\data-processing-uat\deploy\windows\install_service.cmd "C:\Services\data-processing-uat"
sc query state= all | findstr /i "SERVICE_NAME: data-processing-"
```

and on Linux:

```bash
sudo bash /opt/data-processing-uat/deploy/linux/install.sh
systemctl list-units 'data-processing-*'
```

If you forget to change `service.name` in a copy, the installer stops with
"a service named ... already exists" instead of replacing the other
instance.

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `address already in use` / error 10048 | Something else is using port 8000, often an earlier run of this service | Stop the other copy (see below) or change `api.port` |
| `bad magic number` | The package was built with a different Python version | Install the matching Python, or rebuild with this machine's Python |
| Service starts, then stops | Startup error | Windows: read `<service.name>.err.log` next to the log file. Linux: `journalctl -u <service.name>` |
| Installer says `logging.path is not set` | No `logging.path` in that copy's `settings.yaml` | Add it, then run the installer again |
| Installer says a service with that name already exists | Another instance already uses this `service.name` | Give this copy its own `service.name` in its `settings.yaml` |
| `logging.path is not set` on startup | No `logging.path` in `settings.yaml` | Add it (see [Configuration](#configuration)) |
| `log write failed` in the console or `<service.name>.err.log` | The log folder isn't writable, or the file is locked by another program | Fix the folder's permissions or `logging.path` |
| `could not create renamed exe` error in the log | Running from a system-wide Python instead of a venv | Harmless. Use a venv if you want the `<child_unit_prefix>_<name>.exe` names |
| `could not tie pid=... to the supervisor's lifetime` in the log | Windows refused to add a unit to the supervisor's job | The unit's parent watcher still stops it if the supervisor dies; nothing to do unless it repeats |
| `supervisor process is gone; stopping this unit` in the log | The supervisor was force-killed or crashed | Expected; the unit stopped itself. Check why the supervisor died |

## Stopping and cleaning up

| How it's running | How to stop it |
|---|---|
| In a terminal | `Ctrl+C` in that terminal |
| Windows Service | `net stop data-processing` |
| Linux service | `sudo systemctl stop data-processing` |
| Anything else | Kill the supervisor; its units stop with it |

**If a supervisor is still running somewhere**, for example from a terminal
you can't find any more, this finds every supervisor started as `main.py`
or `main.pyc` and stops it, which also stops its units:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match '\bmain\.pyc?\b' } |
  ForEach-Object {
    $sup = $_.ProcessId
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$sup" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Stop-Process -Id $sup -Force
  }
```

That stops every Python program on the machine started as `main.py`, not
only this one, so check first that nothing else of yours runs that way.

**Units whose supervisor is already gone** (orphans) can't happen any more
(see [Units never outlive the supervisor](#units-never-outlive-the-supervisor)).
They can only be left over from a version before that was added. This stops
only unit processes whose parent no longer exists. Set `$prefix` to your
`service.child_unit_prefix`:

```powershell
$prefix = 'data_processing'
$running = (Get-Process).Id
Get-CimInstance Win32_Process |
  Where-Object { ($_.Name -like "${prefix}_*.exe" -or $_.CommandLine -match 'multiprocessing\.spawn') -and $running -notcontains $_.ParentProcessId } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
