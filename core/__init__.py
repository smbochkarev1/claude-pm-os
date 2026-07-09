"""PM OS core engines — pure, adapter-agnostic business logic.

  classifier       six-bucket debrief classification (signal layer + LLM layer)
  backlog_engine   cross-source normalize -> dedup -> prioritize
  weekly_engine    aggregate daily debriefs into a weekly digest
  followup_engine  post-meeting follow-up extraction

Engines depend only on adapters.base interfaces + dataclasses, never on a vendor.
"""
