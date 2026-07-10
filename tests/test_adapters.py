"""Unit tests for the working reference adapters' transform logic.

No network, no credentials: these exercise the pure parse functions that turn a
vendor payload into the canonical dataclasses. The HTTP/auth plumbing around
them is thin and lazily-imported, so it stays out of CI.
"""

from __future__ import annotations

import sys
from datetime import date, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.base import CalendarEvent, Transcript  # noqa: E402
from adapters.calendar_google import (  # noqa: E402
    parse_attendees,
    parse_event,
    parse_events,
)
from adapters.transcript_zoom import (  # noqa: E402
    parse_vtt,
    speakers_from_text,
    _pick_transcript_file,
)


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

TIMED_EVENT = {
    "id": "abc123",
    "status": "confirmed",
    "summary": "Payments sync",
    "start": {"dateTime": "2026-03-14T10:00:00+03:00"},
    "end": {"dateTime": "2026-03-14T10:30:00+03:00"},
    "attendees": [
        {"email": "jordan@example.com", "displayName": "Jordan"},
        {"email": "dana@example.com"},
        {"email": "room-5@resource.calendar.google.com", "resource": True,
         "displayName": "Room 5"},
    ],
}

ALL_DAY_EVENT = {
    "id": "vac1",
    "status": "confirmed",
    "summary": "PTO",
    "eventType": "outOfOffice",
    "start": {"date": "2026-03-16"},
    "end": {"date": "2026-03-17"},
}

ZOOM_EVENT = {
    "id": "gcal-999",
    "status": "confirmed",
    "summary": "Roadmap review",
    "start": {"dateTime": "2026-03-14T15:00:00Z"},
    "end": {"dateTime": "2026-03-14T16:00:00Z"},
    "conferenceData": {
        "conferenceSolution": {"name": "Zoom Meeting"},
        "entryPoints": [
            {"entryPointType": "video", "uri": "https://us02web.zoom.us/j/89012345678?pwd=x"}
        ],
    },
    "attendees": [{"email": "sam@example.com", "displayName": "Sam"}],
}

CANCELLED_EVENT = {"id": "gone", "status": "cancelled", "summary": "Cancelled"}


def test_parse_timed_event():
    ev = parse_event(TIMED_EVENT)
    assert isinstance(ev, CalendarEvent)
    assert ev.id == "abc123"
    assert ev.title == "Payments sync"
    assert ev.is_all_day is False
    assert ev.kind == "meeting"
    assert ev.duration_minutes == 30
    # tz-aware start preserved
    assert ev.start is not None and ev.start.tzinfo is not None


def test_parse_attendees_skips_resources_and_dedups():
    names = parse_attendees(TIMED_EVENT["attendees"])
    assert names == ["Jordan", "dana@example.com"]  # room dropped, email fallback


def test_parse_all_day_event():
    ev = parse_event(ALL_DAY_EVENT)
    assert ev.is_all_day is True
    assert ev.kind == "vacation"
    assert ev.start is not None and ev.start.tzinfo is not None
    assert ev.start.date() == date(2026, 3, 16)


def test_zoom_conference_id_becomes_event_id():
    ev = parse_event(ZOOM_EVENT)
    # id is the Zoom meeting number extracted from the join URL, not the gcal id
    assert ev.id == "89012345678"
    assert ev.kind == "meeting"


def test_default_tz_applied_to_naive_datetime():
    raw = {
        "id": "n1", "status": "confirmed", "summary": "No tz",
        "start": {"dateTime": "2026-03-14T09:00:00"},
        "end": {"dateTime": "2026-03-14T09:30:00"},
    }
    ev = parse_event(raw, default_tz=timezone.utc)
    assert ev.start is not None and ev.start.tzinfo == timezone.utc


def test_parse_events_skips_cancelled():
    out = parse_events([TIMED_EVENT, CANCELLED_EVENT, ZOOM_EVENT])
    assert len(out) == 2
    assert [e.title for e in out] == ["Payments sync", "Roadmap review"]


# ---------------------------------------------------------------------------
# Zoom transcript (VTT)
# ---------------------------------------------------------------------------

SAMPLE_VTT = """WEBVTT

NOTE recorded by Zoom

1
00:00:01.000 --> 00:00:04.000
Jordan: Let's ship the retry-on-decline flow to 20% today.

2
00:00:04.500 --> 00:00:07.000
Jordan: Let's ship the retry-on-decline flow to 20% today.

3
00:00:07.500 --> 00:00:11.000
Dana: I'll prepare the rollback criteria before we go to 50%.

4
00:00:11.500 --> 00:00:14.000
<v Sam>Sam: I'll check the mobile tax edge case.</v>
"""


def test_parse_vtt_strips_timecodes_indices_and_header():
    text = parse_vtt(SAMPLE_VTT)
    lines = text.splitlines()
    assert "WEBVTT" not in text
    assert "-->" not in text
    assert "00:00" not in text
    # inline <v ...> tag removed
    assert "<v" not in text and "</v>" not in text
    assert lines[0] == "Jordan: Let's ship the retry-on-decline flow to 20% today."


def test_parse_vtt_collapses_consecutive_duplicates():
    text = parse_vtt(SAMPLE_VTT)
    # the duplicated Jordan line (cue 1 and 2) appears once
    assert text.count("Let's ship the retry-on-decline flow") == 1


def test_speakers_from_text():
    text = parse_vtt(SAMPLE_VTT)
    assert speakers_from_text(text) == ["Jordan", "Dana", "Sam"]


def test_pick_transcript_file():
    recording = {
        "recording_files": [
            {"file_type": "MP4", "download_url": "https://x/mp4"},
            {"file_type": "TRANSCRIPT", "download_url": "https://x/vtt"},
        ]
    }
    f = _pick_transcript_file(recording)
    assert f is not None and f["download_url"] == "https://x/vtt"
    assert _pick_transcript_file({"recording_files": []}) is None


def test_transcript_dataclass_shape():
    # sanity: the canonical record the adapter returns
    t = Transcript(meeting_id="1", title="x", date="2026-03-14", text="a",
                   participants=["Jordan"])
    assert t.participants == ["Jordan"]
