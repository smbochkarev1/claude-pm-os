"""Google Calendar adapter — working reference implementation.

Reads events for a date range and maps them into the canonical `CalendarEvent`
records the engines understand. This is the calendar half of the end-to-end
"calendar -> debrief" and "meeting -> follow-up" paths.

Auth (same shape as spreadsheet_gspread — google-auth, no vendor lock-in in the
engines):
  - GOOGLE_TOKEN_JSON        OAuth *user* token json (authorized_user format),
                             minted once with the calendar.readonly scope.
  - GOOGLE_CREDENTIALS_JSON  *service account* key json (alternative to the
                             user token; set GOOGLE_CALENDAR_SUBJECT to
                             domain-wide-delegate to a mailbox).
  - GOOGLE_CALENDAR_ID       which calendar to read (default: "primary").
  - GOOGLE_CALENDAR_TIMEZONE optional IANA tz for the query window + naive
                             all-day events (default: UTC).

Only the transform functions (`parse_event`, `parse_events`, `parse_attendees`)
are import-time cheap and network-free — they carry the unit tests. The Google
client libraries are imported lazily so the module (and its parse tests) load
without them installed.

Meeting-id note: when an event has a Zoom conference attached, `CalendarEvent.id`
is set to the *Zoom meeting number* extracted from the join URL, so the transcript
poller can hand it straight to the Zoom transcript adapter. Otherwise it's the
Google event id.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .base import Calendar, CalendarEvent

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

_ZOOM_ID_RE = re.compile(r"zoom\.us/(?:j|w|wc/join|my)/(\d{8,})")


class CalendarAuthError(RuntimeError):
    """Raised when no usable Google credentials are configured."""


# ---------------------------------------------------------------------------
# Pure transforms (network-free; the unit tests live here)
# ---------------------------------------------------------------------------

def _parse_dt(node: dict, default_tz) -> tuple[Optional[datetime], bool]:
    """Return (tz-aware datetime, is_all_day) for a Google start/end node."""
    if not node:
        return None, False
    if node.get("dateTime"):
        raw = node["dateTime"]
        # Python's fromisoformat handles the trailing 'Z' from 3.11+.
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt, False
    if node.get("date"):
        d = date.fromisoformat(node["date"])
        return datetime(d.year, d.month, d.day, tzinfo=default_tz), True
    return None, False


def parse_attendees(items: list[dict]) -> list[str]:
    """Map Google attendee objects to display names (email fallback).

    Skips meeting rooms / resources; keeps humans in calendar order.
    """
    out: list[str] = []
    for a in items or []:
        if a.get("resource"):
            continue
        name = (a.get("displayName") or a.get("email") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _zoom_meeting_id(raw: dict) -> str:
    """Extract a Zoom meeting number from an event's conference/join links."""
    conf = raw.get("conferenceData", {}) or {}
    candidates = [raw.get("hangoutLink", ""), raw.get("location", "")]
    candidates += [ep.get("uri", "") for ep in conf.get("entryPoints", []) or []]
    for uri in candidates:
        m = _ZOOM_ID_RE.search(uri or "")
        if m:
            return m.group(1)
    solution = (conf.get("conferenceSolution", {}) or {}).get("name", "").lower()
    if "zoom" in solution and conf.get("conferenceId"):
        digits = re.sub(r"\D", "", str(conf["conferenceId"]))
        if digits:
            return digits
    return ""


def _kind(raw: dict) -> str:
    et = raw.get("eventType", "default")
    if et == "outOfOffice":
        return "vacation"
    if et == "focusTime":
        return "focus"
    if raw.get("transparency") == "transparent" and not raw.get("attendees"):
        return "focus"
    return "meeting"


def parse_event(raw: dict, default_tz=timezone.utc) -> CalendarEvent:
    """Translate one Google `events` resource into a canonical CalendarEvent."""
    start, all_day_s = _parse_dt(raw.get("start", {}), default_tz)
    end, all_day_e = _parse_dt(raw.get("end", {}), default_tz)
    return CalendarEvent(
        id=_zoom_meeting_id(raw) or raw.get("id", ""),
        title=(raw.get("summary") or "(no title)").strip(),
        start=start,
        end=end,
        attendees=parse_attendees(raw.get("attendees", [])),
        is_all_day=all_day_s or all_day_e,
        kind=_kind(raw),
    )


def parse_events(items: list[dict], default_tz=timezone.utc) -> list[CalendarEvent]:
    """Translate a page of Google events, skipping cancelled ones."""
    return [
        parse_event(raw, default_tz)
        for raw in items or []
        if raw.get("status") != "cancelled"
    ]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class GoogleCalendar(Calendar):
    def __init__(self, calendar_id: Optional[str] = None):
        self._calendar_id = calendar_id or os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        self._service = None
        self._default_tz = self._resolve_tz()

    @staticmethod
    def _resolve_tz():
        name = os.environ.get("GOOGLE_CALENDAR_TIMEZONE", "").strip()
        if not name:
            return timezone.utc
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            return timezone.utc

    def _credentials(self):
        token_path = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
        sa_path = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
        if token_path and Path(token_path).expanduser().exists():
            from google.oauth2.credentials import Credentials
            return Credentials.from_authorized_user_file(
                str(Path(token_path).expanduser()), SCOPES)
        if sa_path and Path(sa_path).expanduser().exists():
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(
                str(Path(sa_path).expanduser()), scopes=SCOPES)
            subject = os.environ.get("GOOGLE_CALENDAR_SUBJECT", "").strip()
            return creds.with_subject(subject) if subject else creds
        raise CalendarAuthError(
            "Google Calendar credentials not configured: set GOOGLE_TOKEN_JSON "
            "(OAuth user token) or GOOGLE_CREDENTIALS_JSON (service account) in "
            "your .env, pointing at an existing json file.")

    def _service_lazy(self):
        if self._service is not None:
            return self._service
        from googleapiclient.discovery import build
        self._service = build(
            "calendar", "v3", credentials=self._credentials(), cache_discovery=False)
        return self._service

    def fetch_events(self, me: str, date_from: date, date_to: date) -> list[CalendarEvent]:
        service = self._service_lazy()
        tz = self._default_tz
        time_min = datetime.combine(date_from, dtime.min, tzinfo=tz).isoformat()
        time_max = datetime.combine(date_to + timedelta(days=1), dtime.min, tzinfo=tz).isoformat()

        events: list[CalendarEvent] = []
        page_token = None
        while True:
            resp = service.events().list(
                calendarId=self._calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
                pageToken=page_token,
            ).execute()
            events.extend(parse_events(resp.get("items", []), tz))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return events

    def fetch_attendees(self, event_id: str) -> list[str]:
        service = self._service_lazy()
        raw = service.events().get(
            calendarId=self._calendar_id, eventId=event_id).execute()
        return parse_attendees(raw.get("attendees", []))
