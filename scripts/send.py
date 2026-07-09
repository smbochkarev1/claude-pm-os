#!/usr/bin/env python3
"""Deliver a debrief/recap through the configured notifier.

  python scripts/send.py --file debriefs/2026-07-09.md      # format a debrief .md
  python scripts/send.py --stdin --format < recap.txt        # format a plain recap
  echo "text" | python scripts/send.py --stdin               # send as-is

Uses the notifier adapter named in config (default: Telegram Bot API) and the
formatters in adapters.notifier_telegram.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PM_OS_HOME", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))

from core.runtime import load_config, load_adapter                       # noqa: E402
from adapters.notifier_telegram import format_debrief_md, format_summary_text  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a debrief/recap via the notifier")
    ap.add_argument("--file", help="path to a debrief .md (auto-formatted)")
    ap.add_argument("--stdin", action="store_true", help="read text from stdin")
    ap.add_argument("--format", action="store_true", help="apply summary formatting")
    ap.add_argument("message", nargs="?", help="literal message text")
    args = ap.parse_args()

    if args.file:
        text = format_debrief_md(Path(args.file).read_text())
    elif args.stdin:
        raw = sys.stdin.read()
        text = format_summary_text(raw) if args.format else raw
    elif args.message:
        text = format_summary_text(args.message) if args.format else args.message
    else:
        ap.error("provide --file, --stdin, or a message")
        return 2

    cfg = load_config()
    notifier = load_adapter(cfg["notifier"]["adapter"])
    ok = notifier.send(text)
    print("delivered" if ok else "delivery failed", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
