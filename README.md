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
   reads [`config/settings.yaml`](config/settings.yaml), sets up logging
   (`logs/supervisor.log`), and logs `starting data-processing`.
2. **Find the units.** For every unit marked `enabled: true`,
   [`core/registry.py`](core/registry.py) looks up its Python class. For
   example, `ingestion` maps to `IngestionUnit` in `units/ingestion/unit.py`.
3. **Give each unit its own process.** The supervisor starts every unit as a
   brand-new Python process. Each one has its own memory, its own Python
   interpreter and its own log file (`logs/unit_<name>.log`). On Windows,
   when run from a venv, each shows up in Task Manager as `unit_<name>.exe`.
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

The units never talk to each other. The only thing shared between the
processes is that stop signal.

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
│  • writes logs/supervisor.log                                      │
└──┬─────────────────┬──────────────────┬──────────────────┬─────────┘
   │ starts          │ starts           │ starts           │ starts
   ▼                 ▼                  ▼                  ▼
ingestion        pre_processing      processing        post_processing
own process      own process         own process       own process
unit_ingestion   unit_pre_           unit_processing   unit_post_
.log             processing.log      .log              processing.log
```

Five real operating-system processes, shown in Task Manager or `ps`.

### Components

| File | Runs in | Job |
|---|---|---|
| [`main.py`](main.py) | supervisor | Entry point. Loads config, sets up logging, builds the unit list, starts the supervisor and the API, handles `Ctrl+C`. |
| [`core/supervisor.py`](core/supervisor.py) | supervisor | Starts, watches, restarts and stops the unit processes. Reports their status to the API. |
| [`core/base_unit.py`](core/base_unit.py) | each unit | The `BaseUnit` contract (`setup` / `run` / `teardown`) and `unit_entry`, the first code a unit process runs. |
| [`core/registry.py`](core/registry.py) | both | Maps each unit name to its class. |
| [`core/logging_setup.py`](core/logging_setup.py) | both | Log files, log level, console output on or off. |
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
│   └── logging_setup.py
├── api/
│   └── control.py
├── units/
│   ├── ingestion/unit.py
│   ├── pre_processing/unit.py
│   ├── processing/unit.py
│   └── post_processing/unit.py
├── deploy/
│   ├── windows/                  # install_service.ps1, uninstall_service.ps1, web.config
│   └── linux/                    # install.sh, data-processing.service
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
its own `cfg` block when starting it. It also copies the logging settings
into environment variables, which every new process inherits.

For logging settings, the first of these that is set wins:

1. **Environment variable.** The installers use these to point logs at a
   system folder.
2. **`settings.yaml`.**
3. **Built-in default.**

## Configuration

Everything is in [`config/settings.yaml`](config/settings.yaml):

```yaml
service:
  name: "data-processing"      # shown in the API title and the startup log

logging:
  dir: "logs"                  # relative to the folder you start it from
  level: "INFO"                # DEBUG, INFO, WARNING, ERROR, CRITICAL
  console: true                # also print log lines to the terminal

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

Environment variables that override the `logging` block:

