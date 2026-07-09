#!/usr/bin/env python3
"""PM OS eval harness — the quality signal.

Scores the two deterministic engine behaviors that must not regress:

  1. Six-bucket classification (signal layer) against a golden label per item.
  2. Cross-source backlog dedup against a golden set of merged keys.

No network, no LLM key required — both checks are deterministic, so this runs
in CI and locally in under a second. Prints a per-suite and overall pass-rate;
exits non-zero if anything is below 100%.

Usage:
  python eval-harness/run_evals.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.classifier import classify_by_signals            # noqa: E402
from core.backlog_engine import dedup_and_sort, dedup_key, dedup_stats  # noqa: E402

FIXTURES = ROOT / "eval-harness" / "fixtures"
GOLDEN = ROOT / "eval-harness" / "golden"


def _key_str(k: tuple) -> str:
    return f"{k[0]}:{k[1]}"


def eval_classification() -> tuple[int, int, list[str]]:
    items = json.loads((FIXTURES / "debrief_items.json").read_text())
    golden = json.loads((GOLDEN / "classification.json").read_text())

    # Signal layer drops non-matching items; here every fixture item is signalful.
    binned = classify_by_signals(items)
    predicted: dict[str, str] = {}
    for bucket, its in binned.items():
        for it in its:
            predicted[it["id"]] = bucket

    passed, total, failures = 0, 0, []
    for item_id, want in golden.items():
        total += 1
        got = predicted.get(item_id, "<unclassified>")
        if got == want:
            passed += 1
        else:
            text = next((i["text"] for i in items if i["id"] == item_id), "")
            failures.append(f"  [{item_id}] expected {want}, got {got}  «{text[:60]}»")
    return passed, total, failures


def eval_backlog_dedup() -> tuple[int, int, list[str]]:
    rows = json.loads((FIXTURES / "backlog_rows.json").read_text())
    golden = json.loads((GOLDEN / "backlog_dedup.json").read_text())
    cfg = {"streams": [{"key": s, "aliases": []} for s in golden["stream_order"]]}

    out = dedup_and_sort(rows, cfg)
    stats = dedup_stats(rows, out)
    got_keys = sorted({_key_str(dedup_key(r)) for r in out})
    want_keys = sorted(golden["expected_keys"])

    checks: list[tuple[str, bool, str]] = [
        ("row_count", len(out) == golden["expected_row_count"],
         f"expected {golden['expected_row_count']}, got {len(out)}"),
        ("merges", stats["merged"] == golden["expected_merges"],
         f"expected {golden['expected_merges']}, got {stats['merged']}"),
        ("dedup_keys", got_keys == want_keys,
         f"expected {want_keys}, got {got_keys}"),
    ]
    # Stream-order sanity: rows must be grouped by configured stream order.
    order = {s: i for i, s in enumerate(golden["stream_order"])}
    seq = [order.get(r["stream"], 99) for r in out]
    checks.append(("sorted_by_stream", seq == sorted(seq), f"stream sequence {seq}"))

    passed = sum(1 for _, ok, _ in checks if ok)
    failures = [f"  [{name}] {detail}" for name, ok, detail in checks if not ok]
    return passed, len(checks), failures


def main() -> int:
    suites = [
        ("classification (6-bucket signal layer)", eval_classification),
        ("backlog dedup / prioritize", eval_backlog_dedup),
    ]
    total_pass = total_all = 0
    print("PM OS eval harness\n" + "=" * 40)
    for name, fn in suites:
        passed, total, failures = fn()
        total_pass += passed
        total_all += total
        rate = 100.0 * passed / total if total else 0.0
        status = "PASS" if passed == total else "FAIL"
        print(f"[{status}] {name}: {passed}/{total} ({rate:.0f}%)")
        for f in failures:
            print(f)
    overall = 100.0 * total_pass / total_all if total_all else 0.0
    print("=" * 40)
    print(f"OVERALL pass-rate: {total_pass}/{total_all} ({overall:.0f}%)")
    return 0 if total_pass == total_all else 1


if __name__ == "__main__":
    sys.exit(main())
