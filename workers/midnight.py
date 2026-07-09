#!/usr/bin/env python3
"""Midnight fallback — runs headless (e.g. 23:00 on working days).

If no debrief exists for today, this pulls the sources via the configured
adapters, runs the six-bucket classification through the LLM adapter, writes
debriefs/<today>.md, and delivers a summary through the notifier. When no LLM
key is present it degrades to a raw source dump (labeled as such) so the
history never has a silent gap.

This is the safety net for days you forget to run /debrief yourself.

Env: PM_OS_HOME (repo root override), plus the PM_OS_LLM_* / NOTIFIER_* vars.
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
from core.classifier import classify_with_llm               # noqa: E402


def _tz(cfg: dict):
    try:
        return ZoneInfo(cfg.get("me", {}).get("timezone", "UTC"))
    except Exception:
        return timezone.utc


def is_working_day(cfg: dict, today: datetime) -> bool:
    wd = [d.lower()[:3] for d in cfg.get("me", {}).get("working_days", [])]
    if wd and today.strftime("%a").lower() not in wd:
        return False
    hfile = cfg.get("me", {}).get("holidays_file")
    if hfile:
        p = ROOT / hfile
        if p.exists():
            try:
                data = json.loads(p.read_text()) if p.suffix == ".json" else {}
            except Exception:
                data = {}
            year = today.strftime("%Y")
            if today.strftime("%Y-%m-%d") in data.get(year, []):
                return False
    return True


def gather_sources_block(cfg: dict, me: str, tz) -> str:
    """Collect sources into a plain-text block for the classifier prompt.

    Every source is best-effort: a failing adapter is recorded, not fatal.
    """
    blocks: list[str] = []
    today = datetime.now(tz).date()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    srcs = cfg.get("sources", {})

    def try_load(key):
        spec = srcs.get(key, {}).get("adapter")
        if not spec:
            return None
        try:
            return load_adapter(spec)
        except Exception as e:
            blocks.append(f"## {key}: unavailable ({e})")
            return None

    tracker = try_load("tracker")
    if tracker:
        try:
            tasks = tracker.fetch_tasks(me, since=day_start,
                                        limit=srcs["tracker"].get("max_tasks", 500))
            blocks.append(f"## Tracker ({len(tasks)} tasks):")
            for t in tasks[:60]:
                blocks.append(f"- [{t.key}] {t.title} | status: {t.status} | owner: {t.owner}")
        except NotImplementedError:
            blocks.append("## Tracker: adapter is a stub (implement fetch_tasks)")
        except Exception as e:
            blocks.append(f"## Tracker: error ({e})")

    cal = try_load("calendar")
    if cal:
        try:
            events = cal.fetch_events(me, today, today)
            blocks.append(f"## Calendar ({len(events)} events):")
            for e in events:
                blocks.append(f"- [{e.id}] {e.title} {e.duration_minutes}min")
        except NotImplementedError:
            blocks.append("## Calendar: adapter is a stub")
        except Exception as e:
            blocks.append(f"## Calendar: error ({e})")

    chat = try_load("chat")
    if chat:
        try:
            msgs = chat.fetch_messages(me, since=day_start,
                                       max_per_chat=srcs["chat"].get("max_messages_per_chat", 50))
            blocks.append(f"## Chat ({len(msgs)} messages):")
            for m in msgs[:80]:
                who = "me" if m.from_me else "them"
                blocks.append(f'- [chat / "{m.chat_name}" / msg {m.time}] ({who}): {m.text[:200]}')
        except NotImplementedError:
            blocks.append("## Chat: adapter is a stub")
        except Exception as e:
            blocks.append(f"## Chat: error ({e})")

    return "\n".join(blocks) if blocks else "(no sources available)"


def raw_debrief(today: str, sources_block: str) -> str:
    return f"""---
date: {today}
mode: headless_raw_no_llm
note: Auto-generated fallback without LLM classification (PM_OS_LLM_API_KEY unset). Run /debrief manually for the full version.
---

## My notes (raw input)
> (none — automatic run)

## Done today
_(not classified — no LLM key)_

## Owed by me — not done today
_(not classified)_

## Waiting on others
_(not classified)_

## Decisions
### Taken today
_(not classified)_

### Open / awaiting
_(not classified)_

## Risks & blockers
_(not classified)_

## Planned (after today)
_(not classified)_

---
## Source detail
{sources_block}
"""


def main() -> int:
    cfg = load_config()
    tz = _tz(cfg)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")

    if not is_working_day(cfg, now):
        print(f"[midnight] {today} is a non-working day, exiting.")
        return 0

    debrief_path = ROOT / "debriefs" / f"{today}.md"
    if debrief_path.exists():
        print(f"[midnight] debrief for {today} already exists, exiting.")
        return 0

    me = cfg.get("me", {}).get("name", "")
    sources_block = gather_sources_block(cfg, me, tz)

    content = None
    try:
        llm = load_adapter(cfg["llm"]["adapter"])
        content = classify_with_llm(
            llm, today, me, cfg.get("signals", {}), sources_block,
        )
    except Exception as e:
        print(f"[midnight] LLM unavailable ({e}); saving raw fallback.")
    if not content:
        content = raw_debrief(today, sources_block)

    debrief_path.parent.mkdir(parents=True, exist_ok=True)
    debrief_path.write_text(content)
    print(f"[midnight] wrote {debrief_path}")

    try:
        from adapters.notifier_telegram import format_debrief_md
        notifier = load_adapter(cfg["notifier"]["adapter"])
        ok = notifier.send(f"\U0001F319 Auto-debrief {today}\n\n" + format_debrief_md(content))
        print(f"[midnight] notifier: {'sent' if ok else 'delivery failed'}")
    except Exception as e:
        print(f"[midnight] notifier error: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
