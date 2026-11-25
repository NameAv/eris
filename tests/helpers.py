"""Shared bits for Eris's tests: fakes for the slow or outside parts (screen, brain,
voice, microphone) and a throwaway settings folder, so running the tests never touches
your real settings, memories or API key."""
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Throwaway home for settings (set before anything from eris is imported).
_home = tempfile.mkdtemp(prefix="eris-test-")
os.environ["APPDATA"] = _home
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home

# No audio hardware is needed for any test.
sys.modules.setdefault("sounddevice", types.ModuleType("sounddevice"))

from eris.protocol import Event, LineStream  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def done(title):
    """End of a test file: exit non-zero if anything failed (run_all reads that)."""
    print(f"{title}: {'all passed' if not FAILS else f'{len(FAILS)} failed'}")
    sys.exit(1 if FAILS else 0)


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ---------------- fakes ----------------
def fake_shot(elements=None, scale=2.0, w=1280, h=720):
    """A screenshot stand-in: image coords x2 = screen coords."""
    s = types.SimpleNamespace(left=0, top=0, width=int(w * scale), height=int(h * scale),
                              img_w=w, img_h=h, sx=scale, sy=scale, b64="", full=None,
                              elements=elements or [], app=None)
    s.to_screen = lambda b: tuple(int(v * scale) for v in b)
    return s


class FakeVoice:
    def __init__(self, log=None):
        self.said = []

    def say(self, text, force=False, voice=None):
        self.said.append(text)

    def stop(self):
        pass

    def ack(self):
        pass

    def busy(self):
        return False


class ScriptedBrain:
    """Plays back scripted replies, one list of events (or reply text) per turn."""

    def __init__(self, log=None):
        self.script, self.asked, self.history, self.notes = [], [], [], []
        self.moved = True       # the quick check's answer
        self.plan = None        # the next step planned early

    def snap(self):
        return 1

    def shot_width(self):
        return 1280

    def prewarm(self):
        pass

    def moved_on(self, shot, step):
        return self.moved

    def predict(self, shot):
        return self.plan

    def reset(self):
        self.history = []

    def turn(self, shot, text, on_event, alive, notes=""):
        self.asked.append(text)
        self.notes.append(notes)
        step = self.script.pop(0) if self.script else []
        if isinstance(step, str):
            step = LineStream().feed(step + "\n")
        for ev in step:
            if ev == "PAUSE":
                self.gate.wait(2)
                continue
            on_event(ev)


class FakeUI:
    def __init__(self):
        self.cmds, self.logs = [], []

    def cmd(self, *a):
        self.cmds.append(a)

    def log(self, *a):
        self.logs.append(a)

    def window_rects(self):
        return []


def make_eris(shot=None):
    """An Eris with every outside part faked: scripted brain, silent voice, fake screen."""
    import eris.core as core
    core.Voice = FakeVoice
    core.Brain = ScriptedBrain
    core.beep = lambda *a: None
    core.Eris.load_ears = lambda self: None
    core.privacy.should_look_away = lambda: ""
    the_shot = shot or fake_shot()
    core.Eris._shoot = lambda self: the_shot
    core.Watcher.look = lambda self: None          # no before/after check unless a test wants one
    core.config.SETTLE_DELAY = 0.05
    ui = FakeUI()
    e = core.Eris(ui)
    return e, ui, the_shot


__all__ = ["Event", "LineStream", "check", "done", "wait_for", "fake_shot", "FakeVoice",
           "ScriptedBrain", "FakeUI", "make_eris", "ROOT"]
