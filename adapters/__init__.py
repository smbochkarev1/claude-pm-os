"""PM OS adapters — vendor integrations behind the base interfaces.

Working, ready-to-use:
  llm.HttpLLM                 provider-agnostic chat completion (Anthropic/OpenAI)
  notifier_telegram.Telegram  Telegram Bot API delivery + chat formatters
  spreadsheet_gspread.Gspread  Google Sheets read/write via gspread

Interfaces to implement for your stack: see adapters/stubs/.
"""
