"""Post-meeting follow-up engine.

Given a meeting Transcript, extract only outcome items — decisions, who-owns-what
tasks, and what we're waiting on — attribute each to the right owner, and render
a compact follow-up message. The heavy lifting is an LLM call behind the
externalized prompt (prompts/followup.md); this module builds the prompt,
parses the JSON, and formats the message.

Owner attribution is the hard part: each item's owner is whoever actually made
the commitment (spoke the line), not whoever was merely mentioned. The prompt
enforces that; the speaker table passed in keeps @handles honest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from adapters.base import LLM, Transcript

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "followup.md"

SECTION_EMOJI = {
    "agreed": "\U0001F3AF",
    "to do": "\U0001F4CC",
    "waiting": "⏳",
    "open questions": "❓",
    "risks": "\U0001F6A8",
}


def extract_speaker_labels(body: str) -> list[str]:
    """Speaker labels = the line right after an `H:MM:SS` timestamp."""
    labels: list[str] = []
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\d{1,2}:\d{2}:\d{2}\s*$", line.strip()) and i + 1 < len(lines):
            lbl = lines[i + 1].strip()
            if lbl:
                labels.append(lbl)
    seen, out = set(), []
    for l in labels:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


def build_prompt(transcript: Transcript, owner_handle: Optional[str], speaker_labels: list[str]) -> str:
    template = PROMPT_PATH.read_text()
    people = "\n".join(f"  - {l}" for l in speaker_labels) or "  (could not detect speakers)"
    owner_note = (
        f"The meeting owner is {owner_handle}. Capture their OWN commitments carefully, "
        f"but never assign others' tasks to them."
        if owner_handle else
        "No configured owner — assign each item strictly to whoever spoke it."
    )
    return (
        template
        .replace("{title}", transcript.title)
        .replace("{date}", transcript.date)
        .replace("{participants}", ", ".join(transcript.participants) or "(not listed)")
        .replace("{speaker_labels}", people)
        .replace("{owner_note}", owner_note)
        .replace("{transcript}", transcript.text)
    )


def _parse_json(raw: str) -> Optional[dict]:
    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean.strip(), flags=re.MULTILINE)
    m = re.search(r"\{[\s\S]+\}", clean)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def extract_followups(
    llm: LLM,
    transcript: Transcript,
    owner_handle: Optional[str] = None,
    max_tokens: int = 4096,
) -> Optional[dict]:
    """Return the parsed follow-up structure, or None on unrecoverable parse error."""
    labels = extract_speaker_labels(transcript.text)
    prompt = build_prompt(transcript, owner_handle, labels)
    raw = llm.complete(prompt, max_tokens=max_tokens)
    result = _parse_json(raw)
    if result is None:
        # One repair attempt with a stricter instruction.
        repair = (
            "Return ONLY valid JSON, no markdown fence. Do not use raw newlines "
            "inside string values. Here is your previous answer:\n\n" + raw[:3000]
        )
        result = _parse_json(llm.complete(repair, max_tokens=max_tokens))
    return result


def render_message(result: dict, title: str, date: str) -> str:
    date_fmt = date
    if re.match(r"\d{4}-\d{2}-\d{2}", date):
        p = date.split("-")
        date_fmt = f"{p[2]}.{p[1]}"

    lines = [f"\U0001F4CB Follow-up: «{title}» ({date_fmt})"]
    intro = (result.get("intro") or "").strip()
    if intro:
        lines += ["", intro]

    for section in result.get("sections", []):
        stype = (section.get("type") or "").lower()
        emoji = SECTION_EMOJI.get(stype, "▸")
        lines += ["", f"{emoji} {stype.capitalize()}:"]
        for item in section.get("items", []):
            text = (item.get("text") or "").strip()
            owner = item.get("owner_handle") or ""
            deadline = item.get("deadline") or ""
            bullet = f"• {owner} — {text}" if owner and owner not in text else f"• {text}"
            if deadline:
                bullet += f" (by {deadline})"
            lines.append(bullet)
            if item.get("suggested_chat"):
                lines.append(f"  → ping in «{item['suggested_chat']}»")
    return "\n".join(lines).rstrip() + "\n"
