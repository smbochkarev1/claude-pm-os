# SPEC — claude-pm-os architecture & design

This document explains how the PM OS is put together and why. The README is the
pitch; this is the reference for anyone extending it (including your Claude Code).

## 1. Layers

```
commands/  (Claude-driven playbooks)  ── orchestrate a run, own wording & delivery
   │
core/      (pure engines)             ── classify, dedup, aggregate, extract
   │  depends only on ▼
adapters/base.py  (interfaces + dataclasses)
   ▲  implemented by
adapters/  (vendor code)              ── translate a vendor payload ↔ canonical
```

Two hard rules keep this honest:

1. **Engines never import a vendor SDK.** They import `adapters.base` and the
   canonical dataclasses only. This is what makes them unit-testable offline and
   reusable across stacks.
2. **Identity and secrets never live in code or committed config.** They come
   from `.env` and the git-ignored `config/*.yaml`. `scripts/build_dist.sh`
   enforces it.

## 2. Canonical model (`adapters/base.py`)

Every source is reduced to a handful of dataclasses — `Task`, `CalendarEvent`,
`ChatMessage`, `Transcript`, `SpreadsheetSnapshot`, `MetricPoint`. Adapters map
vendor payloads INTO these; engines only ever see these. Adding a source type
means adding a dataclass + interface here, then one adapter.

Interfaces: `TaskTracker`, `Calendar`, `Spreadsheet`, `ChatSource`,
`TranscriptSource`, `MetricsAdapter`, `Notifier`, `LLM`.

## 3. Adapters

Shipped working:

- `adapters/llm.py::HttpLLM` — provider-agnostic chat completion over stdlib
  urllib. Anthropic- or OpenAI-shaped, endpoint/key/model from `PM_OS_LLM_*`.
- `adapters/notifier_telegram.py::TelegramNotifier` — Telegram Bot API over
  HTTPS (works on restrictive networks), 4096-char chunking, 429 retry, plus the
  markdown→chat formatters.
- `adapters/spreadsheet_gspread.py::GspreadSpreadsheet` — Google Sheets read/write
  via gspread + OAuth.
- `adapters/calendar_google.py::GoogleCalendar` — Google Calendar events via the
  Calendar v3 API + google-auth (OAuth user token or service account, scope
  `calendar.readonly`). Handles pagination, all-day vs timed, tz-aware datetimes,
  attendee mapping, and extracts a Zoom meeting number off the event's conference
  data so `meeting → follow-up` chains through to the Zoom adapter.
- `adapters/transcript_zoom.py::ZoomTranscript` — Zoom meeting transcripts via
  Server-to-Server OAuth: mints a bearer, finds the `TRANSCRIPT` (VTT) recording
  file, downloads and parses it to clean speaker text. Returns None (retry-later)
  when the transcript isn't ready.

The pure transform functions of the last two (`parse_event`/`parse_events` and
`parse_vtt`) are network-free and covered by `tests/test_adapters.py`; the
HTTP/auth plumbing is thin and lazily-imported so the parse tests run with no
credentials.

Stubs (interface + implementation guidance) under `adapters/stubs/`:
`task_tracker.py`, `calendar.py` (Outlook/CalDAV), `chat_source.py`,
`transcript.py` (Meet/Teams). Copy one, keep the class name, implement the one
abstract method for your tool.

Adapters are named in config as `"module.path:ClassName"` and instantiated by
`core/runtime.py::load_adapter`, so no engine or worker hard-codes a vendor.

## 4. Core engines

### 4.1 classifier (`core/classifier.py`)
Two layers. `classify_by_signals` is a deterministic keyword classifier over the
six buckets, driven by the `signals` config — no network, a graceful degraded
mode, and the thing the eval harness scores. `classify_with_llm` is the
production path: it renders `prompts/classify.md` and calls the LLM adapter for a
traced, refined debrief. Ownership ambiguity (owed-by-me vs waiting-on-others) is
resolved by message authorship (`from_me`) when available. `parse_debrief_buckets`
reads a debrief `.md` back into buckets (used by the weekly engine and evals).

### 4.2 backlog_engine (`core/backlog_engine.py`)
`normalize -> merge -> dedup -> sort`. Source dirt (header offsets, column maps,
status aliases, stream dictionaries) lives entirely in
`config/backlog_sources.yaml`; the engine is a pure transform. Dedup primary key
is the ticket id, falling back to normalized `title + stream`; merges fold
non-empty fields and union the source provenance. Sort is stream order →
priority → deadline → title, then it stamps `BL-NNN` ids.