| Variable              | Same as           | Example |
|-----------------------|-------------------|---------|
| `SERVICE_LOG_DIR`     | `logging.dir`     | `C:\ProgramData\data-processing\logs` |
| `SERVICE_LOG_LEVEL`   | `logging.level`   | `DEBUG` |
| `SERVICE_LOG_CONSOLE` | `logging.console` | `0` or `false` turns console output off |

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
- **Easy to see what's going on.** One log file per unit, `/health` and
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
- **Force-killing the supervisor leaves the units running on Windows.**
  This happens with Task Manager "End task" or `Stop-Process -Force`. The
  orphaned units keep writing to and locking their log files until you
  kill them (see [Stopping and cleaning up](#stopping-and-cleaning-up)).
  Stopping it normally with `Ctrl+C` or by stopping the service doesn't
  have this problem.
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
is open. Logs go to `logs\` inside the project folder.

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
out, and restarts it 5 seconds after a crash. It shows up as
`data-processing` in `services.msc`. A small tool called
[NSSM](https://nssm.cc) wraps `python main.py` so Windows can manage it as
a service.

**Before you start**

- Python 3.14 installed, with `python --version` working in a new
  PowerShell window.
- Port 8000 free. Don't also run `python main.py` in a terminal at the same
  time.
- A PowerShell window opened **as Administrator** (right-click, then "Run
  as administrator") for every command below.

**Step 1: Install NSSM**

```powershell
winget install NSSM.NSSM
```

Then close and reopen the admin PowerShell, so `nssm` is found.

**Step 2: Put the app in its permanent folder.** Pick one:

From a compiled package (copy the zip to the server first):

```powershell
Expand-Archive .\data-processing-0.1.0-py314.zip -DestinationPath C:\Services
Rename-Item C:\Services\data-processing-0.1.0-py314 data-processing
```

Or from source:

```powershell
robocopy "E:\Project\Python Service" "C:\Services\data-processing" /E /XD .venv logs dist __pycache__ .git
```

**Step 3: Install the service**

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Services\data-processing\deploy\windows\install_service.ps1" -AppDir "C:\Services\data-processing"
```

The installer checks the Python version (for packages), creates
`C:\Services\data-processing\venv`, installs the requirements, registers
the service, and starts it. It runs `main.pyc` for a package or `main.py`
for source. It also gives the service 30 seconds to shut down cleanly, and
turns console logging off so log lines aren't duplicated.

**Step 4: Check it**

```powershell
Get-Service data-processing
curl.exe http://127.0.0.1:8000/health
```

You should see `Running` and `{"status":"ok","units_alive":4,"units_total":4}`.

**Where things live**

| What | Where |
|---|---|
| App and settings | `C:\Services\data-processing\` |
| Python environment | `C:\Services\data-processing\venv\` |
| Logs | `C:\ProgramData\data-processing\logs\` (`supervisor.log`, `unit_*.log`) |
| Startup errors and crash tracebacks | `C:\ProgramData\data-processing\logs\service.err.log` |

When it runs as a service, the log folder comes from the installer, so
`logging.dir` in `settings.yaml` is ignored. `logging.level` still works.

**Day to day**

```powershell
Restart-Service data-processing
Stop-Service data-processing
Start-Service data-processing
Get-Content C:\ProgramData\data-processing\logs\unit_ingestion.log -Tail 20 -Wait
```

To change settings, edit `C:\Services\data-processing\config\settings.yaml`,
then run `Restart-Service data-processing`.

**Upgrade to a new package version**

```powershell
Stop-Service data-processing
Expand-Archive .\data-processing-0.2.0-py314.zip -DestinationPath C:\Services\_new
robocopy C:\Services\_new\data-processing-0.2.0-py314 C:\Services\data-processing /MIR /XD venv /XF settings.yaml
C:\Services\data-processing\venv\Scripts\pip.exe install -r C:\Services\data-processing\requirements.txt
Start-Service data-processing
Remove-Item -Recurse -Force C:\Services\_new
```

`/MIR` makes the folder match the new version exactly, but `/XD venv`
keeps the installed Python environment and `/XF settings.yaml` keeps your
server's settings. If the new release adds settings, copy them in by hand.
If you're switching from a source install to a package (or back), run the
installer from step 3 again instead, because the file it starts changes
between `main.py` and `main.pyc`.

**Uninstall**

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Services\data-processing\deploy\windows\uninstall_service.ps1"
```

That removes the service but keeps the files and logs. To delete those too:

```powershell
Remove-Item -Recurse -Force C:\Services\data-processing, C:\ProgramData\data-processing
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

The script creates a `data-processing` system user, a venv, and the log
folder `/var/log/data-processing/`. It installs the requirements and
registers and starts the systemd service. Check and manage it with:

```bash
systemctl status data-processing
sudo systemctl restart data-processing
journalctl -u data-processing -f
```

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `address already in use` / error 10048 | Something else is using port 8000, often an earlier run of this service | Stop the other copy (see below) or change `api.port` |
| `bad magic number` | The package was built with a different Python version | Install the matching Python, or rebuild with this machine's Python |
| Service starts, then stops | Startup error | Read `C:\ProgramData\data-processing\logs\service.err.log` |
| `could not create renamed exe` warning | Running from a system-wide Python instead of a venv | Harmless. Use a venv if you want the `unit_<name>.exe` names |
| Can't delete the `logs` folder | Orphaned units still have the log files open | See below |

## Stopping and cleaning up

| How it's running | How to stop it |
|---|---|
| In a terminal | `Ctrl+C` in that terminal |
| Windows Service | `Stop-Service data-processing` |
| Linux service | `sudo systemctl stop data-processing` |

**If something is left behind**, for example after "End task" or a closed
terminal, this finds every supervisor started as `main.py` or `main.pyc`,
then stops its units first and itself second:

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

**Units whose supervisor is already gone** (orphans) aren't found by the
command above. This stops only unit processes whose parent no longer
exists:

```powershell
$running = (Get-Process).Id
Get-CimInstance Win32_Process |
  Where-Object { ($_.Name -like 'unit_*.exe' -or $_.CommandLine -match 'multiprocessing\.spawn') -and $running -notcontains $_.ParentProcessId } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
