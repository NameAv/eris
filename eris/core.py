"""Eris's step-by-step logic: listen, look, box, talk, wait, repeat.

Talks to the window only through ui.cmd(...) and ui.log(...), both thread-safe.
"""
import queue
import sys
import threading
import time
import traceback

from pynput import keyboard

from . import config, elements, privacy, screen, settings, snap
from .brain import Brain, locate
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
        alive = lambda: my == self.gen
        t0 = time.time()
        times = {}   # how long each part took, for the speed log
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
        times["screenshot"] = time.time() - t0
        if not alive():
            return
        self.mon = (shot.left, shot.top, shot.width, shot.height)
        self.ui.cmd("monitor", *self.mon)
        st = {"ended": False, "first": True, "kept": False, "refining": False,
              "avatar": False, "snapped": threading.Event(), "final": None}

        def refine(rough, what):
            """Make the box exact, while she talks:
            1. snap it onto the real edges right away (Windows' element info, or pixels),
            2. zoom in with the AI to make sure it's the right thing,
            3. snap again."""
            if st["refining"]:
                return
            st["refining"] = True
            st["snapped"].clear()

            def move(new):
                if not new or not alive() or max(abs(a - b) for a, b in zip(new, st["final"])) <= 1:
                    return
                on_screen = self.box == st["final"]
                st["final"] = new
                if on_screen:
                    self.box = new
                    self.ui.cmd("move_box", *new)
                    if self.waiting and not self.busy:
                        self.watcher.rebase(delay=0.3)   # the box moving isn't you doing something

            def work():
                try:
                    start = rough
                    quick = snap.snap(shot, rough)
                    if quick and st["final"] == rough:
                        move(quick)
                        start = quick
                    if config.REFINE and alive():
                        tight = locate(self.brain, shot, start, what, alive)
                        if tight and alive() and st["final"] in (rough, start):
                            move(snap.snap(shot, tight) or tight)
                    self.ui.log("debug", f"box: rough={rough} final={st['final']} what={what!r}")
                except Exception as e:
                    self.ui.log("debug", f"box refine failed: {e}")
                finally:
                    st["snapped"].set()
            threading.Thread(target=work, daemon=True).start()

        def on_event(ev):
            if not alive() or st["kept"]:
                return
            now = time.time() - t0
            times.setdefault("first reply", now)
            if ev.kind in ("box", "element"):
                times.setdefault("box", now)
            elif ev.kind == "say":
                times.setdefault("first words", now)
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
                    if ev.kind not in ("box", "element"):
                        self._clear()
            if ev.kind == "element":
                exact = elements.rect(shot.elements, ev.value)
                if exact:   # Windows' own rectangle: already perfect, no snapping needed
                    self.box = st["final"] = exact
                    self.box_gen = my
                    self.early_click = None
                    st["refining"] = True
                    st["snapped"].set()
                    self.ui.cmd("box", *exact)
                    self.ui.log("debug", f"box: element {ev.value} {shot.elements[ev.value - 1]}")
                else:
                    self.ui.log("debug", f"box: element {ev.value} isn't in the list")
            elif ev.kind == "box":
                self.box = st["final"] = shot.to_screen(ev.value)
                self.box_gen = my
                self.early_click = None
                st["refining"] = False
                self.ui.cmd("box", *self.box)
            elif ev.kind == "what":
                if self.box and self.box_gen == my:
                    refine(self.box, ev.value)
            elif ev.kind == "nobox":
                self._clear()
            elif ev.kind == "avatar":
                st["avatar"] = True
            elif ev.kind == "remember":
                settings.remember(ev.value)
                self.ui.log("info", f"Eris will remember: {ev.value}")
            elif ev.kind == "type":
                self.ui.cmd("type_hint", ev.value)
                self.ui.log("hint", f"Type:  {ev.value}")
            elif ev.kind == "say":
                self.ui.cmd("status", "")
                self.ui.cmd("state", "guiding")
                self.ui.log("eris", ev.value)
                self.voice.say(ev.value)
                if self.box and self.box_gen == my:   # no WHAT line: use what she said
                    refine(self.box, ev.value)
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
        times["done"] = time.time() - t0
        self.ui.log("debug", "speed: " + " · ".join(f"{k} {v:.2f}s" for k, v in times.items())
                    + f" ({config.BRAIN}{', automatic look' if soft else ''})")
        if st["avatar"] and st["final"]:
            threading.Thread(target=self._take_avatar, args=(shot, st), daemon=True).start()
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
        """Screenshot + Windows' list of clickable things, fetched at the same time.
        Private fields found by the scan are blacked out before anything leaves the PC."""
        scan = {}

        def ask_windows():
            try:
                from . import uia
                scan.update(uia.get().scan() or {})
            except Exception:
                pass
        helper = None
        if sys.platform == "win32" and (config.PRIVACY or config.ELEMENTS):
            helper = threading.Thread(target=ask_windows, daemon=True)
            helper.start()
        img, mon = screen.capture()
        if helper:
            helper.join(1.0)
        hide = scan.get("sensitive")
        if hide is None:            # Windows didn't answer: fall back to the field check
            hide = privacy.hidden_fields()
        if not config.PRIVACY:
            hide = []
        shot = screen.finish(img, mon, snap=self.brain.snap(), max_w=self.brain.shot_width(),
                             hide=hide)
        if config.ELEMENTS:
            shot.elements = elements.pick(scan.get("elements"), (mon["left"], mon["top"],
                                                                 mon["width"], mon["height"]))
        return shot

    def _prepare_shot(self, token):
        """Take the screenshot while your words are still being transcribed."""
        try:
            if not privacy.should_look_away():
                shot = self._shoot()
                if token is self.pre_token:      # still the same question
                    self.pre_shot = (token, time.time(), shot)
        except Exception:
            self.pre_shot = None

    def _take_avatar(self, shot, st):
        """She picked a profile picture: cut it out of the screenshot (once the box
        has snapped onto it) and make it her picture in the app."""
        if st["refining"]:
            st["snapped"].wait(6)
        box = st["final"]
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
        img = img.crop((l, t, l + side, t + side)).resize((256, 256))
        img.save(settings.AVATAR)
        self.ui.cmd("avatar")
        self.ui.log("info", "Eris has a new profile picture.")

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
