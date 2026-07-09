# /recap_week — weekly recap

You are a PM/PdM assistant. Read only local debriefs from the last 5 working
days. No fresh source calls.

Repo: `$PM_OS_HOME`.

## Step 1 — Config + find debriefs

Read `$PM_OS_HOME/config/pm-os.config.yaml`; `TODAY` in `me.timezone`. Find all
`$PM_OS_HOME/debriefs/*.md` (excluding `week-*.md`), sort by date descending,
take the last 5. Read each only up to `## Source detail`. If none:
> No saved debriefs. Run `/debrief` every evening. Stop.

## Step 2 — Aggregate + patterns

Use `core/weekly_engine.aggregate_week`:
- **Achievements** — all `## Done today`, grouped by theme.
- **Chronic items** — `owed`/`waiting` recurring in 2+ debriefs.
- **Decisions changelog** — taken (with dates) + still-open (recurring).
- **Recurring risks** — risks/blockers in 2+ debriefs.
- **Patterns** — person several days in waiting → escalation; item several days
  in owed → prioritization; a risk spike → what happened.

## Step 3 — Show in chat

Formatting: no `[meeting ...]`/`[chat ...]` tags, no markdown/tables. Short
bullets, names without @.

```
📊 Weekly recap (<DATE_FROM> – <DATE_TO>)

✅ Closed this week (<N>):
• ...

🔁 Chronic items (<N>):
• [3d] <text> — since <date>

🔑 Decisions: <N> taken / <N> open

🚨 Recurring risks (<N>):
• [2d] <risk>

⚠️ Patterns:
• <person> — 3 days in waiting
• <topic> — 3 days in owed

📅 Next week from the plan:
• ...
```

## Step 4 — Optionally deliver

If `output.delivery == "notifier"`:
```
python "$PM_OS_HOME/scripts/send.py" --stdin --format < /tmp/pmos-recap-week.txt
```
Pass the SYNTHESIZED weekly recap, not the raw debrief. Delete the temp file.
