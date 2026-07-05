"""Smoke tests for the ``acquire-intel`` CLI stub (T0.1).

These prove the scaffold is runnable; behavioural crawl wiring is tested in T0.4.
"""

from __future__ import annotations

import pytest

from acquire_intel import __version__
from acquire_intel.cli import build_parser, main


def test_no_command_prints_help_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage: acquire-intel" in out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_crawl_stub_is_not_yet_implemented(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["crawl", "demo"])
    assert exc.value.code == 2
    assert "not yet implemented" in capsys.readouterr().err


def test_parser_rejects_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["nope"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
