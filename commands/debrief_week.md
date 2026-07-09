# /debrief_week — weekly summary

You are a PM/PdM assistant. Aggregate the past working week's debriefs (Mon–Fri).
No external sources — read local debriefs only.

Repo: `$PM_OS_HOME`. This is a thin wrapper over `core/weekly_engine.py`, which
does the deterministic aggregation; you handle wording and delivery.

## Step 1 — Period

Read `$PM_OS_HOME/config/pm-os.config.yaml`; `TODAY` in `me.timezone`.
Compute the past working week: `WEEK_MON` (this or last week's Monday; if TODAY
is Monday, take the previous week) through `WEEK_FRI`. Honor an explicit period
in the request (e.g. "this week", "2026-W20").

## Step 2 — Read debriefs

For each date in range read `$PM_OS_HOME/debriefs/<date>.md` (only up to
`## Source detail`). Missing files = skipped days. If none exist:
> No debriefs for {WEEK_MON}–{WEEK_FRI}. Run `/debrief` every evening!

## Step 3 — Aggregate

`core/weekly_engine.aggregate_week` gives you: achievements (deduped
`done_today`), chronic items (`owed`/`waiting` on 2+ days), decisions taken,
recurring risks (2+ days), and patterns (someone stuck in waiting → escalation;
an item stuck in owed → prioritization).

## Step 4 — Write the file

`$PM_OS_HOME/debriefs/week-<ISO_YEAR>-W<NN>.md` — use
`weekly_engine.render_weekly_md` as the template (Closed / Chronic / Decisions /
Recurring risks / Patterns / Next week).

## Step 5 — Deliver

If `output.delivery == "notifier"`:
```
python "$PM_OS_HOME/scripts/send.py" --file "$PM_OS_HOME/debriefs/week-<YYYY-WNN>.md"
```

## Step 6 — Show in chat

Print the full `week-*.md`. Close:
> Weekly debrief saved to `debriefs/week-<ISO_WEEK>.md` [and delivered].
