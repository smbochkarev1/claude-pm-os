"""Weekly aggregation engine.

Reads a set of daily debrief markdown files and derives the weekly view without
touching any external source:

  - achievements   union of `done_today`, near-duplicates folded
  - chronic         `owed_by_me` + `waiting_on_others` items repeating on 2+ days
  - decisions       taken (with dates) + still-open (repeating)
  - recurring_risks risks/blockers appearing on 2+ days
  - patterns        person stuck in waiting, item stuck in owed, risk spikes

Pure and deterministic — same inputs give the same weekly digest. The command
layer decides how to render it (markdown file, chat message, notifier).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from core.backlog_engine import fuzzy
from core.classifier import parse_debrief_buckets

FUZZY_THRESHOLD = 0.82


def _similar(a: str, b: str) -> bool:
    return fuzzy(a, b) >= FUZZY_THRESHOLD


def _dedup_union(items: Iterable[str]) -> list[str]:
    kept: list[str] = []
    for it in items:
        if not any(_similar(it, k) for k in kept):
            kept.append(it)
    return kept


def _repeating(day_items: dict[str, list[str]], min_days: int = 2) -> list[dict]:
    """Group near-duplicate bullets across days; keep those on >= min_days."""
    groups: list[dict] = []  # {"text": str, "dates": [..]}
    for date, items in sorted(day_items.items()):
        for it in items:
            hit = next((g for g in groups if _similar(it, g["text"])), None)
            if hit:
                if date not in hit["dates"]:
                    hit["dates"].append(date)
            else:
                groups.append({"text": it, "dates": [date]})
    return [g for g in groups if len(g["dates"]) >= min_days]


def aggregate_week(debriefs: dict[str, str]) -> dict:
    """`debriefs` maps date (YYYY-MM-DD) -> debrief markdown text."""
    per_day = {d: parse_debrief_buckets(t) for d, t in debriefs.items()}

    done_all: list[str] = []
    owed_by_day: dict[str, list[str]] = {}
    waiting_by_day: dict[str, list[str]] = {}
    risks_by_day: dict[str, list[str]] = {}
    decisions_by_day: dict[str, list[str]] = {}

    for date, b in sorted(per_day.items()):
        done_all.extend(b.get("done_today", []))
        owed_by_day[date] = b.get("owed_by_me", [])
        waiting_by_day[date] = b.get("waiting_on_others", [])
        risks_by_day[date] = b.get("risks_blockers", [])
        decisions_by_day[date] = b.get("decisions", [])

    chronic_owed = _repeating(owed_by_day)
    chronic_waiting = _repeating(waiting_by_day)

    patterns: list[str] = []
    for g in chronic_owed:
        if len(g["dates"]) >= 3:
            patterns.append(f"Owed {len(g['dates'])} days — needs prioritization: {g['text'][:80]}")
    for g in chronic_waiting:
        if len(g["dates"]) >= 3:
            patterns.append(f"Waiting {len(g['dates'])} days — needs escalation: {g['text'][:80]}")

    return {
        "days_with_debrief": len(debriefs),
        "achievements": _dedup_union(done_all),
        "chronic": chronic_owed + chronic_waiting,
        "decisions_taken": [d for items in decisions_by_day.values() for d in items],
        "recurring_risks": _repeating(risks_by_day),
        "patterns": patterns,
    }


def render_weekly_md(agg: dict, date_from: str, date_to: str, iso_week: str) -> str:
    def bullets(items, key="text"):
        out = []
        for it in items:
            if isinstance(it, dict):
                nd = len(it.get("dates", []))
                out.append(f"- [{nd}d] {it[key]} — {', '.join(it['dates'])}")
            else:
                out.append(f"- {it}")
        return "\n".join(out) or "- (none)"

    return f"""---
date_from: {date_from}
date_to: {date_to}
iso_week: {iso_week}
days_with_debrief: {agg['days_with_debrief']}/5
---

## Closed this week ({len(agg['achievements'])})
{bullets(agg['achievements'])}

## Chronic items ({len(agg['chronic'])})
{bullets(agg['chronic'])}

## Decisions taken ({len(agg['decisions_taken'])})
{bullets(agg['decisions_taken'])}

## Recurring risks ({len(agg['recurring_risks'])})
{bullets(agg['recurring_risks'])}

## Patterns
{bullets(agg['patterns'])}
"""
