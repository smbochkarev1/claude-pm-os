# /debrief-backlog — debrief + backlog refresh in one command

Orchestrator: runs the full `/debrief`, then builds the unified backlog,
**reusing** the data already collected (sheet snapshots + tracker + today's
debrief) without re-fetching.

Repo: `$PM_OS_HOME`.

## Step A — Debrief
Run the entire `/debrief` flow (see `commands/debrief.md`) to the end: collect
sources, classify, write `debriefs/<TODAY>.md`, deliver. Along the way today's
sheet snapshots land in `snapshots/sheets/<id>/<TODAY>.json`, and the tracker
data is pulled — **keep it**.

## Step B — Tracker data for the engine
Serialize the tracker data from Step A to `/tmp/tracker.json` in the engine
format (`by_key` + `extra_tickets`, see `commands/backlog.md` Step 2) so the
engine doesn't hit the tracker twice. If the tracker didn't load — skip
(degraded).

## Step C — Run the engine (reuse)
```
python "$PM_OS_HOME/workers/build_backlog.py" --from-debrief "$PM_OS_HOME/debriefs/<TODAY>.md" [--tracker-data /tmp/tracker.json]
```
`--from-debrief` reuses today's snapshots (no re-fetch); debrief-enrich reads the
fresh `debriefs/<TODAY>.md`.

## Step D — Verify + report
As in `/backlog` Steps 4–5: count reconciliation, spot-check, open-questions,
link to the sheet. Report both parts — what's in the debrief and what changed in
the backlog.
