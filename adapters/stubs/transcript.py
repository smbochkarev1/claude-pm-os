"""STUB: meeting-transcript adapter.

Implement `fetch_transcript` for your meeting provider (Zoom, Google Meet,
Teams, or an internal ASR service). Return a `Transcript`, or None if the
transcript is not ready yet — the transcript poller treats None as "retry
later" and keeps the meeting in its pending queue.

Guidance:
  - `meeting_id` matches the id on the CalendarEvent from your calendar adapter.
  - Return None (not an exception) for HTTP 404/204 "not ready".
  - Fill `participants` when you can; the follow-up engine uses them to
    attribute action items to real owners.

Example skeletons:
  Zoom    GET /meetings/{id}/recordings -> transcript file
  Meet    Drive/Docs export of the generated transcript
"""

from __future__ import annotations

from typing import Optional

from ..base import Transcript, TranscriptSource


class MyTranscriptSource(TranscriptSource):
    def fetch_transcript(self, meeting_id: str) -> Optional[Transcript]:
        raise NotImplementedError(
            "Implement fetch_transcript for your meeting provider. "
            "Return adapters.base.Transcript, or None if not ready yet."
        )
