#!/usr/bin/env python3
"""Metrics watch — periodic business-metric digest + freshness watchdog.

Pulls tracked metrics via a MetricsAdapter, builds a short digest, and raises a
team alarm through the notifier when either:
  - a metric crosses its threshold in the bad direction, or
  - a metric's data is stale (no fresh observation within the freshness window)
    — a dashboard that silently stops updating is its own incident.

The alarm goes to the SAME notifier the debriefs use, so a team can point it at
a shared channel. Metric definitions and thresholds live in config; this worker
holds no metric-specific logic.

Env: PM_OS_HOME, PM_OS_METRICS_FRESHNESS_MIN (default 180), NOTIFIER_* vars.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("PM_OS_HOME", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))

from core.runtime import load_config, load_adapter          # noqa: E402


def evaluate(metrics, freshness_min: int, now: datetime) -> tuple[list[str], list[str]]:
    """Return (digest_lines, alarm_lines)."""
    digest: list[str] = []
    alarms: list[str] = []
    for m in metrics:
        val = f"{m.value:g}{(' ' + m.unit) if m.unit else ''}"
        digest.append(f"• {m.name}: {val}")

        if m.threshold is not None:
            breached = (
                (m.direction == "below" and m.value < m.threshold)
                or (m.direction == "above" and m.value > m.threshold)
            )
            if breached:
                alarms.append(
                    f"\U0001F6A8 {m.name} = {val} crossed threshold "
                    f"{m.threshold:g} ({m.direction})"
                )

        if m.observed_at is not None:
            age_min = (now - m.observed_at).total_seconds() / 60
            if age_min > freshness_min:
                alarms.append(
                    f"⚠️ {m.name} data is stale "
                    f"({int(age_min)} min old > {freshness_min} min)"
                )
    return digest, alarms


def main() -> int:
    cfg = load_config()
    spec = cfg.get("sources", {}).get("metrics", {}).get("adapter")
    if not spec:
        print("[metrics_watch] no metrics adapter configured (sources.metrics.adapter) — nothing to do")
        return 0

    freshness_min = int(os.environ.get("PM_OS_METRICS_FRESHNESS_MIN", "180"))
    now = datetime.now(timezone.utc)

    try:
        metrics = load_adapter(spec).fetch_metrics()
    except NotImplementedError:
        print("[metrics_watch] metrics adapter is a stub — implement fetch_metrics")
        return 0
    except Exception as e:
        print(f"[metrics_watch] metrics fetch failed: {e}", file=sys.stderr)
        return 1

    # Normalize observed_at to UTC-aware for comparison.
    for m in metrics:
        if m.observed_at is not None and m.observed_at.tzinfo is None:
            m.observed_at = m.observed_at.replace(tzinfo=timezone.utc)

    digest, alarms = evaluate(metrics, freshness_min, now)
    print(f"[metrics_watch] {len(metrics)} metrics, {len(alarms)} alarm(s)")

    if not alarms:
        return 0

    try:
        notifier = load_adapter(cfg["notifier"]["adapter"])
    except Exception as e:
        print(f"[metrics_watch] notifier load failed: {e}", file=sys.stderr)
        return 1

    body = "\U0001F4CA Metrics watch — action needed\n\n" + "\n".join(alarms)
    if digest:
        body += "\n\nCurrent readings:\n" + "\n".join(digest)
    notifier.send(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
