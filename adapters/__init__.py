"""PM OS adapters — vendor integrations behind the base interfaces.

Working, ready-to-use:
  llm.HttpLLM                    provider-agnostic chat completion (Anthropic/OpenAI)
  notifier_telegram.Telegram     Telegram Bot API delivery + chat formatters
  spreadsheet_gspread.Gspread    Google Sheets read/write via gspread
  calendar_google.GoogleCalendar Google Calendar events via Calendar v3 + google-auth
  transcript_zoom.ZoomTranscript Zoom meeting transcripts (S2S OAuth, VTT parse)

Interfaces to implement for your other tools: see adapters/stubs/.
"""
