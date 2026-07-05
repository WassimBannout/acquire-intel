"""End-to-end wiring test for ``acquire-intel crawl`` (T0.4).

Runs the CLI in a subprocess (a fresh Twisted reactor per run) and asserts the
no-op crawl completes and emits structured JSON logs carrying ``run_id``. Uses
dummy required env vars — the no-op crawl validates config but never touches the DB.
"""

from __future__ import annotations

import json
import subprocess
import sys

ENV = {
    "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5999/none",
    "FLASK_SECRET_KEY": "test",
    "ADMIN_TOKEN": "test",
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    import os

    return subprocess.run(
        [sys.executable, "-m", "acquire_intel.cli", *args],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **ENV},
    )


def _json_log_lines(stream: str) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = []
    for line in stream.splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return lines


def test_crawl_demo_runs_and_logs_a_run() -> None:
    result = _run("crawl", "demo")
    assert result.returncode == 0, result.stderr

    logs = _json_log_lines(result.stderr)
    events = {log.get("event"): log for log in logs}
    assert "crawl.started" in events
    assert "crawl.finished" in events

    # Every one of our run logs carries the same run_id (structured context).
    run_ids = {log["run_id"] for log in logs if "run_id" in log}
    assert len(run_ids) == 1
    assert events["crawl.finished"]["finish_reason"] == "finished"


def test_crawl_unknown_source_exits_2() -> None:
    result = _run("crawl", "nope")
    assert result.returncode == 2
    events = {log.get("event") for log in _json_log_lines(result.stderr)}
    assert "crawl.unknown_source" in events
