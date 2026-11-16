"""Build a deployable package of compiled .pyc code into dist/: python build.py"""
from __future__ import annotations

import compileall
import json
import py_compile
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# Compiled to .pyc; the .py source is left out of the package.
CODE = ["main.py", "api", "core", "units", "shared"]
# Copied as-is.
FILES = ["config", "deploy", "requirements.txt"]


def build() -> Path:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    name = f"{meta['name']}-{meta['version']}-py{python.replace('.', '')}"
    stage = DIST / name

    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    skip = shutil.ignore_patterns("__pycache__", "*.pyc")
    for item in CODE:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, stage / item, ignore=skip)
        else:
            shutil.copy2(src, stage / item)

    # legacy=True puts foo.pyc beside foo.py (not in __pycache__) so it still imports once the source is gone.
    ok = compileall.compile_dir(
        stage,
        ddir=name,  # tracebacks show package paths, not this build machine's
        quiet=1,
        legacy=True,
        optimize=2,  # strips docstrings and asserts
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,  # no timestamps: identical builds
    )
    if not ok:
        raise SystemExit("compilation failed; see errors above")
    for source in stage.rglob("*.py"):
        source.unlink()

    for item in FILES:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, stage / item, ignore=skip)
        else:
            shutil.copy2(src, stage / item)

    # The installers read this to refuse a Python version that can't load the .pyc files.
    (stage / "BUILD_INFO.json").write_text(
        json.dumps(
            {
                "name": meta["name"],
                "version": meta["version"],
                "python": python,
                "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    archive = shutil.make_archive(str(stage), "zip", root_dir=DIST, base_dir=name)
    return Path(archive)


if __name__ == "__main__":
    archive = build()
    print(f"built {archive.relative_to(ROOT)}")
    print(f"needs Python {sys.version_info.major}.{sys.version_info.minor} on the target machine")
