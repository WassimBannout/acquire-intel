"""``acquire-intel`` command-line entrypoint.

T0.1 provides a runnable stub: ``acquire-intel --help`` and ``--version`` work,
and the ``crawl`` subcommand is registered but not yet wired to the acquisition
engine (that is T0.4). Built on stdlib ``argparse`` to honour the tech-stack
rule "prefer stdlib before adding a package".
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from acquire_intel import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser and its subcommands."""
    parser = argparse.ArgumentParser(
        prog="acquire-intel",
        description=(
            "Resilient, pluggable data-acquisition platform for product & price intelligence."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    crawl = subparsers.add_parser(
        "crawl",
        help="Run an on-demand crawl for a registered source (wired in T0.4).",
    )
    crawl.add_argument("source", help="Registered source id to crawl, e.g. 'demo'.")
    crawl.add_argument(
        "--run-id",
        default=None,
        help="Adopt a pre-opened crawl_runs id (internal: used by the admin/scheduler trigger).",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "crawl":
        # Import lazily so `--help`/`--version` don't pay the Scrapy import cost.
        from acquire_intel.acquisition import run_crawl

        return run_crawl(args.source, args.run_id)

    # argparse rejects unknown commands before we reach here.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
