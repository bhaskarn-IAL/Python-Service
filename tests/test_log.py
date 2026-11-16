from __future__ import annotations

import multiprocessing as mp
import re

import pytest

from core import log

LINE_RE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} (INFO |ERROR) \[(\S+) pid=\d+\] (.*)$"
)


@pytest.fixture(autouse=True)
def _reset_log():
    yield
    log.init(None)


def _write_many(path: str, source: str, count: int) -> None:
    log.init(path, source=source)
    for i in range(count):
        log.info(f"{source} line {i} " + "x" * 200)


def test_info_and_error_lines(tmp_path):
    path = tmp_path / "sub" / "app.txt"  # parent folder is created
    log.init(path, source="ingestion")
    log.info("hello")
    log.error("went wrong")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (LINE_RE.match(line) for line in lines)
    assert first.groups() == ("INFO ", "ingestion", "hello")
    assert second.groups() == ("ERROR", "ingestion", "went wrong")


def test_error_inside_except_adds_traceback(tmp_path):
    path = tmp_path / "app.txt"
    log.init(path)
    try:
        raise ValueError("boom")
    except ValueError:
        log.error("unit crashed")

    text = path.read_text(encoding="utf-8")
    assert "ERROR [supervisor pid=" in text
    assert "unit crashed\nTraceback (most recent call last):" in text
    assert "ValueError: boom" in text


def test_no_path_writes_nothing(tmp_path):
    log.init(None)
    log.info("dropped")
    log.error("dropped")
    assert list(tmp_path.iterdir()) == []


def test_processes_writing_together_never_mix_lines(tmp_path):
    path = tmp_path / "shared.txt"
    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(target=_write_many, args=(str(path), f"unit{n}", 200))
        for n in range(4)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 800
    for line in lines:
        m = LINE_RE.match(line)
        assert m, f"malformed line: {line[:80]!r}"
        assert m.group(3).startswith(m.group(2) + " line ")
