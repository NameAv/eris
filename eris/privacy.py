"""Keeping private things private.

- While you're typing into a password, email, card or code field, Eris looks
  away: no screenshots at all until you've left that field.
- Password / email / card fields elsewhere on screen are blacked out in every
  screenshot before it leaves your PC.
- Password managers (and any app you add in Settings) are never looked at.
- The keyboard hook only ever keeps Eris's own hotkeys and Enter; every other
  key is dropped immediately and never stored.

Field detection uses the same Windows accessibility info screen readers use.
Apps that draw their own password boxes can't be detected that way, which is
what the blocklist and the Active switch are for.
"""
import sys
import time

from . import config


def foreground_title():
    """Title of the app in front (ignoring Eris's own windows)."""
    from . import apps
    win = apps.front_window()
    return win["title"] if win else ""


def blocked_app():
    """Name of a blocked app in front, or ''."""
    title = foreground_title().lower()
    for name in config.PRIVATE_APPS:
        if name.strip() and name.strip().lower() in title:
            return name.strip()
    return ""


_focus_cache = (0.0, False)


def typing_secret():
    """True while the focused field is a password/email/card/code field."""
    global _focus_cache
    if sys.platform != "win32" or not config.PRIVACY:
        return False
    t, val = _focus_cache
    if time.time() - t < 0.4:
        return val
    try:
        from . import uia
        answer = uia.get("privacy").focus_is_sensitive()
    except Exception:
        answer = None
    if answer is not None:     # no answer in time: keep the last known one, don't assume "safe"
        val = bool(answer)
    _focus_cache = (time.time(), val)
    return val


def should_look_away():
    """Reason to take no screenshot right now, or ''."""
    if not config.PRIVACY:
        return ""
    app = blocked_app()
    if app:
        return f"{app} is private"
    if typing_secret():
        return "you're typing something private"
    return ""


_fields_cache = (0.0, "", [])


def hidden_fields():
    """Screen rects to black out (password/email/card fields), [] if none or unknown.
    Cached for 2 seconds per window: asking Windows about a big web page can be slow."""
    global _fields_cache
    if sys.platform != "win32" or not config.PRIVACY:
        return []
    title = foreground_title()
    t, cached_title, rects = _fields_cache
    if title == cached_title and time.time() - t < 2:
        return rects
    try:
        from . import uia
        found = uia.get("privacy").sensitive_rects()
    except Exception:
        found = None
    if found is None:      # Windows didn't answer in time: don't cache a guess
        return []
    _fields_cache = (time.time(), title, found)
    return found
