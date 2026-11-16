"""Eris's step-by-step logic: listen, look, box, talk, wait, repeat.

Talks to the window only through ui.cmd(...) and ui.log(...), both thread-safe.
"""
import queue
import sys
import threading
import time
import traceback

from pynput import keyboard

from . import apps, config, elements, ocr, privacy, screen, settings, snap
from .brain import Brain, locate
from .speech import Voice, beep
from .tracker import Tracker
from .watcher import Watcher

WATCH_PROMPT = ("(Automatic look: my screen changed while you were waiting.) Here's my screen "
                "now. If the step is done, give the next step, or DONE if the task is finished. "
                "If I'm still partway through or nothing important changed, reply with just KEEP. "
                "If I did something different, briefly tell me and guide me back.")
MAX_LOOKS_PER_TASK = 30

WRONG_BOX_PROMPT = ("That box was on the wrong thing. Here's my screen again. Look carefully, "
                    "point at the right one and say what it is (so I can tell it's the one).")
KEEP_MISTAKES = 30           # "Wrong box" screenshots kept for the test lab (oldest go first)
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
        self.track = None       # follows the box's button when you scroll (tracker.Tracker)
        self.last_shot = None   # the screenshot of the step on screen (for "Wrong box")
        self.waiting = None     # None | "click" | "next"
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
        self.hotkeys_paused = False   # while you're choosing a new key in Settings
        self._press_token = None
        self._want_hold = False
        self._hold_shown = None
        self.call = None              # call mode: always listening (see ears.Call)
        self.pre_shot = None     # (token, time, Shot) taken when you let go of the talk key
        self.pre_token = None
        threading.Thread(target=self._input_worker, daemon=True).start()
        self.watcher = Watcher(self)
        self.load_ears()

    # ---------- speech model ----------
    def load_ears(self):
        self.ears = None
        threading.Thread(target=self._load_ears, daemon=True).start()

    def _load_ears(self):
        try:
            self.ui.log("info", "Getting my ears ready (the first time takes a minute)...")
            from .ears import Ears
            self.ears = Ears()
            self.ui.log("info", f"Ready. Hold {config.TALK_KEY.upper()} or the button below to talk.")
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
        self.box = self.track = None
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
        self.ui.cmd("clear_chat")

    def set_active(self, on):
        self.active = on
        if not on:
            self.stop_call()
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
        self.voice.ack()   # a quick "on it" so you know she heard you
        self._clear()
        self.steps = 0
        self.auto_looks = self.task_looks = 0
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, text, False, True), daemon=True).start()

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

    def wrong_box(self):
        """You said the box is on the wrong thing: keep a copy for the test lab (on your
        PC only), then she looks again knowing that."""
        if not self.box or not self.active:
            return
        box, shot, history = self.box, self.last_shot, list(self.brain.history[-2:])
        threading.Thread(target=self._save_mistake, args=(shot, box, history), daemon=True).start()
        self.voice.stop()
        self._clear()
        self.auto_looks = 0
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, WRONG_BOX_PROMPT), daemon=True).start()

    def _save_mistake(self, shot, box, history):
        """Screenshot (private fields already blacked out) + what she said, in the
        mistakes folder. Nothing is sent anywhere."""
        if shot is None or shot.full is None:
            return
        try:
            import json
            folder = settings.folder() / "mistakes"
            folder.mkdir(parents=True, exist_ok=True)
            name = time.strftime("%Y%m%d-%H%M%S")
            shot.full.convert("RGB").save(folder / f"{name}.jpg", quality=85)
            (folder / f"{name}.json").write_text(json.dumps({
                "box": [int(v) - o for v, o in zip(box, (shot.left, shot.top) * 2)],
                "app": (shot.app or {}).get("name") if isinstance(shot.app, dict) else None,
                "conversation": history}, indent=1), encoding="utf-8")
            for old in sorted(folder.glob("*.jpg"))[:-KEEP_MISTAKES]:
                old.unlink()
                old.with_suffix(".json").unlink(missing_ok=True)
            self.ui.log("debug", f"wrong box saved as mistakes/{name}")
        except Exception as e:
            self.ui.log("debug", f"couldn't save the wrong box: {e}")

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

    def follow(self, box):
        """The watcher saw the thing she pointed at move (you scrolled, or moved the
        window): the box goes with it."""
        if not self.box or self.busy:
            return
        self.box = box
        self.ui.cmd("move_box", *box)

    def _start_tracking(self, shot, box, hint=""):
        """Remember what the thing she's pointing at looks like, so the box can follow it."""
        self.track = None
        if config.TRACK and box:
            seen = getattr(self.ui, "box_in_screenshots", lambda: True)()
            self.track = Tracker.make(shot.full, shot.left, shot.top, box, hint, seen)

    @property
    def busy(self):
        return self._busy > 0

    def _turn_safe(self, my, text, soft=False, allow_pre=False):
        with self.lock:
            self._busy += 1
        try:
            self._turn(my, text, soft, allow_pre)
        except Exception as e:
            self.ui.log("error", f"Something broke: {e}")
            self.ui.log("debug", traceback.format_exc())
            self.ui.cmd("status", "")
            self.ui.cmd("state", "ready")
        finally:
            with self.lock:
                self._busy -= 1

    def _turn(self, my, text, soft=False, allow_pre=False):
        """One step. soft=True is an automatic look: the current box stays up
        unless the brain has something new to say (it can reply KEEP)."""
        t0 = time.time()
        if not soft:
            self.ui.cmd("status", "Looking...")
            self.ui.cmd("state", "thinking")
        why = privacy.should_look_away()
        if why:   # never take a screenshot while you type a password / use a private app
            self.ui.cmd("status", "")
            if not soft:
                self.ui.cmd("state", "guiding")
                self.ui.log("hint", f"I looked away ({why}). Press {config.NEXT_KEY.upper()} "
                                    "when you're done and I'll look again.")
                self.voice.say("I'll look away while you do that. Press "
                               f"{config.NEXT_KEY.upper()} when you're done.")
                self.waiting = self.waiting or "next"
            return
        shot = self._take_shot(allow_pre)
        self.last_shot = shot
        step = Step(self, my, shot, soft, t0)
        step.times["screenshot"] = time.time() - t0
        if not step.alive():
            return
        self.mon = getattr(shot, "monitor", None) or (shot.left, shot.top, shot.width, shot.height)
        self.ui.cmd("monitor", *self.mon)
        if soft:
            self.ui.cmd("status", "Checking...")
        self.brain.turn(shot, text, step.on_event, step.alive)
        step.times["done"] = time.time() - t0
        step.over = True
        step.track()
        self.ui.log("debug", "speed: " + " · ".join(f"{k} {v:.2f}s" for k, v in step.times.items())
                    + f" ({config.BRAIN}{', automatic look' if soft else ''})")
        if step.avatar and step.final:
            threading.Thread(target=step.save_avatar, daemon=True).start()
        if not step.alive():
            return
        self.ui.cmd("status", "")
        if step.kept:
            if not soft:   # screen was still loading: wait for it to change
                self.waiting = self.waiting or "next"
                self.ui.cmd("state", "guiding")
            self.watcher.rebase(delay=0.3, kept=True)   # nothing new: keep watching from here
            return
        if not step.ended:
            self.waiting = "next"
        if self.waiting == "click" and self.early_click == my:
            self.advance()   # you already clicked the box while she was talking
            return
        if self.waiting:
            self.watcher.rebase()
            if self.waiting == "next" and not soft and not self.told_watch:
                self.told_watch = True
                self.ui.log("info", "I'm watching your screen and will notice when you're done "
                                    f"(or press {config.NEXT_KEY.upper()}).")

    def _take_shot(self, allow_pre=False):
        """Screenshot with private fields blacked out. For a spoken question, uses the
        one taken the moment you let go of the talk key (saves time). That one is
        only ever used for that question, never for a later step."""
        pre, token = self.pre_shot, self.pre_token
        self.pre_shot = self.pre_token = None
        if allow_pre and pre and pre[0] is token and time.time() - pre[1] < 4:
            return pre[2]
        return self._shoot()

    def _shoot(self):
        """Screenshot + which app you're in + the clickable things in it.

        Windows' button list is fetched while the screen is captured. Apps that don't
        share their buttons (Unity, Blender, games) get their window's words read
        instead, and only those apps: browsers and normal apps don't need it. Private
        fields are blacked out first, so they're never read or sent."""
        win = apps.front_window()
        scan = {}

        def ask_windows():
            try:
                from . import uia
                scan.update(uia.get().scan(win["hwnd"] if win else None) or {})
            except Exception:
                pass
        helper = None
        if sys.platform == "win32" and (config.PRIVACY or config.ELEMENTS):
            helper = threading.Thread(target=ask_windows, daemon=True)
            helper.start()
        img, mon = screen.capture(win["rect"] if win else None)
        if helper:
            helper.join(1.0)
        hide = scan.get("sensitive")
        if hide is None:            # Windows didn't answer: fall back to the field check
            hide = privacy.hidden_fields()
        if config.PRIVACY and hide:
            screen.black_out(img, hide, mon)
        found = scan.get("elements") or []
        if config.ELEMENTS and config.OCR and win and self._needs_reading(win, found):
            found = ocr.merge(found, self._read_window(img, mon, win))
        area = screen.window_area(win["rect"], mon) if win and self.brain.window_only() else None
        if area:   # small models: just the app's window, so its words come out sharper
            img = img.crop((area["left"] - mon["left"], area["top"] - mon["top"],
                            area["left"] - mon["left"] + area["width"], area["top"] - mon["top"] + area["height"]))
        shot = screen.finish(img, area or mon, snap=self.brain.snap(), max_w=self.brain.shot_width())
        shot.app = win
        if area:
            shot.monitor = (mon["left"], mon["top"], mon["width"], mon["height"])
        if config.ELEMENTS:
            a = area or mon
            shot.elements = elements.pick(found, (a["left"], a["top"], a["width"], a["height"]))
        return shot

    @staticmethod
    def _needs_reading(win, found):
        """Read the screen's words only for apps whose buttons Windows can't see (few or
        no named items from its button list), e.g. Unity, Blender and games."""
        return sum(1 for e in found if e.get("name")) < 8

    @staticmethod
    def _read_window(img, mon, win):
        """Read just the app's window (the part of it on this monitor)."""
        x1, y1, x2, y2 = win["rect"]
        a, b = max(x1, mon["left"]), max(y1, mon["top"])
        c, d = min(x2, mon["left"] + mon["width"]), min(y2, mon["top"] + mon["height"])
        if c - a < 50 or d - b < 50:
            return []
        crop = img.crop((a - mon["left"], b - mon["top"], c - mon["left"], d - mon["top"]))
        return ocr.reader().read(crop, a, b)

    def _prepare_shot(self, token):
        """Take the screenshot while your words are still being transcribed."""
        try:
            if not privacy.should_look_away():
                shot = self._shoot()
                if token is self.pre_token:      # still the same question
                    self.pre_shot = (token, time.time(), shot)
        except Exception:
            self.pre_shot = None

    # ---------- call mode ----------
    @property
    def on_call(self):
        return self.call is not None

    def toggle_call(self):
        self.stop_call() if self.on_call else self.start_call()

    def start_call(self):
        if self.on_call or not self.active:
            return
        if not self.ears:
            self.ui.log("hint", "My ears are still loading (or there's no mic). Try again in a moment.")
            return
        from .ears import Call
        call = Call(self.ears, on_start=self._call_heard_you, on_text=self._call_text,
                    muted=lambda: (self.voice.busy() or self.talking or not self.active
                                   or self.hotkeys_paused))
        try:
            call.start()
        except Exception as e:
            self.ui.log("error", f"Couldn't open the microphone: {e}")
            return
        self.call = call
        beep("start")
        self.ui.cmd("call", True)
        self.ui.log("info", "On a call: just talk, I'm listening. Click the button to hang up.")

    def stop_call(self):
        if not self.on_call:
            return
        self.call.stop()
        self.call = None
        beep("stop")
        self.ui.cmd("call", False)
        self.ui.cmd("status", "")
        self.ui.log("info", "Call ended.")

    def _call_heard_you(self):
        self.ui.cmd("status", "Listening...")
        self.ui.cmd("state", "listening")

    def _call_text(self, text):
        if not self.on_call:
            return
        if text:
            self.ask(text)
        else:
            self.ui.cmd("status", "")
            self.ui.cmd("state", "guiding" if self.waiting else "ready")

    # ---------- listening ----------
    def start_listening(self):
        """The talk key went down: push-to-talk straight away."""
        if not self.ears:
            self.ui.log("hint", "My ears are still loading (or there's no mic). You can type instead.")
            return
        self._press_token = object()
        if self.begin_hold():
            self.confirm_hold()

    # The talk button. Opening the microphone can take a moment on Windows, so it happens
    # on a helper thread; a token makes sure a quick click never leaves it recording.
    def press(self):
        self._want_hold = False
        self._press_token = token = object()
        threading.Thread(target=self._press_work, args=(token,), daemon=True).start()

    def _press_work(self, token):
        if self.begin_hold():
            if self._press_token is not token:
                self.abort_listening()          # you already let go (it was a click)
            elif self._want_hold:
                self.confirm_hold()             # the mic was slow to open; you're holding

    def release_click(self):
        self._press_token = None
        self.abort_listening()
        threading.Thread(target=self.toggle_call, daemon=True).start()

    def release_hold(self):
        self._press_token = None
        self.stop_listening()

    def begin_hold(self):
        """Talk button pressed: start recording straight away (so your first word isn't
        cut off) but don't interrupt anything yet; it might just be a click."""
        if self.talking or not self.active or not self.ears:
            return False
        try:
            self.ears.start()
        except Exception as e:
            self.ui.log("error", f"Couldn't open the microphone: {e}")
            return False
        self.talking = True
        return True

    def confirm_hold(self):
        """Still held after a moment: it's push-to-talk."""
        self._want_hold = True
        if not self.talking or self._hold_shown is self._press_token:
            return
        self._hold_shown = self._press_token
        self._new_gen()
        self.voice.stop()
        self._clear()
        self.steps = 0
        beep("start")
        self.ui.cmd("status", "Listening...")
        self.ui.cmd("state", "listening")
        threading.Thread(target=self.brain.prewarm, daemon=True).start()

    def abort_listening(self):
        """The talk button was only clicked, not held: forget that recording."""
        if not self.talking:
            return
        self.talking = False
        self.ears.abort()
        self.ui.cmd("status", "")
        self.ui.cmd("state", "ready")

    def stop_listening(self):
        if not self.talking:
            return
        self.talking = False
        beep("stop")
        self.ui.cmd("status", "Thinking...")
        self.ui.cmd("state", "thinking")
        self.pre_token = token = object()
        threading.Thread(target=self._prepare_shot, args=(token,), daemon=True).start()

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

    def _wanted(self, key):
        """Only Eris's own hotkeys and Enter get past the hook. Letters, numbers and
        everything else you type are dropped right here and never stored."""
        if not isinstance(key, keyboard.Key):
            return False
        return key == keyboard.Key.enter or getattr(key, "name", "") in (
            config.TALK_KEY.lower(), config.NEXT_KEY.lower(), config.CANCEL_KEY.lower())

    def on_press(self, key):
        if self._wanted(key):
            self.inbox.put(("press", key, None))

    def on_release(self, key):
        if self._wanted(key):
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
        if not self.active or self.hotkeys_paused:
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
        if self.hotkeys_paused:
            return
        if self._is(key, config.TALK_KEY):
            self.stop_listening()


