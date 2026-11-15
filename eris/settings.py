"""Saves your settings (API key, keys, voice...) so you set them once."""
import json
import os
import sys
from pathlib import Path

from . import config

SAVED = ["BRAIN", "LOCAL_MODEL", "VOICE_ENGINE", "VOICE_NAME", "API_KEY", "EFFORT", "FAST_MODE", "VOICE_ON", "VOICE_RATE", "WHISPER_MODEL",
         "TALK_KEY", "NEXT_KEY", "CANCEL_KEY", "BOX_TIMEOUT", "PANEL_ON_TOP", "WATCH", "REFINE"]


def folder() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    p = Path(base) / "Eris" if base else Path.home() / ".eris"
    p.mkdir(parents=True, exist_ok=True)
    return p


FILE = folder() / "settings.json"


def load():
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return
    for k in SAVED:
        if k in data:
            setattr(config, k, data[k])


def save():
    FILE.write_text(json.dumps({k: getattr(config, k) for k in SAVED}, indent=2))


def api_key():
    return config.API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
