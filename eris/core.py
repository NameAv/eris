"""Eris's step-by-step logic: listen, look, box, talk, wait, repeat.

Talks to the window only through ui.cmd(...) and ui.log(...), both thread-safe.
"""
import queue
import re
import sys
import threading
import time
import traceback

from pynput import keyboard

from . import apps, config, course, elements, experience, ocr, privacy, recipes, screen, settings, snap, unity_book, unity_project
from .brain import Brain, locate
from .protocol import Event
from .speech import Voice, beep
from .tracker import Tracker
from .watcher import STILL as SCREEN_STILL, Watcher, changed as screen_changed

WATCH_PROMPT = ("(Automatic look: my screen changed while you were waiting.) Here's my screen "
                "now. If the step is done, give the next step, or DONE if the task is finished. "
                "If I haven't done it yet, I'm partway through or nothing important changed, reply "
                "with just KEEP (don't repeat the step). If I did something different, briefly "
                "tell me and guide me back.")
MAX_LOOKS_PER_TASK = 30
ACTIONS = {"click", "double-click", "right-click", "type", "press", "hit", "scroll", "drag", "open",
           "select", "choose", "pick", "tap", "close", "enter", "search", "hold", "move", "put", "use",
           "switch", "go", "find", "check", "tick", "untick", "turn", "hover", "save", "copy", "paste"}
FILLERS = {"now", "next", "then", "okay", "ok", "great", "good", "nice", "so", "alright", "right",
           "perfect", "lovely", "awesome", "first", "and", "just"}


def is_action(line):
    """Does this line tell you what to do ("Click...", "Now type...")? Otherwise it's
    commentary ("Good, the search worked...")."""
    for word in re.findall(r"[a-z'-]+", line.lower())[:4]:
        if word in ACTIONS:
            return True
        if word not in FILLERS:
            return False
    return False

WRONG_BOX_PROMPT = ("That box was on the wrong thing. Here's my screen again. Look carefully, "
                    "point at the right one and say what it is (so I can tell it's the one).")
KEEP_MISTAKES = 30           # "Wrong box" screenshots kept for the test lab (oldest go first)
STUCK_PROMPT = ("I'm stuck on this step. Here's my screen. Give me hint level {level} of 3 "
                "(see the teacher rules). Don't do it for me.")
