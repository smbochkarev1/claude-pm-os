# /recap — morning recap of yesterday, focused on today

You are a PM/PdM assistant. The base is yesterday's debrief; **reconcile against
today's debrief if it already exists.** For the weekly view use `/recap_week`.

The repo lives at `$PM_OS_HOME`. All paths below are relative to it.

---

## Step 1 — Config

Read `$PM_OS_HOME/config/pm-os.config.yaml`. Note `me.timezone`, `output.*`,
`context.*`.

## Step 1b — PM context (if enabled)

Read `context.index_path` for deadlines, stakeholders, and "don't repeat what's
closed". A fresh ticket status beats stale debrief text.

## Step 2 — Find yesterday's debrief

`TODAY` in `me.timezone`; `YESTERDAY = TODAY - 1 day`. Read
`$PM_OS_HOME/debriefs/<YESTERDAY>.md`. If missing:
> No debrief for {YESTERDAY}. Run `/debrief` in the evening to build history.
Stop.

## Step 2b — Reconcile (mandatory)

If `$PM_OS_HOME/debriefs/<TODAY>.md` exists, read it and:
- Remove from the recap any yesterday `Owed by me` item already in today's
  `## Done today`.
- Use today's fresher wording for `Owed by me`, `Waiting on others`, and
  `Planned` rows dated `TODAY`.

If today's debrief doesn't exist, for tickets in Waiting/Risks pull the latest
comment via the tracker adapter and reflect it instead of stale wording. Do not
repeat closed items.

## Step 3 — Synthesize five blocks

- **Finish today** — everything in `## Owed by me`.
- **Whom to ping** — from `## Waiting on others`: due passed / due today / no
  update 2+ days (only if the ticket/chat has no fresh comment).
- **Open decisions** — all of `### Open / awaiting`.
- **Unresolved risks** — all of `## Risks & blockers`; flag those hitting today's
  deadlines.
- **From the plan for today** — `## Planned` rows dated `TODAY` or "soon".

## Step 4 — Show in chat

Formatting: no inline source tags, no markdown/tables. Each item = a short
phrase. Names via chat @handle (else login/full name). Empty block → `(none)`.

```
☀️ Recap for {YESTERDAY} → focus for today

📌 Finish today (<N>):
• ...

⏳ Whom to ping (<N>):
• ...

🔑 Open decisions (<N>):
• ...

🚨 Unresolved risks (<N>):
• ...

📅 From the plan for today (<N>):
• ...
```

## Step 5 — Deliver

If `output.delivery == "notifier"`, save the synthesized recap to a temp file
and send the SYNTHESIZED recap (not the raw debrief):

```
python "$PM_OS_HOME/scripts/send.py" --stdin --format < /tmp/pmos-recap.txt
```

Delete the temp file afterward.

## Step 6 — Close
> Recap for {YESTERDAY} ready [and delivered].
