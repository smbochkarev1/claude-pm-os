# /backlog — assemble the unified cross-source backlog (standalone)

You are a PM/PdM assistant. Assemble one status table of all tasks across
streams into the target spreadsheet defined in
`config/backlog_sources.yaml → target`.

Repo: `$PM_OS_HOME`. Engine: `core/backlog_engine.py` +
`workers/build_backlog.py` (config `config/backlog_sources.yaml`).
This command does NOT run a debrief. Combined run: `/debrief-backlog`.

## Step 1 — Fresh sheet snapshots (if needed)

The engine reads snapshots from `snapshots/sheets/<id>/<TODAY>.json` (written by
`/debrief`). If today's snapshots are missing, the Spreadsheet adapter fetches
live. Nothing to collect separately.

## Step 2 — Live tracker (recommended)

Pull live task status/owner/deadline via the tracker adapter for the ticket keys
in the backlog and for your open tickets. Serialize to `/tmp/tracker.json` in
the engine format:
```json
{
  "by_key": {"PROJ-101": {"status": "In progress", "assignee": "me", "deadline": "2026-07-01"}},
  "extra_tickets": [{"key": "PROJ-200", "summary": "...", "status": "Open", "assignee": "...", "stream": "Payments"}]
}
```
**If the tracker is unavailable** — skip it; the engine degrades to "ticket keys
as in the sheets" (links still built from keys), and records this in the sync
log. Never Silent-Fail.

## Step 3 — Run the engine

```
python "$PM_OS_HOME/workers/build_backlog.py" [--tracker-data /tmp/tracker.json]
```
Stages: normalize → tracker enrich → debrief enrich → dedup → sort → write
(tabs Backlog / Stream summary / Sync log). Add `--dry-run` to preview.

## Step 4 — Verify

- Sync log: source-by-source count reconciliation.
- Spot-check 5 tickets against the tracker (if live).
- Unmatched/ambiguous rows went to `context/open-questions.md`.
- Idempotence: a second `--dry-run` gives the same row count.

## Step 5 — Report

Total rows, per-stream breakdown and total effect (from Summary), what degraded/
was skipped, link to the sheet.
