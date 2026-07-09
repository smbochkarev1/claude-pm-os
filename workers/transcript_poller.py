#!/usr/bin/env python3
"""Transcript poller — runs every ~15 min via launchd/cron.

A retry queue with durability: finished meetings are enqueued, and on each poll
we try to fetch their transcript. When one is ready we extract the follow-up
(LLM) and deliver it (notifier), then mark the meeting done. Meetings whose
transcript never appears within `retry_hours` are dropped.

The queue (cache/transcript_pending.json) means a missed poll — laptop asleep,
ASR slow, a meeting that ran past midnight — never loses a follow-up: it stays
pending and is picked up on a later run.

Adapters used (from config): calendar, transcript, llm, notifier.
Env: PM_OS_HOME plus the usual PM_OS_LLM_* / NOTIFIER_* vars.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("PM_OS_HOME", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))

from core.runtime import load_config, load_adapter          # noqa: E402
from core.followup_engine import extract_followups, render_message  # noqa: E402

SEEN_FILE = ROOT / "cache" / "transcript_poller_seen.txt"
PENDING_FILE = ROOT / "cache" / "transcript_pending.json"

LOOKBACK_DAYS = 2
MIN_MINUTES_AGO = 10          # ASR usually not ready sooner than this
DEFAULT_RETRY_HOURS = 48


def _tz(cfg: dict):
    try:
        return ZoneInfo(cfg.get("me", {}).get("timezone", "UTC"))
    except Exception:
        return timezone.utc


def load_seen() -> set[str]:
    return set(SEEN_FILE.read_text().splitlines()) if SEEN_FILE.exists() else set()


def mark_seen(mid: str) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "a") as f:
        f.write(mid + "\n")


def load_pending() -> dict:
    if not PENDING_FILE.exists():
        return {}
    try:
        return json.loads(PENDING_FILE.read_text()) or {}
    except Exception:
        return {}


def save_pending(pending: dict) -> None:
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))


def enqueue(events, seen: set, pending: dict, now: datetime) -> int:
    added = 0
    for ev in events:
        if ev.is_all_day or ev.kind != "meeting":
            continue
        mid = str(ev.id)
        if not mid or mid in seen or mid in pending:
            continue
        if not ev.end or ev.end > now:
            continue  # not finished yet
        pending[mid] = {
            "title": ev.title,
            "date": (ev.start or now).strftime("%Y-%m-%d"),
            "end": ev.end.isoformat(),
            "attempts": 0,
            "first_seen": now.isoformat(),
        }
        added += 1
    return added


def process(pending: dict, transcript_src, llm, notifier, owner, now: datetime,
            retry_hours: int) -> tuple[int, int, int]:
    sent = dropped = waiting = 0
    for mid, info in list(pending.items()):
        try:
            end = datetime.fromisoformat(info["end"])
        except Exception:
            end = now
        minutes_ago = (now - end).total_seconds() / 60

        if minutes_ago > retry_hours * 60:
            print(f"drop (no transcript after {retry_hours}h): {info.get('title', mid)}")
            del pending[mid]
            mark_seen(mid)
            dropped += 1
            continue
        if minutes_ago < MIN_MINUTES_AGO:
            waiting += 1
            continue

        try:
            transcript = transcript_src.fetch_transcript(mid)
        except NotImplementedError:
            print("transcript adapter is a stub — implement fetch_transcript", file=sys.stderr)
            return sent, dropped, waiting
        except Exception as e:
            print(f"  transcript error for {mid}: {e}", file=sys.stderr)
            transcript = None

        if not transcript:
            info["attempts"] = info.get("attempts", 0) + 1
            waiting += 1
            continue

        try:
            result = extract_followups(llm, transcript, owner_handle=owner)
            if result:
                message = render_message(result, transcript.title, transcript.date)
                if notifier.send(message):
                    mark_seen(mid)
                    del pending[mid]
                    sent += 1
                    print(f"  sent follow-up: {transcript.title}")
                    continue
        except Exception as e:
            print(f"  follow-up error for {mid}: {e}", file=sys.stderr)
        info["attempts"] = info.get("attempts", 0) + 1
        waiting += 1
    return sent, dropped, waiting


def main() -> int:
    cfg = load_config()
    tz = _tz(cfg)
    now = datetime.now(tz)
    me = cfg.get("me", {}).get("name", "")
    owner = f"@{me.lstrip('@')}" if me else None
    retry_hours = cfg.get("sources", {}).get("transcript", {}).get("retry_hours", DEFAULT_RETRY_HOURS)

    try:
        calendar = load_adapter(cfg["sources"]["calendar"]["adapter"])
        transcript_src = load_adapter(cfg["sources"]["transcript"]["adapter"])
        llm = load_adapter(cfg["llm"]["adapter"])
        notifier = load_adapter(cfg["notifier"]["adapter"])
    except Exception as e:
        print(f"[poller] adapter load failed: {e}", file=sys.stderr)
        return 1

    seen = load_seen()
    pending = load_pending()

    try:
        events = calendar.fetch_events(
            me, (now - timedelta(days=LOOKBACK_DAYS)).date(), now.date())
        added = enqueue(events, seen, pending, now)
        if added:
            print(f"enqueued {added} finished meeting(s)")
    except NotImplementedError:
        print("[poller] calendar adapter is a stub — processing existing queue only")
    except Exception as e:
        print(f"[poller] calendar unavailable ({e}) — processing existing queue only")

    sent, dropped, waiting = process(
        pending, transcript_src, llm, notifier, owner, now, retry_hours)
    save_pending(pending)
    print(f"done: {sent} sent, {dropped} dropped, {waiting} waiting (pending={len(pending)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
