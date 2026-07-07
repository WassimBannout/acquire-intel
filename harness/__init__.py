"""AcquireIntel adversarial mock harness (ADR-0009).

A local, fully-controlled mock server that simulates anti-bot behaviours on demand so the
resilience layer can be verified deterministically — no live hostile site. See the README.
"""

from __future__ import annotations

from harness.scenarios import HarnessConfig, Scenario
from harness.server import create_harness_app

__all__ = ["HarnessConfig", "Scenario", "create_harness_app"]
