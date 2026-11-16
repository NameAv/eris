"""The real window, driven like a person would: chat, talking, calling, settings, the
test-lab button, the watcher and the red box. Needs a screen (on Linux: xvfb-run)."""
import json
import os
import sys
import threading
import time
import tkinter as tk

from helpers import LineStream, check, done

import eris.core as core
from eris import bench, brain, config, settings

log = []


class FakeEars:
    def start(self):
        log.append("rec")

    def abort(self):
        log.append("abort")

    def stop_and_transcribe(self):
        log.append("transcribe")
        return ""


class FakeCall:
    def __init__(self, *a, **k):
        pass

    def start(self):
        log.append("call-start")

    def stop(self):
        log.append("call-stop")


core.Eris._load_ears = lambda self: (setattr(self, "ears", FakeEars()), self.ui.cmd("state", "ready"))
import eris.ears  # noqa: E402
eris.ears.Call = FakeCall
import eris.speech  # noqa: E402
eris.speech.Voice._sapi_loop = lambda self: None
config.API_KEY, config.VOICE_ON = "sk-ant-test", False
config.THEME = os.environ.get("ERIS_THEME", "crimson")     # run_all tries every look

REPLIES = []


def scripted_turn(self, shot, text, on_event, alive):
    reply = REPLIES.pop(0) if REPLIES else "NOBOX\nSAY Okay.\nDONE"
    for ev in LineStream().feed((reply(shot) if callable(reply) else reply) + "\n"):
        on_event(ev)


brain.Brain.turn = scripted_turn
core.locate = lambda *a: None

from eris.app import App  # noqa: E402

app = App()
app.geometry("480x760+0+0")
STEPS = []


def step(ms):
    def add(fn):
        STEPS.append((ms, fn))
        return fn
    return add


def run_steps(i=0):
    if i >= len(STEPS):
        if config.THEME == "neon":
            check("Neon: the banner is animating", app.banner is not None and app.banner.frames > 20,
                  getattr(app.banner, "frames", None))
        errors = [l for l in settings.folder().joinpath("eris.log").read_text(encoding="utf-8").splitlines()
                  if "window couldn't do" in l or "[error]" in l] if settings.folder().joinpath("eris.log").exists() else []
        check("the window logged no errors", not errors, errors[:3])
        app.destroy()
        return
    ms, fn = STEPS[i]
    try:
        fn()
    except Exception as e:
        check(f"step {fn.__name__} ran", False, repr(e))
    app.after(ms, lambda: run_steps(i + 1))


@step(300)
def welcome():
    check("welcome greeting shown", app.welcome is not None and app.welcome.winfo_exists())
    app.update()
    right = app.winfo_rootx() + app.winfo_width()
    app._set_state("guiding")
    app.geometry("400x760")       # the narrowest the window goes
    app.update()
    check("the status chip isn't cut off in a narrow window",
          app.chip_text.winfo_width() >= app.chip_text.winfo_reqwidth() - 2, (app.chip_text.winfo_width(), app.chip_text.winfo_reqwidth()))
    app.geometry("480x760")
    app._set_state("ready")
    app.update()
    right = app.winfo_rootx() + app.winfo_width()
    check("all four step buttons fit in the window",
          all(b.winfo_rootx() + b.winfo_width() <= right for b in app.ctl_row.winfo_children()),
          [(b.cget("text"), b.winfo_rootx() + b.winfo_width(), right) for b in app.ctl_row.winfo_children()])
    check("talk button says click to call / hold to talk", "Click to call" in app.mic.cget("text"))


@step(400)
def push_to_talk_down():
    from pynput import keyboard
    app.eris.on_press(keyboard.Key.f8)


@step(400)
def push_to_talk_up():
    from pynput import keyboard
    check("F8 down: listening", app.eris.talking and app.chip_text.cget("text") == "Listening")
    app.eris.on_release(keyboard.Key.f8)


@step(300)
def after_talk():
    check("F8 up: transcribed", "transcribe" in log and not app.eris.talking)
    app._mic_down()
    app.after(60, app._mic_up)


@step(400)
def call_started():
    check("a click on the button starts a call", app.eris.on_call and "On a call" in app.mic.cget("text"))
    app._mic_down()
    app.after(60, app._mic_up)


@step(400)
def call_ended():
    check("a second click hangs up", not app.eris.on_call and "Click to call" in app.mic.cget("text"))
    REPLIES.append("NOBOX\nSAY On it! Click the address bar at the very top.\nSAY Then type wikipedia.\nWAIT next")
    app.eris.ask("take me to wikipedia")


