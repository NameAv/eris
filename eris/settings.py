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


# ---------- Eris's own memory and profile picture ----------
MEMORY = folder() / "memory.json"
AVATAR = folder() / "avatar.png"


def memories():
    try:
        return [m for m in json.loads(MEMORY.read_text()) if isinstance(m, str)]
    except (OSError, ValueError):
        return []


def remember(fact):
    fact = " ".join(fact.split())[:200]
    if not fact:
        return
    mems = [m for m in memories() if m.lower() != fact.lower()]
    mems.append(fact)
    MEMORY.write_text(json.dumps(mems[-40:], indent=2))


def forget_all():
    for f in (MEMORY, AVATAR):
        try:
            f.unlink()
        except OSError:
            pass
