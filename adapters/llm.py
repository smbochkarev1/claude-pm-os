"""LLM adapter — provider-agnostic chat completion over plain urllib.

Supports Anthropic-style and OpenAI-style HTTP APIs. Which one, the base URL,
the API key and the default model all come from environment variables so the
same code works against the public Anthropic/OpenAI endpoints or any
compatible gateway/proxy.

Environment:
  PM_OS_LLM_PROVIDER   "anthropic" (default) | "openai"
  PM_OS_LLM_API_KEY    API key
  PM_OS_LLM_BASE_URL   override endpoint (default: provider's public API)
  PM_OS_LLM_MODEL      default model id

No SDK dependency on purpose — one file, stdlib only, easy to audit.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from .base import LLM

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class LLMError(RuntimeError):
    pass


class HttpLLM(LLM):
    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
    ):
        self.provider = (provider or os.environ.get("PM_OS_LLM_PROVIDER", "anthropic")).lower()
        self.api_key = api_key or os.environ.get("PM_OS_LLM_API_KEY", "")
        self.base_url = (base_url or os.environ.get("PM_OS_LLM_BASE_URL", "")).rstrip("/")
        self.model = model or os.environ.get("PM_OS_LLM_MODEL", "")
        self.timeout = timeout
        if not self.base_url:
            self.base_url = (
                "https://api.anthropic.com"
                if self.provider == "anthropic"
                else "https://api.openai.com"
            )
        if not self.model:
            self.model = (
                DEFAULT_ANTHROPIC_MODEL
                if self.provider == "anthropic"
                else DEFAULT_OPENAI_MODEL
            )

    def complete(self, prompt: str, max_tokens: int = 4096, model: Optional[str] = None) -> str:
        if not self.api_key:
            raise LLMError("PM_OS_LLM_API_KEY is not set")
        model = model or self.model

        if self.provider == "anthropic":
            url = f"{self.base_url}/v1/messages"
            payload = json.dumps({
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        else:
            url = f"{self.base_url}/v1/chat/completions"
            payload = json.dumps({
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            }

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
        except urllib.error.URLError as e:
            raise LLMError(f"connection error: {e.reason}")

        if self.provider == "anthropic":
            return data["content"][0]["text"]
        return data["choices"][0]["message"]["content"]


def default_llm() -> HttpLLM:
    """Build an LLM from the PM_OS_LLM_* environment variables."""
    return HttpLLM()
