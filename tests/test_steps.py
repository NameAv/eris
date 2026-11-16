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


def test_box_follows_its_button():
    from PIL import Image, ImageDraw
    from eris import config
    shot = fake_shot()
    shot.full = Image.new("RGB", (shot.width, shot.height), "white")
    ImageDraw.Draw(shot.full).rounded_rectangle((204, 204, 396, 256), 6, fill="#1a73e8")
    ImageDraw.Draw(shot.full).text((230, 222), "Add Component", fill="white")
    config.REFINE = False
    e, ui, _ = make_eris(shot)
    e.brain.script = ["BOX 100 100 200 130\nTYPE rigid\nSAY Click Add Component.\nWAIT click"]
    e.ask("add a rigidbody")
    check("once the step is set, the box can follow its button",
          wait_for(lambda: e.track is not None) and e.track.box == tuple(e.box))
    old = e.box
    moved = (old[0], old[1] - 120, old[2], old[3] - 120)
    e.follow(moved)
    check("following moves the box on screen", e.box == moved and ("move_box", *moved) in ui.cmds)
    e._clear()
    check("a cleared box stops tracking", e.track is None)
    e._busy = 1
    e.box = old
    e.follow(moved)
    check("no following while she's working on a new step", e.box == old)
    e._busy = 0
    config.TRACK = False
    e._start_tracking(shot, old)
    check("switched off in Settings: no tracking", e.track is None)
    config.TRACK, config.REFINE = True, True


def test_drag_scroll_and_keys():
    e, ui, shot = make_eris()
    e.brain.script = ["BOX 100 100 200 130\nTO 600 400 700 440\nSAY Drag it onto the Player.\nWAIT next",
                      "NOBOX\nSCROLL down\nSAY It's further down.\nWAIT next",
                      "NOBOX\nKEY ctrl+s\nSAY Press Ctrl and S.\nDONE",
                      "BOX 100 100 200 130\nKEY enter\nSAY Then press Enter.\nWAIT next"]
    e.ask("put my script on the player")
    check("a drag shows where to drop it", wait_for(lambda: ("drop", 1200, 800, 1400, 880) in ui.cmds), ui.cmds[-4:])
    e.ask("where do foxes live")
    check("scroll arrow at the edge of what she saw",
          wait_for(lambda: ("scroll_hint", "down", 0, 0, shot.width, shot.height) in ui.cmds))
    e.ask("how do i save")
    check("a shortcut with no box: a big badge", wait_for(lambda: ("badge", "press  Ctrl + S", 0, 0,
                                                                     shot.width, shot.height) in ui.cmds))
    e.ask("search")
    check("a key with a box: shown inside it", wait_for(lambda: ("type_hint", "Enter", "press:  ") in ui.cmds))


def test_box_knows_what_it_points_at():
    shot = fake_shot(elements=[{"type": 50000, "name": "Add Component", "rect": (1200, 560, 1640, 608)},
                               {"type": 50004, "name": "Search", "rect": (1180, 640, 1660, 688)}])
    e, ui, _ = make_eris(shot)
    e.brain.script = ["ELEMENT 1\nSAY Click Add Component.\nWAIT click", "ELEMENT 2\nTYPE rigid\nSAY Type rigid.\nWAIT next"]
    e.ask("add a component")
    check("a button from Windows' list: the box knows it's a button",
          wait_for(lambda: any(c[0] == "box" and c[-1] == "button" for c in ui.cmds)))
    e.ask("search")
    check("...and a text box is a text box", wait_for(lambda: any(c[0] == "box" and c[-1] == "text box" for c in ui.cmds)))


def test_recipes():
    from eris import recipes
    recipes.forget()
    shot = fake_shot()
    shot.app = {"name": "Unity", "title": "MyGame - Unity", "hwnd": 1}
    e, _, _ = make_eris(shot)
    e.brain.script = ["ELEMENT 1\nSAY Click Player in the Hierarchy.\nWAIT click",
                      "BOX 10 10 50 30\nWHAT the Add Component button\nSAY Click Add Component.\nWAIT click",
                      "BOX 10 10 50 30\nTYPE rigidbody\nSAY Type rigidbody.\nWAIT next",
                      "NOBOX\nSAY Done, it has a Rigidbody now!\nDONE"]
    shot.elements = [{"type": 50000, "name": "Player", "rect": (20, 20, 120, 40)}]
    e.ask("how do I add a rigidbody to my player")
    for _ in range(3):
        wait_for(lambda: e.waiting is not None)
        e.advance()
        time.sleep(0.15)
    wait_for(lambda: e.task is None)
    saved = recipes.load()
    check("a finished task is kept as a recipe", len(saved) == 1 and len(saved[0]["steps"]) == 3
          and "Add Component" in saved[0]["steps"][1] and "type rigidbody" in saved[0]["steps"][2], saved)
    e.brain.script = ["NOBOX\nSAY Sure.\nDONE"]
    e.ask("add a rigidbody to the player please")
    check("a similar request gets the steps that worked", wait_for(lambda: len(e.brain.notes) >= 5)
          and "these steps worked" in e.brain.notes[-1] and "Add Component" in e.brain.notes[-1])
    e.brain.script = ["NOBOX\nSAY Sure.\nDONE"]
    e.ask("make the camera follow the player")
    check("...but not a different one", wait_for(lambda: len(e.brain.notes) >= 6) and "worked" not in e.brain.notes[-1])
    recipes.forget()
    e.brain.script = ["BOX 10 10 50 30\nSAY Click this.\nWAIT click", "BOX 60 60 90 90\nSAY Sorry, this.\nWAIT click",
                      "BOX 10 10 50 30\nSAY Now this.\nWAIT click", "NOBOX\nSAY Done.\nDONE"]
    e.ask("open the lighting settings")
    wait_for(lambda: e.waiting == "click")
    e.wrong_box()
    for _ in range(2):
        wait_for(lambda: e.waiting is not None and not e.busy)
        e.advance()
        time.sleep(0.15)
    wait_for(lambda: e.task is None)
    check("a task where you pressed Wrong box isn't kept", not recipes.load())


