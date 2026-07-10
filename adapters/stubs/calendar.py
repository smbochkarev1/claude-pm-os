"""STUB: calendar adapter.

For Google Calendar there is a WORKING reference already —
`adapters.calendar_google:GoogleCalendar`. Use this stub as the interface to
implement other calendars (Outlook/Graph, CalDAV, ...).

Implement `fetch_events` (and optionally `fetch_attendees`) for your calendar.
Translate events into `CalendarEvent` records with tz-aware start/end.

Guidance:
  - Skip all-day and out-of-office entries, or mark them via `kind`.
  - `fetch_attendees` is used by the transcript poller to attribute follow-ups
    to the right people; return handles/logins/emails.

Example skeletons:
  Google   GET /calendar/v3/calendars/primary/events?timeMin=..&timeMax=..
  Outlook  GET /me/calendarView?startDateTime=..&endDateTime=..
"""

from __future__ import annotations

from datetime import date

from ..base import Calendar, CalendarEvent


class MyCalendar(Calendar):
    def fetch_events(self, me: str, date_from: date, date_to: date) -> list[CalendarEvent]:
        raise NotImplementedError(
            "Implement fetch_events for your calendar. "
            "Map each event to adapters.base.CalendarEvent."
        )

    def fetch_attendees(self, event_id: str) -> list[str]:
        return []
