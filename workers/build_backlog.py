#!/usr/bin/env python3
"""Assemble the unified backlog and (optionally) publish it.

Thin CLI over core/backlog_engine: loads sheet snapshots via the Spreadsheet
adapter (reusing today's snapshots when present), optionally folds in live
tracker data and a debrief's owed items, then dedups/sorts and writes the
result back to the target spreadsheet.

  python workers/build_backlog.py                         # fetch + build + write
  python workers/build_backlog.py --dry-run               # build, print, don't write
  python workers/build_backlog.py --from-debrief debriefs/2026-07-09.md
  python workers/build_backlog.py --tracker-data /tmp/tracker.json

Env: PM_OS_HOME. Backlog config: config/backlog_sources.yaml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("PM_OS_HOME", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))

from core.runtime import load_config, load_adapter        # noqa: E402
from core.backlog_engine import (                          # noqa: E402
    build_backlog, CANON_FIELDS,
)
from core.classifier import parse_debrief_buckets          # noqa: E402
from adapters.base import Task                             # noqa: E402


def load_backlog_config() -> dict:
    import yaml
    from core.runtime import _expand
    real = ROOT / "config" / "backlog_sources.yaml"
    path = real if real.exists() else ROOT / "config" / "backlog_sources.example.yaml"
    return _expand(yaml.safe_load(path.read_text()) or {})


def load_snapshots(bcfg: dict, main_cfg: dict, today: str, from_debrief: bool) -> dict:
    """Return {source_name: tabs}. Reuse today's snapshot json when present."""
    snap_root = ROOT / "snapshots" / "sheets"
    spreadsheet = None
    out: dict[str, dict] = {}
    for src in bcfg.get("sources", []):
        sid = src.get("id", "")
        name = src.get("name", sid)
        snap = snap_root / sid / f"{today}.json"
        if snap.exists():
            out[name] = json.loads(snap.read_text())
            continue
        if from_debrief:
            print(f"[backlog] {name}: no snapshot {today} (--from-debrief) — degraded")
            out[name] = {}
            continue
        if spreadsheet is None:
            spreadsheet = load_adapter(main_cfg["sources"]["sheets"]["adapter"])
        tabs = spreadsheet.fetch_snapshot(sid).tabs
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(json.dumps(tabs, ensure_ascii=False))
        out[name] = tabs
    return out


def tracker_tasks_from_file(path: str) -> list[Task]:
    data = json.loads(Path(path).read_text())
    tasks: list[Task] = []
    for key, info in data.get("by_key", {}).items():
        tasks.append(Task(key=key, title=info.get("summary", key),
                          status=info.get("status", ""), owner=info.get("assignee", ""),
                          deadline=info.get("deadline", ""), stream=info.get("stream", ""),
                          source="Tracker"))
    for t in data.get("extra_tickets", []):
        tasks.append(Task(key=t["key"], title=t.get("summary", t["key"]),
                          status=t.get("status", ""), owner=t.get("assignee", ""),
                          deadline=t.get("deadline", ""), stream=t.get("stream", ""),
                          source="Tracker"))
    return tasks


def write_output(rows: list[dict], bcfg: dict, main_cfg: dict, dry_run: bool) -> None:
    header = ["id"] + CANON_FIELDS
    body = [[r.get(f, "") for f in header] for r in rows]
    if dry_run:
        print(f"[backlog] dry-run: {len(rows)} rows (not written)")
        return
    target = bcfg.get("target", {})
    sid = target.get("spreadsheet_id", "")
    if not sid or sid.startswith("${"):
        print("[backlog] target spreadsheet_id not configured — printing instead")
        print(f"[backlog] {len(rows)} rows ready")
        return
    spreadsheet = load_adapter(main_cfg["sources"]["sheets"]["adapter"])
    spreadsheet.write_tab(sid, target.get("tabs", {}).get("backlog", "Backlog"), [header] + body)
    print(f"[backlog] wrote {len(body)} rows to {sid}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-debrief")
    ap.add_argument("--tracker-data")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    main_cfg = load_config()
    bcfg = load_backlog_config()
    today = datetime.now().strftime("%Y-%m-%d")

    snapshots = load_snapshots(bcfg, main_cfg, today, bool(args.from_debrief))
    tracker_tasks = tracker_tasks_from_file(args.tracker_data) if args.tracker_data else None

    owed = None
    if args.from_debrief and Path(args.from_debrief).exists():
        buckets = parse_debrief_buckets(Path(args.from_debrief).read_text())
        owed = buckets.get("owed_by_me", [])

    rows, stats = build_backlog(snapshots, bcfg, tracker_tasks=tracker_tasks, owed_bullets=owed)
    print(f"[backlog] {stats['before']} → {stats['after']} rows ({stats['merged']} merged)")
    write_output(rows, bcfg, main_cfg, args.dry_run)
    return 0


if __name__ == "__main__":
    main()