@step(600)
def chat():
    check("asking hides the welcome", app.welcome is None)
    texts = [b.cget("text") for b in app.bubbles if b.winfo_exists()]
    check("your question and her answer are in the chat",
          "take me to wikipedia" in texts and any("address bar" in t for t in texts))
    check("system notes stay out of the chat", not any("watching your screen" in t for t in texts))
    app.eris.new_task()


@step(400)
def new_task():
    check("New task clears the chat and brings the welcome back", app.welcome is not None and not app.bubbles)
    app.open_settings()
    app._settings.geometry("800x620+500+40")


@step(500)
def settings_pages():
    w = app._settings
    for page in ["brain", "voice", "guiding", "privacy", "eris", "keys", "app"]:
        w.show(page)
        w.update()
    check("every settings page builds", True)
    w.show("brain")
    w.set(BRAIN="local")
    w.show("brain")
    check("brain choice saved", json.loads(settings.FILE.read_text())["BRAIN"] == "local"
          and hasattr(w, "ollama_status") and w.ollama_status.winfo_exists())
    w.set(BRAIN="claude")
    w.show("keys")
    w.update()
    w._start_capture("TALK_KEY")
    check("hotkeys paused while choosing a key", app.eris.hotkeys_paused)
    w.event_generate("<KeyPress>", keysym="a")
    w.event_generate("<KeyPress>", keysym="F7")
    w._start_capture("NEXT_KEY")
    w.event_generate("<KeyPress>", keysym="F7")
    check("letters refused, F7 taken, a used key swaps",
          config.TALK_KEY == "f9" and config.NEXT_KEY == "f7")
    w._start_capture("CANCEL_KEY")
    w.event_generate("<KeyPress>", keysym="Escape")
    check("Esc cancels", config.CANCEL_KEY == "f10")


@step(500)
def settings_more():
    w = app._settings
    check("hotkeys back on after choosing", not app.eris.hotkeys_paused)
    w.set(USER_NAME="Sam", VIBE="cheeky")
    check("name and vibe go into her instructions",
          "Their name is Sam" in brain.memory_text() and "cheeky" in brain.memory_text())
    w.show("privacy")
    w.set(PRIVATE_APPS=config.PRIVATE_APPS + ["My Bank"])
    w._fill_apps()
    check("an app is added to the never-look list", "My Bank" in json.loads(settings.FILE.read_text())["PRIVATE_APPS"])
    w.show("app")
    w._reset()
    w._reset()
    check("reset restores defaults but keeps the key", config.TALK_KEY == "f8" and config.VIBE == "friendly"
          and "My Bank" not in config.PRIVATE_APPS and config.API_KEY == "sk-ant-test")
    run_all = bench.run_all
    bench.run_all = lambda brain=None, progress=print, tests=None: run_all(
        type("Echo", (), {"history": [], "turn": lambda s, shot, text, on_event, alive:
                          [on_event(e) for e in LineStream().feed("NOBOX\nSAY Hello?\nDONE\n")]})(),
        progress, bench.TESTS[:2])
    w._run_bench()


@step(3000)
def lab_button():
    w = app._settings
    check("the Run the tests button finishes with a report",
          w.bench_status.cget("text").startswith("Passed")
          and any(settings.folder().joinpath("tests").glob("report-*.md")))
    w.destroy()
    # a fake browser for the watcher and the red box (drawn before she looks at it)
    global browser
    browser = tk.Toplevel(app)
    browser.geometry("760x500+560+140")
    browser.configure(bg="white")
    bar = tk.Frame(browser, bg="white", highlightbackground="#bbbbbb", highlightthickness=1)
    bar.place(x=40, y=30, width=640, height=30)


@step(1500)
def ask_with_sloppy_box():
    REPLIES.append(lambda shot: f"BOX {590 / shot.sx} {162 / shot.sy} {1252 / shot.sx} {208 / shot.sy}\n"
                                "WHAT the address bar\nTYPE wikipedia\nSAY Type wikipedia.\nWAIT next")
    REPLIES.append("BOX 10 10 20 20\nSAY Click the result titled Wikipedia.\nWAIT click")
    app.eris.ask("take me to wikipedia")