### 4.3 weekly_engine (`core/weekly_engine.py`)
Reads a set of daily debrief files and derives achievements, chronic items
(repeating on 2+ days via fuzzy grouping), a decisions changelog, recurring
risks, and patterns. Fully deterministic.

### 4.4 followup_engine (`core/followup_engine.py`)
Given a `Transcript`, builds `prompts/followup.md`, calls the LLM, parses the
JSON (with one repair retry), and renders a compact follow-up. Owner attribution
is the crux: each item is owned by whoever spoke the commitment, enforced by the
prompt and a speaker table, `null` when unknown rather than guessed.

## 5. Workers (`workers/`)

- `midnight.py` — 23:00 fallback: if today's debrief is missing, collect sources,
  classify (LLM, or a raw dump when no key), write the file, deliver a summary.
- `transcript_poller.py` — every ~15 min: a durable retry queue
  (`cache/transcript_pending.json`). Finished meetings are enqueued; each poll
  fetches ready transcripts, extracts + delivers follow-ups, drops meetings whose
  transcript never appears within `retry_hours`. A missed poll never loses a
  follow-up.
- `metrics_watch.py` — periodic digest + freshness watchdog. Alarms the notifier
  when a metric breaches its threshold in the bad direction, or when its data is
  stale beyond `PM_OS_METRICS_FRESHNESS_MIN` (a dashboard that silently stops
  updating is its own incident). The team-facing touchpoint.
- `build_backlog.py` — CLI over `backlog_engine`: load/reuse snapshots, fold in
  tracker + debrief-owed, dedup/sort, publish.

`workers/launchd/*.plist.template` schedule these on macOS; `${PM_OS_HOME}` and
env placeholders are filled in at install time. On Linux, the equivalent cron
lines are one-liners against the same scripts.

## 6. Commands (`commands/`)

Markdown playbooks Claude Code executes: `/debrief`, `/recap`, `/backlog`,
`/debrief_week`, `/recap_week`, `/debrief-backlog`. They own the human-facing
wording, the "ask the user for notes" step, source-freshness handling, and
delivery; they call the engines/workers for the deterministic heavy lifting.
Paths are rooted at `$PM_OS_HOME`.

## 7. Config & secrets

- `config/pm-os.config.yaml` — identity (`me`), which adapter backs each source,
  signals, output, context. `${ENV}` placeholders expand from the environment.
- `config/backlog_sources.yaml` — per-spreadsheet column maps, status/stream
  dictionaries, target sheet.
- `.env` — all tokens and ids. Git-ignored. `.env.example` documents every var.

## 8. Eval harness (`eval-harness/`)

Deterministic, offline, CI-friendly. Scores the six-bucket signal classifier
against golden labels and the backlog dedup against golden merged keys/counts,
printing a pass-rate and exiting non-zero on any regression. Grow it with a
fixture + golden pair each time you find a real miss.

`tests/` (pytest) complements it with unit tests for the working adapters'
transform logic — Google Calendar payload → `CalendarEvent`, Zoom VTT → clean
text — also offline and credential-free. CI runs the harness (`evals.yml`) and
pytest (`tests.yml`) on every push.

## 9. Meeting prep (pattern — extension point)

The follow-up engine handles what happens *after* a meeting. The symmetric
*before*-a-meeting brief is a natural extension and follows the same shape: for
an upcoming `CalendarEvent`, gather context through the existing adapters —
recent `Task`s touching the same stream, the last `ChatMessage`s with the
attendees, open owed/waiting items from recent debriefs, and relevant backlog
rows — then render a one-page pre-read via an externalized `prompts/premeet.md`
and deliver it through the notifier ahead of the meeting. It needs no new
interfaces, only a new engine (`core/premeet_engine.py`) plus a worker that
triggers N minutes before events flagged in the calendar. Left as a documented
extension so the shipped core stays focused.

## 10. Extending

1. New source → add a dataclass + interface in `adapters/base.py`, write one
   adapter, name it in config.
2. New tuning → edit `prompts/*.md` or the `signals`/dictionaries in config; no
   code change.
3. New quality bar → add fixtures + golden and a suite in `run_evals.py`.
