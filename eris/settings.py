"""Saves your settings (API key, keys, voice...) so you set them once."""
import json
import os
import sys
from pathlib import Path

from . import config

SAVED = ["BRAIN", "LOCAL_MODEL", "VOICE_ENGINE", "VOICE_NAME", "API_KEY", "EFFORT", "FAST_MODE", "VOICE_ON", "VOICE_RATE", "WHISPER_MODEL",
         "TALK_KEY", "NEXT_KEY", "CANCEL_KEY", "BOX_TIMEOUT", "PANEL_ON_TOP", "WATCH", "REFINE", "PRIVACY", "PRIVATE_APPS", "ACK", "BOX_STYLE", "VIBE", "USER_NAME", "UPDATES", "ELEMENTS", "OCR", "TRACK", "BOX_IN_RECORDINGS"]


def folder() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    p = Path(base) / "Eris" if base else Path.home() / ".eris"
    p.mkdir(parents=True, exist_ok=True)
    return p


FILE = folder() / "settings.json"
DEFAULTS = {k: (list(v) if isinstance(v, list) else v)
            for k, v in ((k, getattr(config, k)) for k in SAVED)}   # before any load()


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows' own encryption for secrets, tied to your Windows login: the result only
    decrypts as you, on this PC."""
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    desc = "Eris API key" if protect else None
    if not fn(ctypes.byref(blob_in), desc, None, None, None, 0x1, ctypes.byref(blob_out)):
        raise OSError("Windows couldn't protect/unprotect the key")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _protect_key(key):
    import base64
    return base64.b64encode(_dpapi(key.encode(), True)).decode()


def _unprotect_key(text):
    import base64
    return _dpapi(base64.b64decode(text), False).decode()


def load():
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return
    for k in SAVED:
        if k in data:
            setattr(config, k, data[k])
    if data.get("API_KEY_PROTECTED"):
        try:
            config.API_KEY = _unprotect_key(data["API_KEY_PROTECTED"])
        except Exception:
            config.API_KEY = ""   # e.g. the file was copied from another PC: re-enter the key
    elif data.get("API_KEY") and sys.platform == "win32":
        save()   # an older Eris stored the key as plain text: encrypt it now


def save():
    data = {k: getattr(config, k) for k in SAVED}
    if sys.platform == "win32" and config.API_KEY:
        try:   # never store the key as plain text
            data["API_KEY_PROTECTED"] = _protect_key(config.API_KEY)
            data["API_KEY"] = ""
        except Exception:
            pass
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, FILE)


def reset_all(keep_key=True):
    """Back to how Eris came out of the box (keeps your API key unless told not to)."""
    key = config.API_KEY
    for k, v in DEFAULTS.items():
        setattr(config, k, list(v) if isinstance(v, list) else v)
    if keep_key:
        config.API_KEY = key
    save()


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


def forget(fact):
    MEMORY.write_text(json.dumps([m for m in memories() if m != fact], indent=2))


def forget_all():
    for f in (MEMORY, AVATAR):
        try:
            f.unlink()
        except OSError:
            pass
