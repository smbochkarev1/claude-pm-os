"""STUB: task tracker adapter.

Implement `fetch_tasks` for your tracker (Jira, Linear, GitHub Issues, Asana,
Tracker, ClickUp, ...). Translate the vendor payload into `Task` records.

Guidance:
  - `me` is the caller's handle/login. Return tasks where they are assignee,
    author or follower (honor the `roles` filter when your API supports it).
  - `since` filters by last-updated. `queues` optionally scopes to
    projects/boards. `limit` caps the result.
  - Set `Task.status` to the RAW source status; the backlog engine normalizes
    it via config. Set `updated_at` (tz-aware) so the classifier can tell
    "touched today" from "stale".
  - Never raise on transient errors during a scheduled run — log and return
    what you have; a partial pull beats a crashed worker.

Example skeletons:
  Jira    GET /rest/api/3/search?jql=assignee=currentUser() AND updated>=-1d
  Linear  GraphQL issues(filter:{ assignee:{ isMe:true }, updatedAt:{ gte } })
  GitHub  GET /issues?filter=assigned&since=...
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..base import Task, TaskTracker


class MyTaskTracker(TaskTracker):
    def fetch_tasks(
        self,
        me: str,
        since: Optional[datetime] = None,
        roles: Optional[list[str]] = None,
        queues: Optional[list[str]] = None,
        limit: int = 500,
    ) -> list[Task]:
        raise NotImplementedError(
            "Implement fetch_tasks for your tracker. "
            "Map each issue to adapters.base.Task."
        )
