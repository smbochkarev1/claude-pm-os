"""Adapter interfaces for the PM Operating System.

Every external system the PM OS talks to is hidden behind a small abstract
interface defined here. The core engines (classifier, backlog, weekly,
followup) depend ONLY on these interfaces and the canonical dataclasses below,
never on a concrete vendor SDK.

Why: a PM's stack is personal. One person is on Jira + Google Calendar + Slack,
another on Linear + Outlook + Telegram. Swapping a stack means writing one
adapter, not touching the engines. The three adapters that ship working
(spreadsheet_gspread, notifier_telegram, llm) prove the shape; everything under
adapters/stubs/ is an interface you implement for your own tools.

All datetimes are timezone-aware. All text is UTF-8.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Canonical records — the shared vocabulary between adapters and engines.
# Adapters translate vendor payloads INTO these; engines only ever see these.
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """A unit of work from any tracker or spreadsheet."""
    key: str                       # stable id, e.g. "PROJ-123" or a row hash
    title: str
    status: str = ""               # raw source status; engine normalizes it
    owner: str = ""                # assignee handle/login/name
    author: str = ""
    deadline: str = ""             # ISO date or free text
    stream: str = ""               # project / workstream / portfolio
    url: str = ""
    updated_at: Optional[datetime] = None
    source: str = ""               # which adapter/tab produced this
    extra: dict = field(default_factory=dict)


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    attendees: list[str] = field(default_factory=list)
    is_all_day: bool = False
    kind: str = "meeting"          # meeting | vacation | focus | ...

    @property
    def duration_minutes(self) -> int:
        if not (self.start and self.end):
            return 0
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class ChatMessage:
    chat_id: str
    chat_name: str
    author: str
    text: str
    time: str = ""                 # HH:MM display
    from_me: bool = False
    ts: Optional[datetime] = None


@dataclass
class Transcript:
    meeting_id: str
    title: str
    date: str
    text: str
    participants: list[str] = field(default_factory=list)


@dataclass
class SpreadsheetSnapshot:
    """A whole spreadsheet captured as {tab_name: [[cell, ...], ...]}."""
    sheet_id: str
    name: str
    tabs: dict[str, list[list[str]]] = field(default_factory=dict)


@dataclass
class MetricPoint:
    """One observation of a tracked business metric (for metrics_watch)."""
    name: str
    value: float
    unit: str = ""
    observed_at: Optional[datetime] = None
    threshold: Optional[float] = None      # alarm if value crosses this
    direction: str = "below"               # "below" | "above" — bad direction


# ---------------------------------------------------------------------------
# Adapter interfaces
# ---------------------------------------------------------------------------

class TaskTracker(ABC):
    """Jira / Linear / GitHub Issues / Tracker / Asana / ..."""

    @abstractmethod
    def fetch_tasks(
        self,
        me: str,
        since: Optional[datetime] = None,
        roles: Optional[list[str]] = None,
        queues: Optional[list[str]] = None,
        limit: int = 500,
    ) -> list[Task]:
        """Return tasks where `me` is assignee/author/follower, updated >= since."""
        raise NotImplementedError


class Calendar(ABC):
    """Google Calendar / Outlook / CalDAV / ..."""

    @abstractmethod
    def fetch_events(self, me: str, date_from: date, date_to: date) -> list[CalendarEvent]:
        raise NotImplementedError

    def fetch_attendees(self, event_id: str) -> list[str]:
        return []


class Spreadsheet(ABC):
    """Google Sheets / Excel / Airtable / ..."""

    @abstractmethod
    def fetch_snapshot(self, sheet_id: str) -> SpreadsheetSnapshot:
        """Read every tab of a spreadsheet into a SpreadsheetSnapshot."""
        raise NotImplementedError

    def write_tab(self, sheet_id: str, tab: str, rows: list[list], clear: bool = True) -> None:
        raise NotImplementedError


class ChatSource(ABC):
    """Slack / Telegram / Teams / ..."""

    @abstractmethod
    def fetch_messages(
        self,
        me: str,
        since: Optional[datetime] = None,
        max_per_chat: int = 50,
    ) -> list[ChatMessage]:
        raise NotImplementedError


class TranscriptSource(ABC):
    """Meeting-transcript provider (Zoom / Meet / internal ASR / ...)."""

    @abstractmethod
    def fetch_transcript(self, meeting_id: str) -> Optional[Transcript]:
        """Return the transcript, or None if not ready yet."""
        raise NotImplementedError


class MetricsAdapter(ABC):
    """Analytics / dashboard / warehouse source for tracked metrics."""

    @abstractmethod
    def fetch_metrics(self) -> list[MetricPoint]:
        raise NotImplementedError


class Notifier(ABC):
    """Telegram Bot / Slack webhook / email / ..."""

    @abstractmethod
    def send(self, text: str) -> bool:
        """Deliver a plain-text message. Must handle its own chunking."""
        raise NotImplementedError


class LLM(ABC):
    """Any chat-completion provider (Anthropic / OpenAI / local / ...)."""

    @abstractmethod
    def complete(self, prompt: str, max_tokens: int = 4096, model: Optional[str] = None) -> str:
        raise NotImplementedError
