"""STUB: chat source adapter.

Implement `fetch_messages` for your messenger (Slack, Telegram, Teams, ...).
Translate messages into `ChatMessage` records.

Guidance:
  - Return messages from active chats within the `since` window, capped at
    `max_per_chat`. Pre-filter to messages that mention `me`, are authored by
    `me`, or land in direct/named chats — the classifier works best on signal,
    not the full firehose.
  - Set `from_me` correctly: the classifier uses it to separate "I promised"
    (owed_by_me) from "they promised me" (waiting_on_others).

Example skeletons:
  Slack     conversations.history per channel, filter by ts and mentions
  Telegram  MTProto get_dialogs -> get_history (user client), or Bot getUpdates
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..base import ChatMessage, ChatSource


class MyChatSource(ChatSource):
    def fetch_messages(
        self,
        me: str,
        since: Optional[datetime] = None,
        max_per_chat: int = 50,
    ) -> list[ChatMessage]:
        raise NotImplementedError(
            "Implement fetch_messages for your messenger. "
            "Map each message to adapters.base.ChatMessage."
        )
