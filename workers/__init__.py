"""Scheduled workers — run headless via launchd/cron.

  midnight.py           23:00 fallback: build today's debrief if none exists
  transcript_poller.py  every 15 min: fetch ready transcripts, send follow-ups
  metrics_watch.py      periodic: metric digest + freshness watchdog alarm
"""
