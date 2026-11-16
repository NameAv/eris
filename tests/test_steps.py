"""Eris's step logic: boxes, clicks, automatic looks, privacy, hotkeys."""
import threading
import time

from helpers import Event, check, done, fake_shot, make_eris, wait_for


def test_click_box_moves_on():
    e, ui, _ = make_eris()
    e.brain.script = ["BOX 100 100 200 130\nSAY Click Add Component.\nWAIT click",
                      "NOBOX\nSAY Done!\nDONE"]
    e.ask("add a rigidbody")
    wait_for(lambda: e.waiting == "click")
    check("box shown in screen coords", e.box == (200, 200, 400, 260))
    e.on_click(50, 50, None, True)
    time.sleep(0.15)
    check("a click outside the box is ignored", len(e.brain.asked) == 1)
    e.on_click(300, 230, None, True)
    check("a click inside clears the box at once", wait_for(lambda: e.box is None, 0.5))
    wait_for(lambda: len(e.brain.asked) == 2)
    check("then she takes a fresh look", e.brain.asked[1].startswith("I did that step"))
    check("and the task ends on DONE", wait_for(lambda: e.waiting is None))


def test_click_while_she_talks():
    e, _, _ = make_eris()
    e.brain.gate = threading.Event()
    e.brain.script = [[Event("box", (100, 100, 200, 130)), Event("say", "Click it."), "PAUSE",
                       Event("wait", "click")], "NOBOX\nSAY Done.\nDONE"]
    e.ask("go")
    wait_for(lambda: e.box is not None)
    e.on_click(300, 230, None, True)            # mid-sentence
    time.sleep(0.1)
    e.brain.gate.set()
    check("an early click on the box still moves on",
          wait_for(lambda: len(e.brain.asked) == 2 and e.brain.asked[1].startswith("I did")))


def test_loading_page_keep():
    e, _, _ = make_eris()
    e.brain.script = ["BOX 100 100 200 130\nSAY Click it.\nWAIT click", "KEEP"]
    e.ask("go")
    wait_for(lambda: e.waiting == "click")
    e.on_click(300, 230, None, True)
    wait_for(lambda: len(e.brain.asked) == 2)
    check("a still-loading page: she waits instead of stalling", wait_for(lambda: e.waiting == "next"))


def test_automatic_looks():
    e, ui, _ = make_eris()
    e.brain.script = ["BOX 100 10 300 30\nTYPE wikipedia\nSAY Type wikipedia and press Enter.\nWAIT next",
                      "KEEP",
                      [Event("fail", "I couldn't reach my brain just now.")],
                      "BOX 50 200 400 230\nSAY Click the result titled Wikipedia.\nWAIT click"]
    e.ask("take me to wikipedia")
    wait_for(lambda: e.waiting == "next")
    check("TYPE goes inside the box", ("type_hint", "wikipedia") in ui.cmds)
    check("no caption bubble", not any(c[0] == "caption" for c in ui.cmds))
    e.auto_look()
    wait_for(lambda: len(e.brain.asked) == 2 and not e.busy)
    check("KEEP keeps the box and the step", e.box == (200, 20, 600, 60) and e.waiting == "next")
    e.auto_look()
    wait_for(lambda: len(e.brain.asked) == 3 and not e.busy)
    check("a network hiccup during a look is silent", e.waiting == "next"
          and "I couldn't reach my brain just now." not in e.voice.said)
    e.auto_look()
    wait_for(lambda: e.waiting == "click")
    check("a new step replaces the box", e.box == (100, 400, 800, 460))


def test_errors_are_said():
    e, ui, _ = make_eris()
    e.brain.script = [[Event("fail", "My API key isn't working.")]]
    e.ask("hi")
    check("a real error is said out loud", wait_for(lambda: "My API key isn't working." in e.voice.said))


def test_element_box_is_exact():
    els = [{"type": 50005, "name": "Wikipedia", "rect": (200, 600, 380, 630)}]
    e, ui, _ = make_eris(fake_shot(elements=els))
    import eris.core as core
    refined = []
    core.locate = lambda *a: refined.append(1)
    e.brain.script = ["ELEMENT 1\nWHAT the Wikipedia link\nSAY Click Wikipedia.\nWAIT click"]
    e.ask("take me to wikipedia")
    wait_for(lambda: e.waiting == "click")
    time.sleep(0.1)
    check("ELEMENT n uses the exact rectangle", e.box == (196, 596, 384, 634))
    check("...with no extra AI pass", not refined)


def test_privacy_look_away():
    e, ui, _ = make_eris()
    import eris.core as core
    shots = []
    core.Eris._shoot = lambda self: shots.append(1)
    core.privacy.should_look_away = lambda: "you're typing something private"
    e.ask("log me in")
    wait_for(lambda: e.waiting == "next")
    check("no screenshot while typing a secret", not shots and not e.brain.asked)
    check("she says she's looking away", any("look away" in s for s in e.voice.said))
    core.privacy.should_look_away = lambda: ""


def test_key_filter():
    from pynput import keyboard
    import queue
    e, _, _ = make_eris()
    e.inbox = queue.Queue()
    kc = keyboard.KeyCode.from_char
    for k in [kc("h"), kc("2"), keyboard.Key.space, keyboard.Key.shift, keyboard.Key.backspace]:
        e.on_press(k)
        e.on_release(k)
    check("typed keys never get past the hook", e.inbox.empty())
    e.on_press(keyboard.Key.f8)
    e.on_press(keyboard.Key.enter)
    check("hotkeys and Enter do", e.inbox.qsize() == 2)


def test_preshot_only_for_its_question():
    import eris.core as core
    e, _, _ = make_eris()
    made = []

    def shoot(self):
        made.append(object())
        return made[-1]
    core.Eris._shoot = shoot
    e.pre_token = tok = object()
    e._prepare_shot(tok)
    check("a fresh pre-screenshot is used for its question", e._take_shot(allow_pre=True) is made[0])
    e.pre_token = tok = object()
    own = e._take_shot(allow_pre=True)
    e._prepare_shot(tok)                       # arrives too late
    check("a late one is dropped", e.pre_shot is None)
    check("and never reused for a later step", e._take_shot() not in (own, made[1]))


for name, fn in list(globals().items()):
    if name.startswith("test_"):
        fn()
done("steps")
