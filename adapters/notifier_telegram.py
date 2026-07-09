"""Telegram Bot API notifier.

Delivers plain-text messages over HTTPS (Bot API), so it works on any network,
including restrictive corporate wifi — no MTProto. Handles the 4096-char limit
by splitting long text on line boundaries, and retries once on HTTP 429.

Also ships two formatters that turn the internal markdown artifacts
(debriefs, recaps) into clean chat text with bucket emoji and no source tags —
lifted from the original send_to_bot and generalized.

Environment (preferred) or constructor args:
  NOTIFIER_BOT_TOKEN   bot token from @BotFather
  NOTIFIER_CHAT_ID     target chat id (your DM = positive, group = negative)
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Optional

from .base import Notifier

MAX_MESSAGE_LENGTH = 4096
CHUNK_LIMIT = MAX_MESSAGE_LENGTH - 16  # reserve room for the "[i/n]\n" prefix

# Order matters: more specific bucket names first.
BUCKET_EMOJI = [
    ("owed by me", "\U0001F4CC"),
    ("done today", "✅"),
    ("waiting on others", "⏳"),
    ("decisions", "\U0001F511"),
    ("risks", "\U0001F6A8"),
    ("planned", "\U0001F4C5"),
    ("my notes", "\U0001F4DD"),
    ("unclassified", "\U0001F4CE"),
]

# Generic inline source-tag stripping for chat output.
_TAG_PATTERNS = [
    r"\s*\[[A-Z][A-Z0-9]+-\d+[^\]]*\]",          # [PROJ-123, comment 12:00]
    r"\s*\[chat\s*/[^\]]*\]",                      # [chat / "Name" / msg 12:34]
    r"\s*\[meeting\s+[^\]]*\]",                    # [meeting <id>, 12:34]
    r"\s*\[sheet[^\]]*\]",                         # [sheet Name / "tab" / A5]
    r"\s*\[my note\]",
]


class TelegramNotifier(Notifier):
    def __init__(self, token: Optional[str] = None, chat_id: Optional[int] = None):
        self.token = token or os.environ.get("NOTIFIER_BOT_TOKEN", "").strip()
        raw_chat = chat_id if chat_id is not None else os.environ.get("NOTIFIER_CHAT_ID", "0")
        try:
            self.chat_id = int(raw_chat)
        except (TypeError, ValueError):
            self.chat_id = 0
        if not self.token or not self.chat_id:
            raise ValueError("NOTIFIER_BOT_TOKEN and NOTIFIER_CHAT_ID must be set")

    # -- delivery ----------------------------------------------------------

    def send(self, text: str) -> bool:
        if len(text) <= MAX_MESSAGE_LENGTH:
            return self._send_one(text)
        chunks = _split_into_chunks(text)
        ok_all = True
        for i, chunk in enumerate(chunks, 1):
            if len(chunks) > 1:
                chunk = f"[{i}/{len(chunks)}]\n{chunk}"
            if not self._send_one(chunk):
                ok_all = False
            if i < len(chunks):
                time.sleep(1)  # stay under the rate limit between chunks
        return ok_all

    def _send_one(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }).encode()
        for attempt in range(2):
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read()).get("ok", False)
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                if e.code == 429 and attempt == 0:
                    retry_after = 1
                    try:
                        retry_after = int(json.loads(body).get("parameters", {}).get("retry_after", 1))
                    except Exception:
                        pass
                    time.sleep(min(retry_after, 30))
                    continue
                return False
            except urllib.error.URLError:
                return False
        return False


# ---------------------------------------------------------------------------
# Formatters (pure functions; usable without a live bot)
# ---------------------------------------------------------------------------

def strip_source_tags(text: str) -> str:
    """Remove inline source tags and markdown emphasis from a bullet line."""
    for pat in _TAG_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()


def format_debrief_md(raw: str) -> str:
    """Turn a debrief .md into readable chat text: drops frontmatter, the
    Source detail section, tables and markdown; maps headers to bucket emoji."""
    lines = raw.splitlines()

    # Drop YAML frontmatter.
    start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                start = i + 1
                break
    lines = lines[start:]

    # Cut at Source detail.
    cut = len(lines)
    for i, line in enumerate(lines):
        if re.match(r"^#{1,3}\s*Source detail", line, re.IGNORECASE):
            cut = i
            break
    lines = lines[:cut]

    out: list[str] = []
    in_code = False
    for line in lines:
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if re.match(r"^\|[-| :]+\|$", s) or (s.startswith("|") and s.endswith("|")):
            continue
        if re.match(r"^---+$", s):
            out.append("")
            continue
        m = re.match(r"^#\s+(.+)", s)
        if m:
            out.append(f"\n\U0001F4CB {m.group(1).strip()}")
            continue
        m = re.match(r"^#{2}\s+(.+)", s)
        if m:
            title = m.group(1).strip()
            tl = title.lower()
            emoji = next((v for k, v in BUCKET_EMOJI if k in tl), "▸")
            out.append(f"\n{emoji} {title.upper()}")
            continue
        m = re.match(r"^#{3}\s+(.+)", s)
        if m:
            out.append(f"  ↳ {m.group(1).strip()}")
            continue
        m = re.match(r"^[-*]\s+(.+)", s)
        if m:
            out.append(f"  • {strip_source_tags(m.group(1))}")
            continue
        m = re.match(r"^>\s+(.+)", s)
        if m:
            out.append(f"  \U0001F4AC {strip_source_tags(m.group(1))}")
            continue
        if s:
            out.append(strip_source_tags(s))
        elif out and out[-1] != "":
            out.append("")

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def format_summary_text(raw: str) -> str:
    """Format a plain-text recap/weekly summary for chat: strips tags/markdown,
    normalizes bullets."""
    out: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            if out and out[-1] != "":
                out.append("")
            continue
        m = re.match(r"^#{1,3}\s+(.+)", s)
        if m:
            out.append(strip_source_tags(m.group(1).strip()))
            continue
        m = re.match(r"^[•\-*]\s+(.+)", s)
        if m:
            out.append(f"• {strip_source_tags(m.group(1))}")
            continue
        m = re.match(r"^\s{2,}[•\-*◦]\s+(.+)", s)
        if m:
            out.append(f"  ◦ {strip_source_tags(m.group(1))}")
            continue
        out.append(strip_source_tags(s))
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _split_into_chunks(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            chunks.append("".join(current))
            current = []
            current_len = 0

    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            flush()
            chunks.append(line[:limit])
            line = line[limit:]
        if current_len + len(line) > limit and current:
            flush()
        current.append(line)
        current_len += len(line)
    flush()
    return chunks
