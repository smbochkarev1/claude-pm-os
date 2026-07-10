"""Zoom transcript adapter — working reference implementation.

Fetches the auto-generated meeting transcript for a finished Zoom meeting and
returns it as a canonical `Transcript`, so the follow-up engine can extract
who-owns-what. This is the transcript half of the "meeting -> follow-up" path.

Auth: Zoom **Server-to-Server OAuth** (no user interaction). Create an S2S OAuth
app in the Zoom Marketplace and put its values in .env:
  ZOOM_ACCOUNT_ID
  ZOOM_CLIENT_ID
  ZOOM_CLIENT_SECRET
Required scope on the app: cloud_recording:read:list_recording_files (or the
classic recording:read:admin). A short-lived bearer token is minted on demand
and cached until just before it expires.

Flow: POST /oauth/token (account_credentials) -> bearer
      GET  /v2/meetings/{meetingId}/recordings -> find the TRANSCRIPT (VTT) file
      GET  download_url (bearer) -> raw VTT -> parse_vtt() -> clean text

`parse_vtt` is a pure, network-free function and carries the unit tests; the
`requests` dependency is imported lazily so this module (and its parse tests)
load without it installed.

Returns None (not an exception) when the meeting has no recording yet or no
transcript file — the poller treats None as "retry later".
"""

from __future__ import annotations

import base64
import os
import re
import time
from typing import Optional

from .base import Transcript, TranscriptSource

_OAUTH_URL = "https://zoom.us/oauth/token"
_API_BASE = "https://api.zoom.us/v2"
_TIMECODE_RE = re.compile(r"-->")
_TAG_RE = re.compile(r"<[^>]+>")
_SPEAKER_RE = re.compile(r"^([^:]{1,60}):\s+")


class ZoomError(RuntimeError):
    """Raised when Zoom credentials are missing or the API rejects a request."""


# ---------------------------------------------------------------------------
# Pure transforms (network-free; the unit tests live here)
# ---------------------------------------------------------------------------

def parse_vtt(vtt: str) -> str:
    """Turn a WebVTT transcript into clean 'Speaker: line' text.

    Drops the WEBVTT header, NOTE blocks, cue index numbers, timecode lines and
    inline <...> tags; collapses immediately-repeated lines (Zoom sometimes
    duplicates a caption across two cues).
    """
    cleaned: list[str] = []
    for raw in vtt.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.upper().startswith("WEBVTT"):
            continue
        if s.startswith("NOTE"):
            continue
        if _TIMECODE_RE.search(s):
            continue
        if s.isdigit():
            continue
        s = _TAG_RE.sub("", s).strip()
        if not s:
            continue
        if cleaned and cleaned[-1] == s:
            continue
        cleaned.append(s)
    return "\n".join(cleaned)


def speakers_from_text(text: str) -> list[str]:
    """Extract unique speaker names (order-preserving) from 'Name: ...' lines."""
    out: list[str] = []
    for line in text.splitlines():
        m = _SPEAKER_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name and name not in out:
                out.append(name)
    return out


def _pick_transcript_file(recording: dict) -> Optional[dict]:
    for f in recording.get("recording_files", []) or []:
        if str(f.get("file_type", "")).upper() == "TRANSCRIPT":
            return f
    return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ZoomTranscript(TranscriptSource):
    def __init__(
        self,
        account_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: int = 30,
    ):
        self.account_id = account_id or os.environ.get("ZOOM_ACCOUNT_ID", "").strip()
        self.client_id = client_id or os.environ.get("ZOOM_CLIENT_ID", "").strip()
        self.client_secret = client_secret or os.environ.get("ZOOM_CLIENT_SECRET", "").strip()
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    # -- auth --------------------------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if not (self.account_id and self.client_id and self.client_secret):
            raise ZoomError(
                "Zoom credentials not configured: set ZOOM_ACCOUNT_ID, "
                "ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET in your .env.")
        import requests
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = requests.post(
            _OAUTH_URL,
            params={"grant_type": "account_credentials", "account_id": self.account_id},
            headers={"Authorization": f"Basic {basic}"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise ZoomError(f"Zoom OAuth failed: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    # -- fetch -------------------------------------------------------------

    def fetch_transcript(self, meeting_id: str) -> Optional[Transcript]:
        import requests
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}"}

        resp = requests.get(
            f"{_API_BASE}/meetings/{meeting_id}/recordings",
            headers=headers, timeout=self.timeout)
        if resp.status_code in (204, 404):
            return None  # no recording yet — retry later
        if resp.status_code != 200:
            raise ZoomError(
                f"Zoom recordings fetch failed for {meeting_id}: "
                f"HTTP {resp.status_code} {resp.text[:200]}")

        recording = resp.json()
        vtt_file = _pick_transcript_file(recording)
        if not vtt_file or not vtt_file.get("download_url"):
            return None  # recording exists but transcript not ready
        if str(vtt_file.get("status", "completed")).lower() != "completed":
            return None

        dl = requests.get(vtt_file["download_url"], headers=headers, timeout=self.timeout)
        if dl.status_code != 200:
            raise ZoomError(
                f"Zoom transcript download failed for {meeting_id}: HTTP {dl.status_code}")

        text = parse_vtt(dl.text)
        start = recording.get("start_time", "") or ""
        return Transcript(
            meeting_id=str(meeting_id),
            title=recording.get("topic", "") or "Zoom meeting",
            date=start[:10],
            text=text,
            participants=speakers_from_text(text),
        )
