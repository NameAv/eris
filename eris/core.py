"""Eris's step-by-step logic: listen, look, box, talk, wait, repeat.

Talks to the window only through ui.cmd(...) and ui.log(...), both thread-safe.
"""
import queue
import threading
import time
import traceback

from pynput import keyboard

from . import config, screen
from .brain import Brain
from .speech import Voice, beep
from .watcher import Watcher

WATCH_PROMPT = ("(Automatic look: my screen changed while you were waiting.) Here's my screen "
                "now. If the step is done, give the next step, or DONE if the task is finished. "
                "If I'm still partway through or nothing important changed, reply with just KEEP. "
                "If I did something different, briefly tell me and guide me back.")
MAX_LOOKS_PER_TASK = 30

NEXT_STEP_PROMPT = ("I did that step. Here's my screen now. Check it worked, then give the "
                    "next step, or DONE if the task is finished. If the screen is still loading, "
                    "reply with just KEEP and you'll get another look when it changes.")


class Eris:
    def __init__(self, ui):
        self.ui = ui
        self.voice = Voice(log=ui.log)
        self.brain = Brain(log=ui.log)
        self.ears = None
        self.active = True
        self.gen = 0            # bumps on every new turn; stale turns abort themselves
        self.box = None         # current box in screen coords
        self.waiting = None     # None | "click" | "next"
        self.caption = ""
        self.steps = 0
        self.talking = False
        self.lock = threading.Lock()
        self.inbox = queue.Queue()
        self._busy = 0
        self.mon = None          # monitor of the last screenshot (left, top, w, h)
        self.auto_looks = 0      # automatic looks since the last new instruction
        self.task_looks = 0      # automatic looks this task (safety cap)
        self.told_watch = False
        self.early_click = None  # gen of a box you clicked before she finished talking
        self.box_gen = None
        threading.Thread(target=self._input_worker, daemon=True).start()
        self.watcher = Watcher(self)
        self.load_ears()

    # ---------- speech model ----------
    def load_ears(self):
        self.ears = None
        threading.Thread(target=self._load_ears, daemon=True).start()

    def _load_ears(self):
        try:
            self.ui.log("info", f"Loading speech model ({config.WHISPER_MODEL})... "
                        "first time downloads it, give it a minute.")
            from .ears import Ears
            self.ears = Ears()
            self.ui.log("info", f"Ready! Hold {config.TALK_KEY.upper()} (or the mic button) "
                        "and ask me how to do something.")
            self.ui.cmd("state", "ready")
        except Exception as e:
            self.ui.log("error", f"Microphone/speech model not available: {e}\n"
                        "You can still type questions.")
            self.ui.cmd("state", "ready")

    # ---------- state ----------
    def _new_gen(self):
        with self.lock:
            self.gen += 1
            return self.gen

    def _clear(self):
        self.box = None
        self.waiting = None
        self.ui.cmd("clear_box")

    def cancel(self):
        self._new_gen()
        self.voice.stop()
        self._clear()
        self.ui.cmd("status", "")
        self.ui.cmd("state", "ready")
        self.steps = 0

    def new_task(self):
        self.cancel()
        self.brain.reset()
        self.ui.log("info", "Fresh start. What are we doing?")

    def set_active(self, on):
        self.active = on
        if not on:
            self.cancel()
            self.ui.cmd("state", "off")
        else:
            self.ui.cmd("state", "ready")

    # ---------- asking ----------
    def ask(self, text):
        if not self.active:
            self.set_active(True)
            self.ui.cmd("active", True)
        self.ui.log("you", text)
        self.voice.stop()
        self._clear()
        self.steps = 0
        self.auto_looks = self.task_looks = 0
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, text), daemon=True).start()

    def advance(self):
        """Step finished (click in box or Next): box goes away NOW, then look again."""
        if not self.waiting:
            return
        self.voice.stop()
        self._clear()
        self.steps += 1
        self.auto_looks = 0
        my = self._new_gen()
        if self.steps >= config.MAX_STEPS:
            msg = "That's a lot of steps, let's pause here. Ask me again if you're stuck."
            self.ui.log("eris", msg)
            self.voice.say(msg)
            return

        def later():
            time.sleep(config.SETTLE_DELAY)   # let menus/panels open first
            if my == self.gen:
                self._turn_safe(my, NEXT_STEP_PROMPT)
        threading.Thread(target=later, daemon=True).start()

    def auto_look(self):
        """Called by the watcher when the screen changed while waiting."""
        if not (self.active and self.waiting) or self.busy:
            return
        if self.task_looks >= MAX_LOOKS_PER_TASK:
            return
        self.auto_looks += 1
        self.task_looks += 1
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, WATCH_PROMPT, True), daemon=True).start()

    @property
    def busy(self):
        return self._busy > 0

    def _turn_safe(self, my, text, soft=False):
        with self.lock:
            self._busy += 1
        try:
            self._turn(my, text, soft)
        except Exception as e:
            self.ui.log("error", f"Something broke: {e}")
            self.ui.log("debug", traceback.format_exc())
            self.ui.cmd("status", "")
            self.ui.cmd("state", "ready")
        finally:
            with self.lock:
                self._busy -= 1

    def _turn(self, my, text, soft=False):
        """One step. soft=True is an automatic look: the current box stays up
        unless the brain has something new to say (it can reply KEEP)."""
        alive = lambda: my == self.gen
        if not soft:
            self.ui.cmd("status", "Looking...")
            self.ui.cmd("state", "thinking")
        shot = screen.grab(snap=self.brain.snap())
        if not alive():
            return
        self.mon = (shot.left, shot.top, shot.width, shot.height)
        self.ui.cmd("monitor", *self.mon)
        st = {"ended": False, "first": True, "kept": False, "caption": ""}

        def on_event(ev):
            if not alive() or st["kept"]:
                return
            if ev.kind == "fail":
                if soft:   # a hiccup during an automatic look: just keep waiting
                    self.ui.log("debug", f"automatic look failed: {ev.value}")
                    st["kept"] = True
                    return
                self._clear()
                self.ui.log("error", ev.value)
                self.voice.say(ev.value)
                self.ui.cmd("state", "ready")
                st["ended"] = True
                return
            if st["first"]:
                st["first"] = False
                if ev.kind == "keep":
                    st["kept"] = True
                    return
                if soft:   # she has something new: drop the old step
                    self.waiting = None
                    self.auto_looks = 0
                    self.voice.stop()
                    if ev.kind != "box":
                        self._clear()
            if ev.kind == "box":
                self.box = shot.to_screen(ev.value)
                self.box_gen = my
                self.early_click = None
                self.ui.cmd("box", *self.box, "")
            elif ev.kind == "nobox":
                self._clear()
            elif ev.kind == "type":
                st["caption"] = f"Type:   {ev.value}"
                self.ui.cmd("caption", st["caption"])
                self.ui.log("hint", f"Type:  {ev.value}")
            elif ev.kind == "say":
                self.ui.cmd("status", "")
                self.ui.cmd("state", "guiding")
                self.ui.log("eris", ev.value)
                self.voice.say(ev.value)
                if not st["caption"]:
                    st["caption"] = ev.value
                    self.ui.cmd("caption", ev.value)
            elif ev.kind in ("wait", "keep"):
                st["ended"] = True
                mode = ev.value if ev.kind == "wait" else "next"
                self.waiting = mode if self.box or mode == "next" else "next"
            elif ev.kind == "done":
                st["ended"] = True
                self.waiting = None
                self.box = None
                self.ui.cmd("clear_box")
                self.ui.cmd("state", "ready")
                self.steps = 0

        if soft:
            self.ui.cmd("status", "Checking...")
        self.brain.turn(shot, text, on_event, alive)
        if not alive():
            return
        self.ui.cmd("status", "")
        if st["kept"]:
            if not soft:   # screen was still loading: wait for it to change
                self.waiting = self.waiting or "next"
                self.ui.cmd("state", "guiding")
            self.watcher.rebase(delay=0.3, kept=True)   # nothing new: keep watching from here
            return
        if not st["ended"]:
            self.waiting = "next"
        if self.waiting == "click" and self.early_click == my:
            self.advance()   # you already clicked the box while she was talking
            return
        if self.waiting:
            self.watcher.rebase()
            if self.waiting == "next" and not soft and not self.told_watch:
                self.told_watch = True
                self.ui.log("hint", "I'm watching your screen and will notice when you're done "
                                    f"(or press {config.NEXT_KEY.upper()}).")

    # ---------- listening ----------
    def start_listening(self):
        if self.talking or not self.active:
            return
        if not self.ears:
            self.ui.log("hint", "Speech model is still loading (or no mic). You can type instead.")
            return
        self.talking = True
        self.cancel()
        beep("start")
        self.ui.cmd("status", "Listening...")
        self.ui.cmd("state", "listening")
        try:
            self.ears.start()
        except Exception as e:
            self.talking = False
            self.ui.log("error", f"Couldn't open the microphone: {e}")
            self.ui.cmd("status", "")

    def stop_listening(self):
        if not self.talking:
            return
        self.talking = False
        beep("stop")
        self.ui.cmd("status", "Thinking...")
        self.ui.cmd("state", "thinking")

        def work():
            text = self.ears.stop_and_transcribe()
            if text:
                self.ask(text)
            else:
                self.ui.cmd("status", "")
                self.ui.cmd("state", "ready")
                self.ui.log("hint", "Didn't catch that. Hold the key while you talk.")
        threading.Thread(target=work, daemon=True).start()

    # ---------- global input hooks ----------
    # Windows silently removes a keyboard/mouse hook if it takes too long to
    # return, after which hotkeys only work while Eris's own window is in front.
    # So the hooks only drop a note in a queue; this worker does the real work.
    def _input_worker(self):
        while True:
            kind, a, b = self.inbox.get()
            try:
                if kind == "click":
                    self._handle_click(a, b)
                elif kind == "press":
                    self._handle_press(a)
                elif kind == "release":
                    self._handle_release(a)
            except Exception as e:
                self.ui.log("error", f"Input problem: {e}")

    def on_click(self, x, y, button, pressed):
        if pressed and self.box:
            self.inbox.put(("click", x, y))

    def on_press(self, key):
        self.inbox.put(("press", key, None))

    def on_release(self, key):
        self.inbox.put(("release", key, None))

    def _handle_click(self, x, y):
        if not self.box:
            return
        x1, y1, x2, y2 = self.box
        s = config.CLICK_SLOP
        if not (x1 - s <= x <= x2 + s and y1 - s <= y <= y2 + s):
            return
        if self.waiting == "click":
            self.advance()
        elif self.busy and self.box_gen == self.gen:
            self.early_click = self.gen   # she's still talking; move on once she's done

    @staticmethod
    def _is(key, name):
        return key == getattr(keyboard.Key, name.lower(), None)

    def _handle_press(self, key):
        if not self.active:
            return
        if key == keyboard.Key.enter and self.waiting:
            self.watcher.nudge()
        if self._is(key, config.TALK_KEY):
            self.start_listening()
        elif self._is(key, config.NEXT_KEY):
            self.advance()
        elif self._is(key, config.CANCEL_KEY):
            self.cancel()

    def _handle_release(self, key):
        if self._is(key, config.TALK_KEY):
            self.stop_listening()
