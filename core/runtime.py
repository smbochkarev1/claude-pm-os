"""Runtime glue: load config and instantiate adapters from config strings.

Config names an adapter as "module.path:ClassName"; this resolves and
instantiates it, so the engines/workers never hard-code a vendor. Env-var
placeholders of the form ${VAR} inside YAML string values are expanded from the
environment, keeping ids/tokens out of the committed config.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_config(path: Optional[str] = None) -> dict:
    """Load a YAML config with ${ENV} expansion.

    Default: config/pm-os.config.yaml, falling back to the .example if the real
    one is missing (handy for a first dry run).
    """
    import yaml
    if path is None:
        real = ROOT / "config" / "pm-os.config.yaml"
        path = real if real.exists() else ROOT / "config" / "pm-os.config.example.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return _expand(cfg)


def load_adapter(spec: str) -> Any:
    """Instantiate an adapter from a "module.path:ClassName" spec."""
    if ":" not in spec:
        raise ValueError(f"adapter spec must be 'module:Class', got {spec!r}")
    module_name, class_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)()