AHEAD_CHECK_PROMPT = ("I did that step. Here's my screen now. To be quick, I've already been shown "
                      "the step you planned next: \"{say}\" (boxed: {what}). If that's right for "
                      "this screen, reply with just KEEP. If not, give the right step now; it "
                      "replaces that one.")
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
        self.task = None        # the task in hand: what you asked, the app, its steps so far
        self.check = None       # the screen as a step was set, to see what your click changed
        self.retried = False    # "give it another click" said once for this step
        self.pending_note = ""  # what that check found, for the next look
        self.last_key = 0.0     # when you last pressed a key (not which key)
        self.last_what = ""     # what the box on screen points at (for lessons)
        self.hint_level = 0     # Eris Unity: how much help you've asked for on this step
        self.ahead = None       # (gen of the step on screen, the next step's words) planned early
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
        self.task = self.check = None
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
    def ask(self, text, lesson=None):
        if not self.active:
            self.set_active(True)
            self.ui.cmd("active", True)
        self.ui.log("you", text)
        self.voice.stop()
        self.voice.ack()   # a quick "on it" so you know she heard you
        self._clear()
        self.steps = 0
        self.auto_looks = self.task_looks = 0
        self.task = {"text": text, "app": None, "steps": [], "wrong": False, "recipe": None,
                     "learned": "", "book": "", "plan": [], "wrong_what": None,
                     "lesson": lesson}
        self.check, self.retried, self.pending_note = None, False, ""
        self.hint_level = 0
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, text, False, True), daemon=True).start()

    @staticmethod
    def _scale():
        """A lesson in Eris Unity is a long task: it gets more steps and looks."""
        return 3 if config.MODE == "unity" else 1

    def start_lesson(self, lesson):
        """Eris Unity: teach this lesson, starting from what's on screen."""
        self.new_task()
        self.ui.log("info", f"Lesson {course.number(lesson)}: {lesson.title}")
        self.ask(course.task(lesson), lesson)

    def stuck(self):
        """Eris Unity: you asked for more help with this step (up to 3 hints, each bigger)."""
        if not self.active:
            return
        if self.task is None:
            self.ui.log("hint", "Start a lesson or ask me something first, then press Stuck.")
            return
        self.hint_level = min(3, self.hint_level + 1)
        self.ui.log("you", f"I'm stuck (hint {self.hint_level} of 3)")
        self.voice.stop()
        self._clear()
        self.auto_looks = 0
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, STUCK_PROMPT.format(level=self.hint_level)),
                         daemon=True).start()

    def advance(self, clicked=False):
        """Step finished (click in box or Next): box goes away NOW, then a quick free check
        of what changed, then look again."""
        if not self.waiting:
            return
        ref, self.check = self.check, None
        planned = self.ahead[1] if clicked and self.ahead and self.ahead[0] == self.box_gen else None
        self.ahead = None
        t = self.task
        if t and t["wrong_what"] and self.last_what and self.last_what != t["wrong_what"]:
            experience.learn(t["app"], t["text"], t["wrong_what"], self.last_what)   # that one was right
            t["wrong_what"] = None
        self.voice.stop()
        self._clear()
        self.steps += 1
        self.auto_looks = 0
        my = self._new_gen()
        self.hint_level = 0
        if self.steps >= config.MAX_STEPS * self._scale():
            msg = "That's a lot of steps, let's pause here. Ask me again if you're stuck."
            self.ui.log("eris", msg)
            self.voice.say(msg)
            return

        threading.Thread(target=self._after_step, args=(my, ref, clicked, planned), daemon=True).start()

    def _after_step(self, my, ref, clicked, planned=None):
        """A moment after the step: check what changed (free), then look again."""
        time.sleep(config.SETTLE_DELAY)   # let menus/panels open first
        if my != self.gen:
            return
        seen = self._settle(my, ref) if ref else ""
        if my != self.gen:
            return
        if seen == "nothing" and clicked and not self.retried and ref.get("box"):
            self._click_again(my, ref)
            return
        self.retried = False
        if seen:
            self.pending_note = ("(Quick check after that step: "
                                 + ("nothing on the screen changed" if seen == "nothing" else seen) + ".)")
        self._turn_safe(my, NEXT_STEP_PROMPT, ahead=None if seen == "nothing" else planned)

    # ---------- checking a step, recipes ----------
    def _settle(self, my, ref, longest=3.0, give_up=1.5):
        """Wait until your action has finished showing (a page loading, a menu opening):
        until the screen has changed and stopped changing, up to `longest` seconds, or
        `give_up` seconds of nothing changing at all. Looking any sooner would show her
        the old screen, and she'd repeat herself. Returns what changed (_what_changed)."""
        start, prev = time.time(), None
        while True:
            now = self.watcher.look()
            seen = self._what_changed(ref, now)
            waited = time.time() - start
            if my != self.gen or now is None or not seen or waited >= longest:
                return seen
            if seen == "nothing":
                if waited >= give_up:
                    return seen
            elif prev is not None and screen_changed(now, prev) <= SCREEN_STILL:
                return seen                # changed, and settled
            prev = now
            time.sleep(0.15)

    def _what_changed(self, ref, now=None):
        """What your last action changed, from a free before/after look: "nothing", a
        short description, or "" if it can't tell."""
        win, before = apps.front_window(), ref.get("win") or {}
        if win and before and win.get("hwnd") != before.get("hwnd"):
            return f'a different window is in front now: {win["name"]} ("{win["title"][:60]}")'
        now = self.watcher.look() if now is None else now
        if now is None or ref.get("thumb") is None:
            return ""
        part = screen_changed(now, ref["thumb"])
        if part < 0.0003:
            return "nothing"
        return "only a small part of the screen changed" if part < 0.02 else "a lot of the screen changed"

    def _click_again(self, my, ref):
        """Your click didn't change anything: put the box back and say so (no AI needed)."""
        self.retried = True
        self.steps -= 1
        box = ref["box"]
        self.box, self.box_gen, self.waiting = box, my, "click"
        self.ui.cmd("box", *box)
        self._start_tracking(self.last_shot, box)
        msg = "Nothing happened yet. Give it another click, right inside the box."
        self.ui.log("eris", msg)
        self.voice.say(msg)
        self.ui.cmd("state", "guiding")
        self.check = ref
        self.watcher.rebase()

    def _set_check(self, my, shot):
        """Remember how the screen looks as a step is set (for _what_changed)."""
        thumb = self.watcher.look()
        if my == self.gen:
            self.check = {"thumb": thumb, "win": getattr(shot, "app", None), "box": self.box}

    def _log_step(self, text):
        t = self.task
        if t is not None and text and (not t["steps"] or t["steps"][-1] != text):
            t["steps"].append(text)
            if t["plan"]:                  # "Step 2 of 4" under the chat
                n = min(len(t["steps"]), len(t["plan"]))
                self.ui.log("info", f"Step {n} of {len(t['plan'])}: {t['plan'][n - 1]}")

    def _set_plan(self, text):
        """Her plan for the task (the first reply's PLAN line), shown in the chat."""
        t = self.task
        steps = [s.strip() for s in text.split("|") if s.strip()][:8]
        if t is None or t["plan"] or len(steps) < 2:
            return
        t["plan"] = steps
        self.ui.log("hint", "Plan:  " + "   ".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))

    def _finish_task(self):
        """The task is done: keep its steps as a recipe, unless something went wrong."""
        t, self.task = self.task, None
        if t and not t["wrong"] and t["app"] and t["steps"]:
            experience.finished(t["app"])
        if t and not t["wrong"] and t["app"] and len(t["steps"]) >= 2:
            try:
                recipes.remember(t["text"], t["app"], t["steps"])
                self.ui.log("debug", f"recipe kept: {t['text']!r} ({len(t['steps'])} steps)")
            except OSError as e:
                self.ui.log("debug", f"couldn't keep the recipe: {e}")

    def wrong_box(self):
        """You said the box is on the wrong thing: keep a copy for the test lab (on your
        PC only), then she looks again knowing that."""
        if not self.box or not self.active:
            return
        box, shot, history = self.box, self.last_shot, list(self.brain.history[-2:])
        if self.task:
            self.task["wrong"] = True     # this one won't be kept as a recipe
            self.task["wrong_what"] = self.last_what
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
        if self.task_looks >= MAX_LOOKS_PER_TASK * self._scale():
            return
        self.auto_looks += 1
        self.task_looks += 1
        my = self._new_gen()
        threading.Thread(target=self._turn_safe, args=(my, WATCH_PROMPT, True), daemon=True).start()

    def screen_moved_on(self):
        """A new screen came up while she was waiting: what she was saying and pointing at is
        out of date, so stop talking and take the box down (her next look gives the next step)."""
        self.voice.stop()
        if self.box:
            self.track = None
            self.ui.cmd("clear_box")

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

    def _turn_safe(self, my, text, soft=False, allow_pre=False, ahead=None):
        with self.lock:
            self._busy += 1
        try:
            self._turn(my, text, soft, allow_pre, ahead)
        except Exception as e:
            self.ui.log("error", f"Something broke: {e}")
            self.ui.log("debug", traceback.format_exc())
            self.ui.cmd("status", "")
            self.ui.cmd("state", "ready")
        finally:
            with self.lock:
                self._busy -= 1

    def _turn(self, my, text, soft=False, allow_pre=False, ahead=None):
        """One step. soft=True is an automatic look: the current box stays up
        unless the brain has something new to say (it can reply KEEP). ahead: the next
        step's words, planned while you did this one: shown at once if what it names is
        on screen, then checked by her real look (which replaces it only if it's wrong)."""
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
        auto = soft
        if ahead and self._show_ahead(my, shot, ahead, t0):
            text = AHEAD_CHECK_PROMPT.format(say=ahead["say"], what=ahead["what"])
            soft = True
            step = Step(self, my, shot, True, t0)
        if soft:
            self.ui.cmd("status", "Checking...")
        if auto and not self.brain.moved_on(shot, self._step_now()):
            step.kept = True       # still working on it: no need for the full brain
        else:
            self.brain.turn(shot, text, step.on_event, step.alive, self._notes(shot))
        step.times["done"] = time.time() - t0
        step.over = True
        step.finish_talking()
        step.track()
        self.ui.log("debug", "speed: " + " · ".join(f"{k} {v:.2f}s" for k, v in step.times.items())
                    + f" ({config.BRAIN}{', automatic look' if auto else ', checking the planned step' if soft else ''})")
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
            if text.startswith(AHEAD_CHECK_PROMPT[:20]) and self.waiting == "click" and config.AHEAD:
                threading.Thread(target=self._plan_ahead, args=(my, shot), daemon=True).start()
            return
        if not step.ended:
            self.waiting = "next"
        if self.waiting == "click" and self.early_click == my:
            self.advance()   # you already clicked the box while she was talking
            return
        if self.waiting == "click" and config.AHEAD:      # work out the next step while you click
            threading.Thread(target=self._plan_ahead, args=(my, shot), daemon=True).start()
        if self.waiting:
            self.watcher.rebase()
            self._set_check(my, shot)
            if self.waiting == "next" and not soft and not self.told_watch:
                self.told_watch = True
                self.ui.log("info", "I'm watching your screen and will notice when you're done "
                                    f"(or press {config.NEXT_KEY.upper()}).")

    # ---------- planning ahead ----------
    def _plan_ahead(self, my, shot):
        plan = self.brain.predict(shot)
        if plan and self.box_gen == my:
            self.ahead = (my, plan)
            self.ui.log("debug", f"planned ahead: {plan['say']!r} ({plan['what']!r})")

    @staticmethod
    def _named(shot, what):
        """The one element on screen whose name is `what` (or the longest name inside it), or None."""
        els = getattr(shot, "elements", None) or []
        names = [(el.get("name") or "").strip().lower() for el in els]
        want = what.strip().strip('"').lower()
        exact = [i for i, n in enumerate(names, 1) if n and n == want]
        if len(exact) == 1:
            return exact[0]
        inside = [(len(n), i) for i, n in enumerate(names, 1) if len(n) >= 4 and n in want]
        if not inside:
            return None
        longest = max(inside)[0]
        best = [i for size, i in inside if size == longest]
        same = {names[i - 1] for i in best}
        return best[0] if len(best) == 1 and len(same) == 1 else None

    def _show_ahead(self, my, shot, plan, t0):
        """Show the planned step at once, if exactly what it names is on the new screen."""
        n = self._named(shot, plan["what"])
        if not n or not is_action(plan["say"]):
            return False
        step = Step(self, my, shot, False, t0)
        events = [Event("element", n), Event("what", plan["what"])]
        events += [Event(k, plan[k]) for k in ("type", "key") if plan.get(k)]
        events += [Event("say", plan["say"]), Event("wait", plan.get("wait", "click"))]
        for ev in events:
            step.on_event(ev)
        if not step.alive() or not self.box:
            return False
        step.over = True
        step.track()
        self.watcher.rebase()
        self._set_check(my, shot)
        self.ui.log("debug", f"planned step shown in {time.time() - t0:.2f}s")
        return True

    def _step_now(self):
        """The instruction on screen now (for the quick check)."""
        t = self.task
        return t["steps"][-1] if t and t["steps"] else self.last_what

    def _notes(self, shot):
        """Extra context for this look: a recipe that worked before, what the last step changed."""
        notes = []
        t = self.task
        if t is not None:
            if t["app"] is None:            # the task's first look: which app, any recipe for it?
                app = shot.app.get("name") if isinstance(getattr(shot, "app", None), dict) else ""
                t["app"] = app or ""
                t["recipe"] = recipes.find(t["text"], app) if app else None
                t["learned"] = experience.notes(app, t["text"])
                if app == "Unity":
                    self._note_unity_version(shot.app.get("title", ""))
                if config.MODE == "unity":    # the handbook: the lesson's page, or the pages your question needs
                    lesson = t["lesson"] or course.current()
                    t["book"] = unity_book.notes("" if t["lesson"] else t["text"], lesson and lesson.id)
                if t["recipe"]:
                    self.ui.log("debug", f"using a recipe: {t['recipe']['task']!r}")
            if t["recipe"]:
                notes.append(recipes.describe(t["recipe"], self.steps + 1))
            if t["learned"]:
                notes.append(t["learned"])
            if t["book"]:
                notes.append(t["book"])
        if config.MODE == "unity":         # their project: scripts, the open script, errors
            project = unity_project.notes(getattr(shot, "app", None))
            if project:
                notes.append(project)
        if self.pending_note:
            notes.append(self.pending_note)
            self.pending_note = ""
        return "\n\n".join(notes)

    def _note_unity_version(self, title):
        """Keep the Unity version from its title bar, so Eris Unity teaches that version."""
        ver = unity_book.version_in(title)
        if ver and ver != config.UNITY_VERSION:
            config.UNITY_VERSION = ver
            settings.save()
            self.ui.log("debug", f"Unity version: {ver}")

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
        hide_me = getattr(self.ui, "hide_me_from_capture", None)
        if hide_me:          # see past her own window, even if it covers the app
            hide_me(True)
            time.sleep(0.05)
        try:
            img, mon = screen.capture(win["rect"] if win else None)
        finally:
            if hide_me:
                hide_me(False)
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
        self.last_key = time.time()        # only *when* a key was pressed (never which), so she
        if self._wanted(key):              # doesn't look while you're typing
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
            self.advance(clicked=True)
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
        self.hint = ""             # what she asked you to type (or press), shown with the box
        self.said = ""             # her first line: the instruction (kept for recipes)
        self.instructed = False    # the instruction has been read out
        self.held = None           # her first line, if it was only commentary
        self.what = ""             # what she pointed at
        self.typed = self.key = ""
        self.dragged = False
        self.element_n = None      # the list number she picked, while it's still being checked
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
                e.voice.stop()             # the screen moved on: so does she
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
        self.element_n = n
        self.refining = True   # an exact rectangle: no precision pass needed
        self.snapped.set()
        e.ui.log("debug", f"box: element {n} {shot.elements[n - 1]}")

    def on_box(self, rough):
        self._show(self.shot.to_screen(rough))
        self.refining = False

    def on_what(self, what):
        self.what = what
        self._check_element(what)
        if self._my_box():
            self.refine(what)

    def on_nobox(self, _):
        self.e._clear()

    def on_avatar(self, _):
        self.avatar = True

    def on_project(self, fact):
        """Eris Unity: something lasting they made, kept so later lessons build on it."""
        if config.MODE == "unity":
            course.remember(fact)
            self.e.ui.log("debug", f"project note: {fact}")

    def on_remember(self, fact):
        settings.remember(fact)
        self.e.ui.log("info", f"Eris will remember: {fact}")

    def on_type(self, text):
        self.hint = self.typed = text
        self.e.ui.cmd("type_hint", text)
        self.e.ui.log("hint", f"Type:  {text}")

    def on_key(self, keys):
        e = self.e
        e.ui.log("hint", f"Press:  {keys}")
        self.key = keys
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
            self.dragged = True
            self.e.ui.cmd("drop", *drop)

    def _area(self):
        """Where the screenshot was taken: the app's window, or the whole monitor."""
        return self.shot.left, self.shot.top, self.shot.width, self.shot.height

    def on_say(self, words):
        e = self.e
        e.ui.cmd("status", "")
        e.ui.cmd("state", "guiding")
        e.ui.log("eris", words)            # the chat shows every line; only what matters is read out
        if is_action(words):
            self._check_element(words)
        if is_action(words) and not self.instructed:
            self.instructed = True
            e.voice.say(words)             # only the instruction itself is read out
            self.said = words
        elif not self.instructed and self.held is None:
            self.held = words              # commentary: said only if no instruction comes
        self.said = self.said or words
        if self._my_box():   # no WHAT line: use what she said
            self.refine(words)

    def finish_talking(self):
        """No instruction in this reply (an answer to a question): say what she said."""
        if not self.instructed and self.held and self.alive() and not self.kept:
            self.e.voice.say(self.held)

    def on_wait(self, mode):
        self.ended = True
        if self.said and self._my_box():
            self.e.last_what = self.what or self.said
        self.e._log_step(self.summary())
        self.e.waiting = mode if self.e.box or mode == "next" else "next"

    def on_plan(self, text):
        self.e._set_plan(text)

    def on_why(self, text):
        """Eris Unity: why the step works. Shown, kept in your notebook, and read out after
        the instruction."""
        e = self.e
        e.ui.log("hint", f"Why:  {text}")
        lesson = (e.task or {}).get("lesson") or course.current()
        if config.MODE == "unity" and lesson:
            course.note(lesson, text)
            e.ui.cmd("lesson")             # the lesson bar shows NOTES once there are some
        if config.MODE == "unity" and self.instructed:
            e.voice.say(text)

    def on_keep(self, _):   # KEEP after other lines: wait for you to press Next
        self.on_wait("next")

    def on_done(self, _):
        e = self.e
        self.ended = True
        e._finish_task()
        e.waiting = e.box = e.track = None
        e.ui.cmd("clear_box")
        e.ui.cmd("state", "ready")
        e.steps = 0

    def _check_element(self, text):
        """She picked a number from the list but names something else ("Click Show more
        images" with the number of a browser tab): point at the element with that name."""
        n, els = self.element_n, self.shot.elements
        if not n or n > len(els):
            return
        low = text.lower()
        picked = (els[n - 1].get("name") or "").strip().lower()
        if picked and picked in low:
            self.element_n = None            # it is the one she means
            return
        named = [(len(name), i) for i, el in enumerate(els, 1)
                 for name in [(el.get("name") or "").strip().lower()] if len(name) >= 6 and name in low]
        if not named:
            return
        better = max(named)[1]
        box, _ = snap.element(self.shot, better)
        if box and better != n and self._my_box():
            from .uia import TYPE_NAMES
            self.e.ui.log("debug", f"box: she said {text!r} but picked {n} ({picked!r}); using {better}")
            self._show(box, TYPE_NAMES.get(els[better - 1].get("type")))
        self.element_n = None

    def summary(self):
        """This step in a few words, for a recipe: "Click Add Component (the blue Add
        Component button) - type rigidbody"."""
        if not self.said:
            return ""
        s = self.said + (f" ({self.what})" if self.what else "")
        if self.typed:
            s += f" - type {self.typed}"
        if self.key:
            s += f" - press {self.key}"
        if self.dragged:
            s += " - drag it to the drop target"
        return s

    # ---- the box ----
    def _show(self, box, kind=None):
        e = self.e
        e.box = self.final = box
        e.track = None
        e.box_gen = self.my
        e.ui.log("debug", f"box shown at {box}")
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
