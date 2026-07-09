# /debrief — end-of-day summary of the working day

You are a PM/PdM assistant. Follow the steps in order. Report progress briefly
after each step.

The repo lives at `$PM_OS_HOME`. All paths below are relative to it.

---

## Step 0 — Model

`/debrief` is a heavy task (many source calls + long classification). Once, at
the start, remind the user to use a strong model (config `llm.heavy_commands`).
If a model call fails on quota/rate limit — do not retry; offer to wait and wait
for "continue".

---

## Step 1 — Read config, check working day

Read `$PM_OS_HOME/config/pm-os.config.yaml`. Note `me.*`, `sources.*`,
`signals.*`, `output.*`, `context.*`.

Determine `TODAY` in `me.timezone`. Verify:
1. `TODAY`'s weekday is in `me.working_days`.
2. `TODAY` is not in `me.holidays_file`.

If it is a weekend or holiday, tell the user and stop:
> Today ({TODAY}) is a non-working day. No debrief needed. Enjoy the break!

---

## Step 1b — PM context (if enabled)

If `context.enabled == true`: read `context.index_path` (cap at
`context.max_index_chars`). Use it for stakeholders/@handles, glossary terms,
and deadlines. Don't mark as owed anything the index marks closed. When unsure
whose track/chat something is, mark `[needs context]` — don't guess.

---

## Step 2 — Ask the user for notes

Ask, in one block:
> **Ready for the debrief ({TODAY}).**
> Anything to add before I collect? Thoughts, promises, plans, things you forgot
> to log — all in one message. Reply "no" or "/" to skip.

Wait. On "no"/"/"/"skip" continue without notes; otherwise save the full text as
`USER_NOTES`.

---

## Step 3 — Collect sources (via adapters)

Pull today's data through the configured adapters (`sources.*`). Each is
best-effort — if one is unavailable, record it and continue (Never Silent-Fail:
surface what's missing, don't drop it silently).

- **Tracker** (`sources.tracker.adapter`): tasks where `me.name` is
  assignee/author/follower, updated since `DAY_START`. Capture key, title,
  status transition, my comments today, mentions of me.
- **Calendar** (`sources.calendar.adapter`): today's events. For events
  `duration >= sources.calendar.min_duration_minutes`, try the transcript
  adapter; if not ready mark `transcript_pending`.
- **Chat** (`sources.chat.adapter`): active chats in the last
  `sources.chat.activity_hours`, capped at `max_messages_per_chat`. Keep
  `from_me` so ownership is clear.
- **Sheets** (`sources.sheets.adapter`): snapshot each configured spreadsheet to
  `$PM_OS_HOME/snapshots/sheets/<id>/<TODAY>.json`; diff vs yesterday
  (added/removed/changed by row content-hash).

---

## Step 4 — Merge context

Assemble one structured context: `USER_NOTES` + tracker + chat + calendar/
transcripts + sheet diffs.

---

## Step 5 — Classify into six buckets

Using `signals.*` and semantics, bin every fact (see `prompts/classify.md` for
the full rubric): **done_today, owed_by_me, waiting_on_others, decisions
(taken/open), risks_blockers, planned_after_today**.

**USER_NOTES:** keep raw text verbatim under `## My notes (raw input)`; then
distribute line-by-line tagged `[my note]`; unrecognized lines →
`## Unclassified notes`.

**Traceability (mandatory):** every bullet carries an inline source tag —
`[PROJ-123]`, `[chat / "Name" / msg HH:MM]`, `[meeting <id>, HH:MM]`,
`[sheet <name> / "<tab>" / <cell>]`, `[my note]`.

---

## Step 6 — Write the debrief file

Create/overwrite `$PM_OS_HOME/debriefs/<TODAY>.md`:

```markdown
---
date: <TODAY>
generated_at: <NOW ISO8601>
sources:
  tracker_tasks: <N>
  chats: <N>
  meeting_transcripts: <N>
  meetings_pending_transcript: <N>
  sheets_snapshotted: <N>
buckets:
  done_today: <N>
  owed_by_me: <N>
  waiting_on_others: <N>
  decisions_taken: <N>
  decisions_open: <N>
  risks_blockers: <N>
  planned_after_today: <N>
---

## My notes (raw input)
> <verbatim USER_NOTES or "(none)">

## Done today
- <bucket 1 with tags>

## Owed by me — not done today
- <bucket 2 with tags>

## Waiting on others
- <bucket 3 with tags>

## Decisions
### Taken today
- <decisions made>

### Open / awaiting
- <open decisions>

## Risks & blockers
- <bucket 5 with tags>

## Planned (after today)
- <bucket 6 with tags>

## Unclassified notes
- <unrecognized USER_NOTES or "(none)">

---
## Source detail

### Tracker (<N> tasks)
<key — title — status — what changed>

### Chat (<N> chats)
<chat — short digest>

### Meetings (<N>)
<id — title — duration — transcript status>

### Sheets diff
<per sheet: added / removed / changed, or "baseline">
```

---

## Step 7 — Deliver

If `output.delivery == "notifier"`:

```
python "$PM_OS_HOME/scripts/send.py" --file "$PM_OS_HOME/debriefs/<TODAY>.md"
```

Send only the summary (no `## Source detail`).

---

## Step 8 — Show in chat

If `output.show_full_summary_in_chat`, print the file (all sections except
`## Source detail`, which you summarize in one line). Close with:
> Debrief saved to `debriefs/<TODAY>.md` [and delivered].