@step(4500)    # give the watcher time to see the change, let it settle, and look again
def box_snaps_and_hint():
    ov = app.overlay
    x1, y1, x2, y2 = app.eris.box or (0, 0, 0, 0)
    p = config.BOX_PADDING
    check("a sloppy box snaps onto the address bar", abs(x1 + p - 600) <= 3 and abs(y1 + p - 170) <= 3
          and abs(x2 - p - 1240) <= 3 and abs(y2 - p - 200) <= 3, app.eris.box)
    check("what to type shows inside the box", ov.hint == "type:  wikipedia")
    for i in range(6):          # the page "loads"
        tk.Label(browser, text=f"Wikipedia - result {i}", bg="white", fg="#1a0dab",
                 font=("DejaVu Sans", 16)).place(x=20, y=90 + i * 34)


@step(300)
def watcher_reacts():
    check("the watcher noticed the page load and looked again", app.eris.waiting == "click")


@step(500)
def ask_about_a_button():
    target = tk.Label(browser, text="   Add Component   ", bg="#1a73e8", fg="white",
                      font=("DejaVu Sans", 16, "bold"))
    target.place(x=300, y=400)
    browser.update()
    x, y, w, h = target.winfo_rootx(), target.winfo_rooty(), target.winfo_width(), target.winfo_height()
    REPLIES.append(lambda shot: f"BOX {(x - shot.left) / shot.sx} {(y - shot.top) / shot.sy} "
                                f"{(x + w - shot.left) / shot.sx} {(y + h - shot.top) / shot.sy}\n"
                                "WHAT the Add Component button\nSAY Click Add Component.\nWAIT click")
    app.eris.ask("add a component")


@step(1200)
def move_the_window():
    global before
    check("she's ready to follow the button", app.eris.track is not None, app.eris.box)
    before = app.eris.box
    browser.geometry("760x500+520+40")       # you drag the window up and left


@step(300)
def box_followed():
    after = app.eris.box or (0, 0, 0, 0)
    check("the box followed its button when the window moved",
          before and abs(after[0] - (before[0] - 40)) <= 2 and abs(after[1] - (before[1] - 100)) <= 2,
          (before, after))
    check("...without asking the AI again", not REPLIES and app.eris.waiting == "click")
    check("Wrong box button works while a box is up", app.wrong_btn.cget("state") == "normal")
    app.wrong_btn.invoke()


@step(800)
def wrong_box_pressed():
    check("Wrong box: she looked again and the button went quiet",
          app.wrong_btn.cget("state") == "disabled" and app.eris.box is None)


@step(300)
def extras_on_screen():
    ov = app.overlay
    placed, real = {}, ov._place
    ov._place = lambda win, x, y, w, h: (placed.__setitem__(win, (x, y)), real(win, x, y, w, h))
    first = ov.variant
    ov.box(600, 200, 800, 240)
    check("each new box takes the next version of its shape", ov.variant == (first + 1) % 3)
    ov.drop(900, 500, 1100, 540)
    check("a drag shows the drop box", ov.drop_rect == (900, 500, 1100, 540)
          and placed.get(ov.drop_bars[0]) == (897, 497))
    ov.move_box(600, 100, 800, 140)
    check("...and it stays put when the dragged thing's box follows a scroll", ov.drop_rect == (900, 500, 1100, 540))
    ov.clear_box()
    ov.scroll_hint("down", 0, 0, 1440, 900)
    check("scroll note near the bottom middle", placed[ov.note][1] > 700 and 500 < placed[ov.note][0] < 720
          and "scroll down" in ov.note_label.cget("text"), placed[ov.note])
    ov.badge("press  Ctrl + S", 0, 0, 1440, 900)
    check("key badge near the top", 0 < placed[ov.note][1] < 200 and "Ctrl + S" in ov.note_label.cget("text"))
    ov.clear_box()
    check("clearing the box clears them all", ov.drop_rect is None and ov.extras_timer is None)
    ov._place = real


if os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
    # Real mouse clicks (only on a virtual screen, so a real mouse is never moved).
    @step(300)
    def real_clicks():
        from pynput.mouse import Button, Controller
        app.update()
        pos = (app.mic.winfo_rootx() + app.mic.winfo_width() // 2, app.mic.winfo_rooty() + 26)
        log.clear()

        def click():
            m = Controller()
            m.position = pos
            time.sleep(0.05)
            m.press(Button.left)
            time.sleep(0.1)
            m.release(Button.left)
        threading.Thread(target=click, daemon=True).start()

    @step(300)
    def real_click_result():
        check("a real mouse click on the button's words starts a call", app.eris.on_call)
        app.eris.stop_call()

app.after(800, run_steps)
app.mainloop()
done("window")
