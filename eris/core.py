"""Eris's step-by-step logic: listen, look, box, talk, wait, repeat.

Talks to the window only through ui.cmd(...) and ui.log(...), both thread-safe.
"""
import threading
import time
import traceback

from pynput import keyboard

from . import config, screen
from .brain import Brain
from .speech import Voice, beep

NEXT_STEP_PROMPT = ("I did that step. Here's my screen now. Check it worked, then give the "
                    "next step, or DONE if the task is finished.")


class Eris:
    def __init__(self, ui):
        self.ui = ui
        self.voice = Voice()
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
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, text), daemon=True).start()

    def advance(self):
        """Step finished (click in box or Next): box goes away NOW, then look again."""
        if not self.waiting:
            return
        self.voice.stop()
        self._clear()
        self.steps += 1
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

    def _turn_safe(self, my, text):
        try:
            self._turn(my, text)
        except Exception as e:
            self.ui.log("error", f"Something broke: {e}")
            self.ui.log("debug", traceback.format_exc())
            self.ui.cmd("status", "")
            self.ui.cmd("state", "ready")

    def _turn(self, my, text):
        alive = lambda: my == self.gen
        self.ui.cmd("status", "Looking...")
        self.ui.cmd("state", "thinking")
        shot = screen.grab()
        if not alive():
            return
        self.ui.cmd("monitor", shot.left, shot.top, shot.width, shot.height)
        self.caption = ""
        ended = {"v": False}

        def on_event(ev):
            if not alive():
                return
            if ev.kind == "box":
                self.box = shot.to_screen(ev.value)
                self.ui.cmd("box", *self.box, "")
            elif ev.kind == "nobox":
                self._clear()
            elif ev.kind == "say":
                self.ui.cmd("status", "")
                self.ui.cmd("state", "guiding")
                self.ui.log("eris", ev.value)
                self.voice.say(ev.value)
                if not self.caption:
                    self.caption = ev.value
                    self.ui.cmd("caption", ev.value)
            elif ev.kind == "wait":
                ended["v"] = True
                self.waiting = ev.value if self.box or ev.value == "next" else "next"
                if self.waiting == "next":
                    self.ui.log("hint", f"Press {config.NEXT_KEY.upper()} or Next step when done.")
            elif ev.kind == "done":
                ended["v"] = True
                self.waiting = None
                self.box = None
                self.ui.cmd("clear_box")
                self.ui.cmd("state", "ready")
                self.steps = 0

        self.brain.turn(shot, text, on_event, alive)
        if alive():
            self.ui.cmd("status", "")
            if not ended["v"]:
                self.waiting = "next"

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
    def on_click(self, x, y, button, pressed):
        if not pressed or self.waiting != "click" or not self.box:
            return
        x1, y1, x2, y2 = self.box
        s = config.CLICK_SLOP
        if x1 - s <= x <= x2 + s and y1 - s <= y <= y2 + s:
            self.advance()

    @staticmethod
    def _is(key, name):
        return key == getattr(keyboard.Key, name.lower(), None)

    def on_press(self, key):
        if not self.active:
            return
        if self._is(key, config.TALK_KEY):
            self.start_listening()
        elif self._is(key, config.NEXT_KEY):
            self.advance()
        elif self._is(key, config.CANCEL_KEY):
            self.cancel()

    def on_release(self, key):
        if self._is(key, config.TALK_KEY):
            self.stop_listening()
