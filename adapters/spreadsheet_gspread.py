"""Google Sheets adapter via gspread + OAuth user credentials.

Reads every tab of a spreadsheet into a SpreadsheetSnapshot and can write a
tab back (used by the backlog engine to publish the unified backlog).

Auth: an OAuth token JSON with the spreadsheets + drive scopes. Point
PM_OS_GSPREAD_TOKEN at it (default: ~/.config/pm-os/google_token.json).
See README "Quickstart" for how to mint the token.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .base import Spreadsheet, SpreadsheetSnapshot

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _token_path() -> Path:
    raw = os.environ.get("PM_OS_GSPREAD_TOKEN", "~/.config/pm-os/google_token.json")
    return Path(raw).expanduser()


class GspreadSpreadsheet(Spreadsheet):
    def __init__(self, token_path: Optional[Path] = None):
        self._token_path = token_path or _token_path()
        self._client = None

    def _client_lazy(self):
        if self._client is not None:
            return self._client
        import gspread
        from google.oauth2.credentials import Credentials
        if not self._token_path.exists():
            raise SystemExit(f"[gspread] token not found at {self._token_path}")
        creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
        self._client = gspread.authorize(creds)
        return self._client

    def fetch_snapshot(self, sheet_id: str) -> SpreadsheetSnapshot:
        sh = self._client_lazy().open_by_key(sheet_id)
        tabs = {ws.title: ws.get_all_values() for ws in sh.worksheets()}
        return SpreadsheetSnapshot(sheet_id=sheet_id, name=sh.title, tabs=tabs)

    def write_tab(self, sheet_id: str, tab: str, rows: list[list], clear: bool = True) -> None:
        sh = self._client_lazy().open_by_key(sheet_id)
        try:
            ws = sh.worksheet(tab)
        except Exception:
            ws = sh.add_worksheet(title=tab, rows=max(100, len(rows) + 10), cols=26)
        if clear:
            ws.clear()
        ws.update(rows, value_input_option="USER_ENTERED")