class Step:
    """One reply from the brain, acted on line by line as it streams in: boxes go up
    the moment they arrive and are made exact while she's still talking."""

    def __init__(self, eris, my, shot, soft, t0):
        self.e, self.my, self.shot, self.soft, self.t0 = eris, my, shot, soft, t0
        self.times = {}            # how long each part took, for the speed log
        self.first = True          # no line handled yet
        self.ended = False         # she said how this step ends (WAIT / DONE / ...)
        self.kept = False          # nothing new: the old step stays
        self.avatar = False        # the box is her new profile picture
        self.refining = False
        self.snapped = threading.Event()
        self.hint = ""             # what she asked you to type
        self.over = False          # the brain has finished this reply
        self.final = None          # where the box ends up after refining

    def alive(self):
        return self.my == self.e.gen

    def on_event(self, ev):
        if not self.alive() or self.kept:
            return
        now = time.time() - self.t0
        self.times.setdefault("first reply", now)
        if ev.kind in ("box", "element"):
            self.times.setdefault("box", now)
        elif ev.kind == "say":
            self.times.setdefault("first words", now)
        if ev.kind == "fail":
            return self.on_fail(ev.value)
        if self.first:
            self.first = False
            if ev.kind == "keep":
                self.kept = True
                return
            if self.soft:   # an automatic look found something new: drop the old step
                e = self.e
                e.waiting = None
                e.auto_looks = 0
                e.voice.stop()
                if ev.kind not in ("box", "element"):
                    e._clear()
        handler = getattr(self, "on_" + ev.kind, None)
        if handler:
            handler(ev.value)

    # ---- one method per kind of line ----
    def on_fail(self, message):
        e = self.e
        if self.soft:   # a hiccup during an automatic look: just keep waiting
            e.ui.log("debug", f"automatic look failed: {message}")
            self.kept = True
            return
        e._clear()
        e.ui.log("error", message)
        e.voice.say(message)
        e.ui.cmd("state", "ready")
        self.ended = True

    def on_element(self, n):
        e, shot = self.e, self.shot
        exact, _ = snap.element(shot, n)
        if not exact:
            e.ui.log("debug", f"box: element {n} isn't in the list")
            return
        from .uia import TYPE_NAMES
        self._show(exact, TYPE_NAMES.get(shot.elements[n - 1].get("type")))
        self.refining = True   # an exact rectangle: no precision pass needed
        self.snapped.set()
        e.ui.log("debug", f"box: element {n} {shot.elements[n - 1]}")

    def on_box(self, rough):
        self._show(self.shot.to_screen(rough))
        self.refining = False

    def on_what(self, what):
        if self._my_box():
            self.refine(what)

    def on_nobox(self, _):
        self.e._clear()

    def on_avatar(self, _):
        self.avatar = True

    def on_remember(self, fact):
        settings.remember(fact)
        self.e.ui.log("info", f"Eris will remember: {fact}")

    def on_type(self, text):
        self.hint = text
        self.e.ui.cmd("type_hint", text)
        self.e.ui.log("hint", f"Type:  {text}")

    def on_key(self, keys):
        e = self.e
        e.ui.log("hint", f"Press:  {keys}")
        if self._my_box():
            self.hint = keys
            e.ui.cmd("type_hint", keys, "press:  ")
        else:
            e.ui.cmd("badge", f"press  {keys}", *self._area())

    def on_scroll(self, way):
        self.e.ui.log("hint", f"Scroll {way}")
        self.e.ui.cmd("scroll_hint", way, *self._area())

    def on_to(self, where):
        """A drag: the box is what to drag, this is where to drop it."""
        if not self._my_box():
            return
        shot = self.shot
        if isinstance(where, int):
            drop, _ = snap.element(shot, where)
        else:
            rough = shot.to_screen(where)
            drop = snap.snap(shot, rough) or rough
        if drop:
            self.e.ui.cmd("drop", *drop)

    def _area(self):
        """Where the screenshot was taken: the app's window, or the whole monitor."""
        return self.shot.left, self.shot.top, self.shot.width, self.shot.height

    def on_say(self, words):
        e = self.e
        e.ui.cmd("status", "")
        e.ui.cmd("state", "guiding")
        e.ui.log("eris", words)
        e.voice.say(words)
        if self._my_box():   # no WHAT line: use what she said
            self.refine(words)

    def on_wait(self, mode):
        self.ended = True
        self.e.waiting = mode if self.e.box or mode == "next" else "next"

    def on_keep(self, _):   # KEEP after other lines: wait for you to press Next
        self.on_wait("next")

    def on_done(self, _):
        e = self.e
        self.ended = True
        e.waiting = e.box = e.track = None
        e.ui.cmd("clear_box")
        e.ui.cmd("state", "ready")
        e.steps = 0

    # ---- the box ----
    def _show(self, box, kind=None):
        e = self.e
        e.box = self.final = box
        e.track = None
        e.box_gen = self.my
        e.early_click = None
        e.ui.cmd("box", *box, "", kind) if kind else e.ui.cmd("box", *box)

    def _my_box(self):
        return self.e.box and self.e.box_gen == self.my

    def refine(self, what):
        """Make the box exact, while she talks:
        1. snap it onto the real edges right away (Windows' element info, or pixels),
        2. zoom in with the AI to make sure it's the right thing,
        3. snap again."""
        if self.refining:
            return
        self.refining = True
        self.snapped.clear()
        threading.Thread(target=self._refine, args=(self.e.box, what), daemon=True).start()

    def _refine(self, rough, what):
        e, shot = self.e, self.shot
        try:
            start = rough
            quick = snap.snap(shot, rough)
            if quick and self.final == rough:
                self._move(quick)
                start = quick
            if config.REFINE and self.alive():
                tight = locate(e.brain, shot, start, what, self.alive)
                if tight and self.alive() and self.final in (rough, start):
                    self._move(snap.snap(shot, tight) or tight)
            e.ui.log("debug", f"box: rough={rough} final={self.final} what={what!r}")
        except Exception as ex:
            e.ui.log("debug", f"box refine failed: {ex}")
        finally:
            self.snapped.set()
            self.track()

    def track(self):
        """Once the reply is over and the box has settled: let the box follow its button."""
        e = self.e
        if self.over and (not self.refining or self.snapped.is_set()) and self.alive() \
                and self.final and e.box == self.final and e.track is None:
            e._start_tracking(self.shot, self.final, self.hint)

    def _move(self, new):
        e = self.e
        if not new or not self.alive() or max(abs(a - b) for a, b in zip(new, self.final)) <= 1:
            return
        on_screen = e.box == self.final
        self.final = new
        if on_screen:
            e.box, e.track = new, None
            e.ui.cmd("move_box", *new)
            if e.waiting and not e.busy:
                e.watcher.rebase(delay=0.3)   # the box moving isn't you doing something

    def save_avatar(self):
        """She picked a profile picture: cut it out of the screenshot (once the box
        has snapped onto it) and make it her picture in the app."""
        if self.refining:
            self.snapped.wait(6)
        box, shot = self.final, self.shot
        if not box or shot.full is None:
            return
        p = config.BOX_PADDING
        x1, y1 = box[0] + p - shot.left, box[1] + p - shot.top
        x2, y2 = box[2] - p - shot.left, box[3] - p - shot.top
        if x2 - x1 < 32 or y2 - y1 < 32:
            return
        img = shot.full.crop((x1, y1, x2, y2))
        side = min(img.size)               # square from the middle
        l, t = (img.width - side) // 2, (img.height - side) // 2
        img.crop((l, t, l + side, t + side)).resize((256, 256)).save(settings.AVATAR)
        self.e.ui.cmd("avatar")
        self.e.ui.log("info", "Eris has a new profile picture.")