def test_learning_from_experience():
    from eris import experience, recipes
    experience.forget()
    recipes.forget()
    shot = fake_shot()
    shot.app = {"name": "Unity", "title": "MyGame - Unity", "hwnd": 1}
    e, ui, _ = make_eris(shot)
    e.brain.script = ["BOX 10 10 50 30\nWHAT Rigidbody 2D\nSAY Click Rigidbody 2D.\nPLAN Select Player | Add Component | Pick Rigidbody\nWAIT click",
                      "BOX 60 60 90 90\nWHAT Rigidbody\nSAY Sorry, this one: Rigidbody.\nWAIT click",
                      "NOBOX\nSAY Done!\nDONE"]
    e.ask("add a rigidbody to my player")
    check("her plan shows in the chat", wait_for(lambda: any(l[0] == "hint" and "1. Select Player" in l[1] for l in ui.logs)))
    check("...with the step you're on", wait_for(lambda: any(l[0] == "info" and l[1].startswith("Step 1 of 3") for l in ui.logs)))
    wait_for(lambda: e.waiting == "click")
    e.wrong_box()
    wait_for(lambda: e.waiting == "click" and e.last_what == "Rigidbody" and not e.busy)
    e.advance()
    wait_for(lambda: e.task is None)
    e.brain.script = ["NOBOX\nSAY Sure.\nDONE"]
    e.ask("add a rigidbody to the enemy")
    check("a mix-up you corrected becomes a lesson for next time",
          wait_for(lambda: len(e.brain.notes) >= 4)
          and "not Rigidbody 2D, the right one was Rigidbody" in e.brain.notes[-1], e.brain.notes[-1:])
    for _ in range(experience.AT_HOME):
        experience.finished("Unity")
    check("where you're at home, she skips the basics", "skip the very basics" in experience.notes("Unity", "x"))
    check("...but not in other apps", experience.notes("Blender", "x") == "")
    for _ in range(2):
        recipes.remember("open the lighting window", "Unity", ["Click Window", "Click Rendering > Lighting"])
    check("a task done again and again: she keeps it brief",
          "keep it brief" in recipes.describe(recipes.find("open the lighting window", "Unity"), 1))
    experience.forget()
    recipes.forget()


def test_no_new_look_while_she_talks():
    e, _, _ = make_eris()
    e.waiting, e.mon = "next", (0, 0, 100, 100)
    check("the watcher may look when she's quiet", e.watcher._ready())
    e.voice.busy = lambda: True
    check("...but waits while she's still talking", not e.watcher._ready())


def test_checking_a_step():
    import numpy as np
    e, ui, _ = make_eris()
    screens = {"now": np.zeros((180, 320), dtype=np.int16)}
    e.watcher.look = lambda: screens["now"].copy()
    e.brain.script = ["BOX 100 100 200 130\nSAY Click it.\nWAIT click",
                      "BOX 300 300 400 330\nSAY Next, this.\nWAIT click",
                      "NOBOX\nSAY Done.\nDONE"]
    e.ask("go")
    wait_for(lambda: e.waiting == "click" and e.check is not None)
    e.on_click(300, 230, None, True)                 # a click that changes nothing
    check("a click that changed nothing: the box comes back, no AI needed",
          wait_for(lambda: any("another click" in l[1] for l in ui.logs if l[0] == "eris"), 4)
          and e.box == (200, 200, 400, 260) and e.waiting == "click" and len(e.brain.asked) == 1)
    e.on_click(300, 230, None, True)                 # still nothing: now she looks properly
    check("...a second time, she looks, told nothing changed",
          wait_for(lambda: len(e.brain.asked) == 2, 4) and "nothing on the screen changed" in e.brain.notes[-1])
    wait_for(lambda: e.waiting == "click" and e.check is not None)
    screens["now"] = np.full((180, 320), 200, dtype=np.int16)     # the click opened something big
    e.on_click(700, 630, None, True)
    check("a click that changed a lot: she's told so", wait_for(lambda: len(e.brain.asked) == 3, 3)
          and "a lot of the screen changed" in e.brain.notes[-1])


def test_wrong_box():
    from PIL import Image
    from eris import settings
    shot = fake_shot()
    shot.full = Image.new("RGB", (shot.width, shot.height), "white")
    e, _, _ = make_eris(shot)
    e.wrong_box()
    check("Wrong box with no box: nothing happens", not e.brain.asked)
    e.brain.script = ["BOX 100 100 200 130\nSAY Click the ad.\nWAIT click",
                      "BOX 300 300 400 330\nSAY Sorry, it's this one.\nWAIT click"]
    e.ask("find wikipedia")
    wait_for(lambda: e.waiting == "click")
    e.wrong_box()
    check("Wrong box: she looks again, told the last one was wrong",
          wait_for(lambda: len(e.brain.asked) == 2) and e.brain.asked[1].startswith("That box was on the wrong"))
    check("...and points somewhere new", wait_for(lambda: e.box == (600, 600, 800, 660)))
    folder = settings.folder() / "mistakes"
    check("the mistake is kept on your PC for the test lab",
          wait_for(lambda: any(folder.glob("*.jpg")) and any(folder.glob("*.json"))))


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
