"""Cross-source backlog engine — normalize -> dedup -> prioritize.

Turns heterogeneous task rows (from any number of spreadsheets, plus live
tracker tasks, plus owed items pulled from debriefs) into one clean, deduped,
prioritized backlog. All source "dirt" — which column is the title, where the
header row sits, how a status string maps to a canonical status — lives in
config (config/backlog_sources.yaml), never in this code.

Pipeline:
  1. normalize   map raw rows to the canonical schema; normalize status & stream
  2. merge       fold in tracker Tasks and debrief-owed rows
  3. dedup       primary key = ticket id; else normalized (title + stream)
  4. sort        stream order -> priority -> deadline -> title, assign BL-NNN ids

This module is pure data transformation: no network, no vendor SDK. The command
layer supplies snapshots (via a Spreadsheet adapter) and tracker Tasks (via a
TaskTracker adapter); publishing the result is the Spreadsheet adapter's job.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from adapters.base import Task

TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")

CANON_FIELDS = [
    "stream", "substream", "task", "segment", "status", "source_status",
    "priority", "owner", "co_owner", "deadline", "effect", "ticket",
    "ticket_url", "my_action_items", "blockers", "comment",
    "ticket_status_live", "last_update", "source",
]


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def _clean(v) -> str:
    return str(v).replace("\xa0", " ").strip() if v is not None else ""


def norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def parse_tickets(*texts) -> list[str]:
    keys: list[str] = []
    for t in texts:
        for m in TICKET_RE.findall(t or ""):
            if m not in keys:
                keys.append(m)
    return keys


def fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_key(a), norm_key(b)).ratio()


def _cell(row: list, idx) -> str:
    return _clean(row[idx]) if idx is not None and idx < len(row) else ""


# ---------------------------------------------------------------------------
# Config-driven normalization
# ---------------------------------------------------------------------------

def normalize_status(raw: str, cfg: dict) -> str:
    low = raw.lower()
    if not low:
        return ""
    for canon, aliases in cfg.get("statuses", {}).items():
        for a in aliases:
            if a and a in low:
                return canon
    return ""


def normalize_stream(raw: str, default: str, cfg: dict) -> str:
    low = (raw or "").lower()
    for s in cfg.get("streams", []):
        for a in s.get("aliases", []):
            if a and a in low:
                return s["key"]
    return default or cfg.get("default_stream", "Other")


def _empty_row() -> dict:
    return {f: "" for f in CANON_FIELDS} | {"effect_mln": None}


def normalize_snapshot_rows(snapshot_tabs: dict, source_cfg: dict, cfg: dict) -> list[dict]:
    """Map one spreadsheet's tabs into canonical rows using its source config.

    `snapshot_tabs` is {tab_name: [[cell,...],...]} (a SpreadsheetSnapshot.tabs).
    """
    rows: list[dict] = []
    for tab in source_cfg.get("tabs", []):
        grid = snapshot_tabs.get(tab["name"], [])
        cols = tab.get("columns", {})
        start = tab.get("data_start_row", 2) - 1
        for grow in grid[start:]:
            rec = _empty_row()
            for f, idx in cols.items():
                rec[f] = _cell(grow, idx)
            if tab.get("task_template") and not rec["task"]:
                try:
                    rec["task"] = tab["task_template"].format(*[_clean(c) for c in grow])
                except (IndexError, KeyError):
                    pass
            if not rec["task"]:
                continue
            # Skip bare section dividers ("1. Section" with nothing else).
            others = [rec[f] for f in CANON_FIELDS if f not in ("task", "stream", "substream")]
            if re.match(r"^\d+[.)]\s", rec["task"]) and not any(others):
                continue
            rec["stream"] = normalize_stream(
                rec["stream"] or tab.get("default_stream", ""),
                tab.get("default_stream", ""), cfg,
            )
            rec["source_status"] = rec["source_status"] or rec["status"]
            rec["status"] = normalize_status(rec["status"], cfg)
            tks = parse_tickets(rec["ticket"], rec["ticket_url"])
            rec["ticket"] = ", ".join(tks)
            prefix = cfg.get("tracker", {}).get("ticket_url_prefix", "")
            if tks and prefix and not rec["ticket_url"].startswith("http"):
                rec["ticket_url"] = prefix + tks[0]
            rec["source"] = f"{source_cfg.get('label', source_cfg.get('name', ''))} / {tab['name']}"
            rows.append(rec)
    return rows


def tasks_to_rows(tasks: list[Task], cfg: dict) -> list[dict]:
    """Fold live tracker Tasks into canonical rows (dedup handles overlaps)."""
    prefix = cfg.get("tracker", {}).get("ticket_url_prefix", "")
    out: list[dict] = []
    for t in tasks:
        rec = _empty_row()
        rec.update(
            task=t.title or t.key,
            ticket=t.key if TICKET_RE.fullmatch(t.key or "") else "",
            ticket_url=t.url or (prefix + t.key if prefix and t.key else ""),
            ticket_status_live=t.status,
            owner=t.owner,
            deadline=t.deadline,
            stream=normalize_stream(t.stream or t.title, t.stream, cfg),
            source=t.source or "Tracker",
        )
        out.append(rec)
    return out


def debrief_owed_to_rows(owed_bullets: list[str], cfg: dict, source_label: str) -> list[dict]:
    """Turn a debrief's `Owed by me` bullets into candidate backlog rows."""
    prefix = cfg.get("tracker", {}).get("ticket_url_prefix", "")
    out: list[dict] = []
    for line in owed_bullets:
        tks = parse_tickets(line)
        short = re.split(r"\s[—-]\s", line)[0][:120]
        rec = _empty_row()
        rec.update(
            task=short, my_action_items=line,
            stream=normalize_stream(line, cfg.get("default_stream", "Other"), cfg),
            status="In progress", source_status="owed (debrief)",
            ticket=", ".join(tks),
            ticket_url=(prefix + tks[0]) if (tks and prefix) else "",
            last_update=line, source=source_label,
        )
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Dedup + sort
# ---------------------------------------------------------------------------

