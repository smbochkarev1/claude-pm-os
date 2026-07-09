"""Six-bucket debrief classifier.

Two layers:

1. `classify_by_signals` — a deterministic, keyword-driven pre-classifier. It
   assigns each input item to one of the six buckets using the signal
   dictionaries from config. No network, no LLM. This is what the eval harness
   scores against the golden set, and what the midnight fallback can lean on
   when no LLM key is present.

2. `classify_with_llm` — the production path: builds the externalized prompt
   (prompts/classify.md), calls an LLM adapter, and returns the debrief
   markdown. The LLM refines and traces what the signal layer roughly bins.

Keeping the deterministic layer separate is deliberate: it makes classification
quality measurable without spending tokens, and gives a graceful degraded mode.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from adapters.base import LLM

BUCKETS = [
    "done_today",
    "owed_by_me",
    "waiting_on_others",
    "decisions",
    "risks_blockers",
    "planned_after_today",
]

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "classify.md"

# Fallback signal dictionary if config supplies none. Kept generic/English;
# real deployments extend this in config/pm-os.config.yaml.
DEFAULT_SIGNALS = {
    "done_today": ["done", "closed", "shipped", "sent", "merged", "resolved", "finished"],
    "owed_by_me": ["i'll", "i will", "my task", "on me", "i'll take", "i'll prepare",
                   "i'll check", "i'll send", "i'll write"],
    "waiting_on_others": ["they'll", "he'll", "she'll", "promised", "will get back",
                          "will send", "by friday", "next week", "waiting on"],
    "decisions": ["agreed", "decided", "approved", "rejected", "finalized",
                  "we'll go with", "signed off"],
    "risks_blockers": ["blocker", "blocked", "risk", "slipping", "at risk",
                       "won't make it", "on fire", "escalate"],
    "planned_after_today": ["tomorrow", "next week", "planned", "scheduled",
                            "upcoming", "later this"],
}

# Order matters: earlier buckets win ties (a closed commitment is "done",
# not "owed"). done_today first, planned last.
_BUCKET_ORDER = [
    "done_today",
    "decisions",
    "risks_blockers",
    "waiting_on_others",
    "owed_by_me",
    "planned_after_today",
]


def _match_bucket(text: str, signals: dict, from_me: Optional[bool]) -> Optional[str]:
    low = text.lower()
    hits: dict[str, int] = {}
    for bucket in _BUCKET_ORDER:
        for kw in signals.get(bucket, []):
            if kw and kw.lower() in low:
                hits[bucket] = hits.get(bucket, 0) + 1

    if not hits:
        return None

    # Ownership disambiguation between owed_by_me / waiting_on_others using
    # `from_me` when the input carries it (chat/comment authorship).
    if "owed_by_me" in hits and "waiting_on_others" in hits and from_me is not None:
        return "owed_by_me" if from_me else "waiting_on_others"

    # Highest hit count, tie broken by _BUCKET_ORDER precedence.
    best = max(hits, key=lambda b: (hits[b], -_BUCKET_ORDER.index(b)))
    return best


def classify_by_signals(items: list[dict], signals: Optional[dict] = None) -> dict[str, list[dict]]:
    """Deterministically bin items into the six buckets.

    Each item is a dict with at least `text`; optional `from_me` (bool) and
    `source` (str, kept for traceability). Items that match no signal are
    dropped (they carry no actionable signal).
    """
    sig = {**DEFAULT_SIGNALS, **(signals or {})}
    result: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    for item in items:
        text = item.get("text", "")
        if not text:
            continue
        bucket = _match_bucket(text, sig, item.get("from_me"))
        if bucket:
            result[bucket].append(item)
    return result


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

def build_prompt(today: str, me: str, signals: dict, sources_block: str) -> str:
    template = PROMPT_PATH.read_text()

    def fmt_sig(bucket: str) -> str:
        return ", ".join(signals.get(bucket, [])) or "(none configured)"

    return (
        template
        .replace("{today}", today)
        .replace("{me}", me or "(unknown)")
        .replace("{signals_owed_by_me}", fmt_sig("owed_by_me"))
        .replace("{signals_waiting_on_others}", fmt_sig("waiting_on_others"))
        .replace("{signals_decisions}", fmt_sig("decisions"))
        .replace("{signals_risks}", fmt_sig("risks_blockers"))
        .replace("{sources_block}", sources_block)
    )


def classify_with_llm(
    llm: LLM,
    today: str,
    me: str,
    signals: dict,
    sources_block: str,
    max_tokens: int = 4096,
) -> str:
    """Production classification: returns a debrief markdown document."""
    prompt = build_prompt(today, me, signals, sources_block)
    return llm.complete(prompt, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# Debrief markdown <-> buckets (used by weekly engine and evals)
# ---------------------------------------------------------------------------

_HEADMAP = {
    "## Done today": "done_today",
    "## Owed by me": "owed_by_me",
    "## Waiting on others": "waiting_on_others",
    "## Decisions": "decisions",
    "## Risks & blockers": "risks_blockers",
    "## Planned": "planned_after_today",
}


def parse_debrief_buckets(text: str) -> dict[str, list[str]]:
    """Parse a debrief .md back into {bucket: [bullet, ...]}."""
    buckets: dict[str, list[str]] = {}
    cur: Optional[str] = None
    for line in text.splitlines():
        head = next((v for k, v in _HEADMAP.items() if line.startswith(k)), None)
        if head:
            cur = head
            buckets.setdefault(cur, [])
            continue
        if line.startswith("## Source detail") or line.startswith("## My notes") \
                or line.startswith("## Unclassified"):
            cur = None
            continue
        if cur and re.match(r"^\s*[-•]\s+", line):
            item = re.sub(r"^\s*[-•]\s+", "", line).strip()
            if item:
                buckets[cur].append(item)
    return buckets