def dedup_key(r: dict) -> tuple:
    tks = [x.strip() for x in r.get("ticket", "").split(",") if x.strip()]
    if tks:
        return ("t", tks[0])
    return ("n", norm_key(r.get("task", "")) + "|" + r.get("stream", ""))


def _merge(a: dict, b: dict) -> dict:
    for f in CANON_FIELDS:
        if not a.get(f) and b.get(f):
            a[f] = b[f]
    if a.get("effect_mln") is None:
        a["effect_mln"] = b.get("effect_mln")
    srcs = sorted({s for s in (a.get("source", ""), b.get("source", "")) if s})
    a["source"] = " ; ".join(srcs)
    return a


def dedup_and_sort(rows: list[dict], cfg: dict) -> list[dict]:
    """Dedup by ticket id (else title+stream), then sort and assign BL-NNN ids.

    Returns the deduped, sorted rows. Stats are available via `dedup_stats`.
    """
    merged: dict[tuple, dict] = {}
    for r in rows:
        k = dedup_key(r)
        if k in merged:
            _merge(merged[k], r)
        else:
            merged[k] = dict(r)
    out = list(merged.values())

    stream_order = {s["key"]: i for i, s in enumerate(cfg.get("streams", []))}

    def prio_num(r: dict) -> int:
        m = re.search(r"\d+", r.get("priority", ""))
        return int(m.group()) if m else 99

    out.sort(key=lambda r: (
        stream_order.get(r.get("stream", ""), 99),
        prio_num(r),
        r.get("deadline") or "~",
        norm_key(r.get("task", "")),
    ))
    for i, r in enumerate(out, 1):
        r["id"] = f"BL-{i:03d}"
    return out


def dedup_stats(before: list[dict], after: list[dict]) -> dict:
    return {"before": len(before), "after": len(after), "merged": len(before) - len(after)}


def build_backlog(
    snapshots: dict[str, dict],
    cfg: dict,
    tracker_tasks: Optional[list[Task]] = None,
    owed_bullets: Optional[list[str]] = None,
    owed_source: str = "Debrief",
) -> tuple[list[dict], dict]:
    """End-to-end assembly.

    `snapshots` maps source name -> SpreadsheetSnapshot.tabs. Returns
    (rows, stats).
    """
    rows: list[dict] = []
    for src in cfg.get("sources", []):
        tabs = snapshots.get(src.get("name", ""), {})
        rows.extend(normalize_snapshot_rows(tabs, src, cfg))
    if tracker_tasks:
        rows.extend(tasks_to_rows(tracker_tasks, cfg))
    if owed_bullets:
        rows.extend(debrief_owed_to_rows(owed_bullets, cfg, owed_source))

    before = list(rows)
    out = dedup_and_sort(rows, cfg)
    return out, dedup_stats(before, out)
