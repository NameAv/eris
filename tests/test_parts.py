"""The smaller parts: reply parsing, numbered lists, reading words, snapping boxes,
watching the screen, hearing speech, safe updates, the saved key and privacy."""
import io
import threading
import time
import types
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from helpers import check, done, fake_shot

from eris import config


def _font(size):
    for name in ("DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def test_protocol():
    from eris.protocol import LineStream, parse_line
    evs = []
    ls = LineStream()
    for chunk in ["BOX 10 2", "0 110 40\nSAY Click Add", " Component.\nWAIT cl", "ick"]:
        evs += ls.feed(chunk)
    evs += ls.flush()
    check("lines are parsed as they stream in", [(e.kind, e.value) for e in evs] == [
        ("box", (10, 20, 110, 40)), ("say", "Click Add Component."), ("wait", "click")])
    cases = {"ELEMENT 7": ("element", 7), "ELEMENT [12]": ("element", 12), "KEEP": ("keep", None),
             'TYPE "wikipedia"': ("type", "wikipedia"), "WHAT the button": ("what", "the button"),
             "AVATAR": ("avatar", None), "REMEMBER I like red": ("remember", "I like red"),
             "```": None, "ELEMENT foo": None}
    ok = all((parse_line(k) and (parse_line(k).kind, parse_line(k).value)) == v or (v is None and parse_line(k) is None)
             for k, v in cases.items())
    check("every reply line kind", ok)


def test_new_lines():
    from eris.protocol import parse_line
    check("KEY: shortcuts written nicely", parse_line("KEY ctrl+shift+s").value == "Ctrl + Shift + S")
    check("SCROLL: the way to go", parse_line("SCROLL up").value == "up" and parse_line("SCROLL").value == "down"
          and parse_line("SCROLL sideways").value == "down")
    check("TO: drop on an element or a box", parse_line("TO ELEMENT 7").value == 7
          and parse_line("TO 30 40 10 20").value == (10, 20, 30, 40))
    check("TO with nothing usable is skipped", parse_line("TO the player") is None)
    from eris import glowbox
    img, x, y = glowbox.render_drop((100, 100, 200, 140), (600, 400, 700, 440))
    check("a drag draws one picture covering both boxes",
          x < 100 and y < 100 and x + img.width > 700 and y + img.height > 440)
    check("scroll / key notes draw", glowbox.render_note("scroll down", "down").width
          > glowbox.render_note("scroll down").width - 1)


def test_looks():
    from eris import glowbox, theme
    theme.apply("neon")
    check("Neon look: black, neon red, sharp corners",
          theme.NAME == "neon" and theme.BG == "#040102" and theme.r(26) == 3 and theme.STATES["guiding"][1] == "#ff2236")
    theme.apply("crimson")
    check("...and back to Crimson exactly", theme.BG == "#0d0809" and theme.r(26) == 26)
    theme.apply("something else")
    check("an unknown look falls back to Crimson", theme.NAME == "crimson")
    banner = theme.streaks(480, 28)
    px = np.asarray(banner)
    check("light-streak banner: mostly dark, with red streaks",
          px.mean() < 60 and (px[..., 0] > 150).mean() > 0.02 and px[..., 0].mean() > px[..., 2].mean() * 2)
    hud = glowbox.render(200, 40, style="neon")
    round_ = glowbox.render(200, 40, style="glow")
    check("Neon HUD box: cut corners and tabs (not the rounded box)",
          np.asarray(hud).shape == np.asarray(round_).shape and not np.array_equal(np.asarray(hud), np.asarray(round_)))


def test_hud_shapes():
    from eris import config, glowbox, hud
    check("small square things get the ring", hud.shape_for(38, 32) == "ring")
    check("long thin things get the bar", hud.shape_for(400, 36) == "bar")
    check("ordinary things get the frame", hud.shape_for(140, 40) == "frame")
    check("big things get the panel", hud.shape_for(600, 400) == "panel")
    check("a wide button is still a button (frame), a short field still a field (bar)",
          hud.shape_for(228, 32, "button") == "frame" and hud.shape_for(120, 30, "text box") == "bar")
    check("a big picture gets the panel", hud.shape_for(240, 160, "image") == "panel")
    config.BOX_STYLE = "neon"
    for w, h in [(38, 32), (400, 36), (140, 40), (600, 400)]:
        img = glowbox.render(w, h, "rigid")
        a = np.asarray(img)[..., 3]
        edge = max(a[0].max(), a[-1].max(), a[:, 0].max(), a[:, -1].max())
        if edge > 40 or a.max() < 200:
            check(f"HUD box {hud.shape_for(w, h)} fits its picture", False, (w, h, int(edge)))
            break
    else:
        check("every HUD shape fits its picture, with the hint", True)
    looks_ok, differ = True, True
    for w, h in [(38, 32), (400, 36), (140, 40), (600, 400)]:
        pics = [np.asarray(glowbox.render(w, h, variant=v)) for v in range(hud.VARIANTS)]
        differ &= not np.array_equal(pics[0], pics[1]) and not np.array_equal(pics[1], pics[2])
        for a in (p[..., 3] for p in pics):
            looks_ok &= max(a[0].max(), a[-1].max(), a[:, 0].max(), a[:, -1].max()) <= 40 and a.max() >= 200
    check("every shape comes in 3 versions that fit their pictures", looks_ok and differ)
    img, x, y = glowbox.render_drop((100, 600, 220, 630), (100, 100, 200, 124))
    check("HUD drag: one picture with room for the DROP HERE tab beside the target",
          x <= 100 and x + img.width >= 200 + 80)
    check("HUD notes draw", glowbox.render_note("scroll down", "down").width > glowbox.render_note("ok").width)
    typed = np.asarray(hud.label("rigidbody", 17, prefix="TYPE"))
    plain = np.asarray(hud.label("rigidbody", 17))
    check("what to type: the same red plate, with a small TYPE before the word",
          typed.shape[1] > plain.shape[1] and typed.shape[0] == plain.shape[0])
    solid = tuple(int(v) for v in typed[typed.shape[0] // 2, 15])    # on the plate, before the text
    check("...a solid red plate, not a black one", solid[0] > 180 and solid[1] < 120 and solid[3] > 200, solid)
    note = np.asarray(glowbox.render_note("scroll down", "down"))
    check("notes use the same red plate", note.shape[0] == typed.shape[0])
    lines = [np.asarray(glowbox.render_drop((100, 600, 220, 630), (100, 100, 200, 124), v)[0]) for v in range(3)]
    check("three different drag lines", not np.array_equal(lines[0], lines[1]) and not np.array_equal(lines[1], lines[2]))
    check("...and each one is still (the same picture every time)",
          np.array_equal(lines[0], np.asarray(glowbox.render_drop((100, 600, 220, 630), (100, 100, 200, 124), 0)[0])))
    left = np.asarray(glowbox.render_drop((900, 300, 1000, 330), (100, 300, 200, 330), 2)[0])
    check("a drag to the left draws too", left[..., 3].max() > 200)
    config.BOX_STYLE = "glow"


def test_glitch_banner():
    from eris import config, glitch
    s = glitch.Streaks(480, 44)
    s.next_glitch = 1e12
    a, b = s.frame(1000.0), s.frame(1000.5)
    check("banner frames are the right size", a.shape == (44, 480, 3) and a.dtype == np.uint8)
    check("the streaks drift", not np.array_equal(a, b))
    calm = s.frame(2000.0)
    s.burst(2000.0, 0.3)
    check("a glitch changes the picture", not np.array_equal(calm, s.frame(2000.0)))
    def plain(t):
        return np.maximum(np.roll(s.far, -int(t * glitch.FAR_SPEED) % 480, axis=1),
                          np.roll(s.near, -int(t * glitch.NEAR_SPEED) % 480, axis=1)).astype(np.uint8)
    check("...and passes", np.array_equal(s.frame(2001.0), plain(2001.0)))
    config.GLITCH = False
    s.burst(3000.0, 0.3)
    check("Glitch effects off: just the drifting streaks", np.array_equal(s.frame(3000.0), plain(3000.0)))
    config.GLITCH = True
    wrap = np.asarray(__import__("eris.theme", fromlist=["streaks"]).streaks(300, 30), dtype=np.int16)
    check("the streaks wrap around seamlessly", np.abs(wrap[:, 0] - wrap[:, -1]).mean() < 25)


def test_elements_list():
    from eris import elements
    els = [{"type": 50005, "name": "Wikipedia", "rect": (200, 600, 380, 630)},
           {"type": 50004, "name": "", "rect": (100, 60, 1400, 100)},
           {"type": 50000, "name": "Off screen", "rect": (3000, 10, 3100, 40)},
           {"type": -1, "name": "Add", "rect": (10, 700, 40, 720), "src": "ocr"}]
    picked = elements.pick(els, (0, 0, 2560, 1440))
    check("list: on-monitor only, top to bottom", [e["name"] for e in picked] == ["", "Wikipedia", "Add"])
    shot = fake_shot(scale=2560 / 1400, w=1400, h=788)
    shot.sy = 1440 / 788
    text = elements.describe(picked, shot)
    check("list text the AI reads", '[2] link "Wikipedia" at 109,328 to 207,344' in text
          and '[3] text "Add"' in text)
    check("element number -> exact box", elements.rect(picked, 2) == (196, 596, 384, 634)
          and elements.rect(picked, 9) is None)


def test_reading_words():
    from eris import ocr
    menu = [("File", (12, 6, 40, 20)), ("Edit", (66, 6, 94, 20)), ("Assets", (120, 6, 168, 20))]
    button = [("Add", (1655, 284, 1683, 298)), ("Component", (1688, 284, 1760, 298))]
    para = [(w, (10 + i * 40, 500, 45 + i * 40, 514)) for i, w in
            enumerate("Wikipedia is a free online encyclopedia created and edited by volunteers".split())]
    items = ocr.group([menu, button, para])
    check("menu bar split, button kept whole, paragraph dropped",
          [i["name"] for i in items] == ["File", "Edit", "Assets", "Add Component"])
    uia = [{"type": 50000, "name": "Add Component", "rect": (1600, 280, 1820, 304)}]
    check("words already in Windows' list aren't repeated",
          [m["name"] for m in ocr.merge(uia, items)] == ["Add Component", "File", "Edit", "Assets"])


def _ui_image():
    img = Image.new("RGB", (1200, 700), "white")
    d = ImageDraw.Draw(img)
    f = _font(15)
    d.rounded_rectangle((100, 100, 260, 136), 6, fill="#1a73e8")
    d.text((128, 108), "Add Component", fill="white", font=f)
    d.text((100, 220), "Read more on ", fill="#222", font=f)
    d.text((205, 220), "Wikipedia", fill="#1a0dab", font=f)
    d.rectangle((100, 320, 600, 352), outline="#cfcfcf", fill="white")
    d.rectangle((700, 100, 900, 250), fill="#c0392b")
    return img, d.textbbox((205, 220), "Wikipedia", font=f)


def test_snapping():
    from eris import snap
    p = config.BOX_PADDING
    img, link = _ui_image()
    pad = lambda b: (b[0] - p, b[1] - p, b[2] + p, b[3] + p)

    def close(got, want, tol=3):
        return got is not None and all(abs(g - w) <= tol for g, w in zip(got, pad(want)))
    check("sloppy box snaps onto a button", close(snap.pixel_snap(img, pad((93, 108, 268, 130))), (100, 100, 261, 137)))
    check("onto a link inside a sentence", close(snap.pixel_snap(img, pad((199, 218, 285, 241))), link, 4))
    check("onto a text field's border", close(snap.pixel_snap(img, pad((96, 316, 606, 357))), (100, 320, 601, 353)))
    check("onto an image", close(snap.pixel_snap(img, pad((710, 92, 905, 258))), (700, 100, 901, 251)))
    check("a box on nothing is left alone", snap.pixel_snap(img, pad((400, 500, 500, 540))) is None)
    dark = Image.new("RGB", (1000, 500), "#383838")
    d = ImageDraw.Draw(dark)
    for i in range(4):
        d.rectangle((40 + i * 30, 150, 67 + i * 30, 172), fill="#4a4a4a")
    d.rounded_rectangle((300, 60, 520, 82), 3, fill="#585858")
    got = snap.pixel_snap(dark, pad((66, 146, 101, 170)))
    check("Unity's packed, low-contrast toolbar", got and abs(got[0] + p - 70) <= 1 and abs(got[2] - p - 98) <= 1)
    word = (360, 64, 460, 78)                      # a word read off a Unity button
    grown = snap.grow(dark, pad(word))
    check("a word's box grows to its button", grown and abs(grown[0] + p - 300) <= 2 and abs(grown[2] - p - 521) <= 2)
    check("a word on plain background stays as it is", snap.grow(img, pad(link)) is None)
    from eris import uia
    cands = [((0, 0, 1920, 1080), 50032), ((90, 80, 700, 400), 50026), ((101, 101, 259, 135), 50000)]
    check("Windows' element chosen by overlap and type",
          uia.best_match((100, 100, 260, 136), cands) == (101, 101, 259, 135)
          and uia.best_match((100, 100, 260, 136), [((0, 0, 1920, 1080), 50032)]) is None)


def test_watching():
    from eris import watcher as W
    W.threading = types.SimpleNamespace(Lock=threading.Lock, Thread=lambda **k: types.SimpleNamespace(start=lambda: None))
    w = W.Watcher(types.SimpleNamespace(waiting="next"))
    blank = np.zeros((W.TH, W.TW), np.int16)
    page = blank.copy()
    page[20:120, 20:300] = 200
    t = 100.0
    w._step(blank, t)
    quiet = []
    for i in range(6):
        t += .5
        quiet.append(w._step(blank, t))
    for i in range(3):                               # a few typed letters
        f = blank.copy()
        f[5:9, 30:40 + i * 12] = 255
        t += .5
        quiet.append(w._step(f, t))
    check("nothing changing / small typing: no look", not any(quiet))
    t += .5
    w._step(page, t)
    fires = []
    for i in range(6):
        t += .5
        fires.append(w._step(page, t))
    check("a page loads and settles: one look", fires.count(True) == 1)
    w2 = W.Watcher(types.SimpleNamespace(waiting="next"))
    rng = np.random.default_rng(0)
    looks, t = [], 1000.0
    while t < 1060:
        f = np.zeros((W.TH, W.TW), np.int16)
        f[rng.integers(0, 170):][:10, :] = 200
        if w2._step(f, t):
            looks.append(t)
            w2.rebase(0, kept=True)
            w2.base_after = 0
        t += .5
    check("a screen that never settles: fewer and fewer looks", len(looks) <= 3, looks)


def test_tracking():
    from eris import tracker
    W, H = 2560, 1440
    page = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)
    for i in range(12):                       # a list of results that look alike
        d.text((300, 200 + i * 90), f"Result number {i}: Wikipedia", fill="#1a0dab", font=_font(22))
    d.rounded_rectangle((900, 300, 1100, 344), 8, fill="#1a73e8")
    d.text((935, 308), "Add Component", fill="white", font=_font(20))
    p = config.BOX_PADDING
    button = (900 - p, 300 - p, 1100 + p, 344 + p)

    def shifted(dx, dy):
        out = Image.new("RGB", (W, H), "white")
        out.paste(page, (dx, dy))
        return tracker.grey(out)

    t = tracker.Tracker.make(page, 0, 0, button)
    check("a button gets a tracker", t is not None)
    check("unchanged screen: same spot", t.find(tracker.grey(page), 0, 0) == ("same", button))
    hover = page.copy()
    ImageDraw.Draw(hover).rounded_rectangle((900, 300, 1100, 344), 8, fill="#1765cc")
    ImageDraw.Draw(hover).text((935, 308), "Add Component", fill="white", font=_font(20))
    check("a hover highlight still matches", t.find(tracker.grey(hover), 0, 0)[0] == "same")
    start = time.time()
    result, box = t.find(shifted(0, -260), 0, 0)
    took = time.time() - start
    check("scrolled up 260px: the box follows exactly", result == "moved"
          and box == (button[0], button[1] - 260, button[2], button[3] - 260), (result, box))
    check("...searching the whole screen quickly", took < 0.5, f"{took:.2f}s")
    t2 = tracker.Tracker.make(page, 0, 0, button)
    big = shifted(-40, -30)
    region = big[0:900, 500:1500]              # the watcher's quick look: just near the box
    result, box = t2.find(region, 500, 0)
    check("moved window, quick look near the box", result == "moved"
          and box == (button[0] - 40, button[1] - 30, button[2] - 40, button[3] - 30), (result, box))
    check("button gone: says so", tracker.Tracker.make(page, 0, 0, button).find(
        tracker.grey(Image.new("RGB", (W, H), "white")), 0, 0)[0] == "gone")
    row = (300 - p, 3 * 90 + 196 - p, 640 + p, 3 * 90 + 228 + p)    # "Result number 3"
    tr = tracker.Tracker.make(page, 0, 0, row)
    result, box = tr.find(shifted(0, -90), 0, 0)
    check("look-alike rows: follows the right one, not its neighbour",
          result == "moved" and box[1] == row[1] - 90, (result, box))
    check("nothing to recognise (blank field): no tracker",
          tracker.Tracker.make(Image.new("RGB", (W, H), "white"), 0, 0, (100, 100, 400, 140)) is None)
    check("box off the screenshot: no tracker", tracker.Tracker.make(page, 0, 0, (W - 50, 10, W + 90, 60)) is None)
    pill = tracker.Tracker.make(page, 0, 0, button, hint="wikipedia", box_visible=True)
    check("keeps clear of the type hint when screenshots can see it",
          pill.picture.shape[1] < t.picture.shape[1])
    from eris.watcher import Watcher
    w = Watcher.__new__(Watcher)
    w.eris = types.SimpleNamespace(waiting="next")
    w.lock, w.last_fire, w.keep_streak = threading.Lock(), 0.0, 0
    w.rebase(delay=0)
    blank = np.zeros((180, 320), dtype=np.int16)
    w._step(blank, 100.0)
    w._step(blank, 100.5, gone=True)
    fired = any(w._step(blank, 100.5 + 0.5 * i) for i in range(1, 6))
    check("watcher: the button vanishing counts as a change", fired)


def test_which_screen():
    from eris import screen
    left_mon = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
    main = {"left": 0, "top": 0, "width": 2560, "height": 1440}
    sct = types.SimpleNamespace(monitors=[{}, main, left_mon])
    check("the monitor your app is on (not the one your mouse is on)",
          screen.monitor_for(sct, (-1800, 100, -300, 900)) is left_mon)
    check("a window across two screens: the one with most of it",
          screen.monitor_for(sct, (-400, 100, 1800, 900)) is main)
    small = screen.window_area((600, 300, 1800, 1100), main)
    check("a smaller window: just it, plus a little around it",
          small and small["left"] < 600 and small["width"] < 2560 and small["left"] >= 0, small)
    check("a maximised app: the whole screen", screen.window_area((-8, -8, 2568, 1400), main) is None)
    check("a tiny popup: the whole screen", screen.window_area((1000, 600, 1300, 800), main) is None)


def test_hearing():
    from eris import ears as E
    rng = np.random.default_rng(0)
    noise = lambda s, lv=0.002: (rng.standard_normal(int(s * E.RATE)) * lv).astype(np.float32)

    def voice(s, lv=0.08):
        t = np.arange(int(s * E.RATE)) / E.RATE
        return (np.sin(2 * np.pi * 180 * t) * lv * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32) + noise(s)

    def ends(audio):
        det, out = E.Speech(), []
        for i in range(0, len(audio) - E.BLOCK + 1, E.BLOCK):
            ev, a = det.feed(audio[i:i + E.BLOCK])
            if ev in ("start", "end"):
                out.append(ev if a is None else round(len(a) / E.RATE, 1))
        return out
    r = ends(np.concatenate([noise(1.5), voice(2.0), noise(1.5)]))
    check("a sentence: one start, one end", len(r) == 2 and r[0] == "start" and 2.0 <= r[1] <= 3.4, r)
    r = ends(np.concatenate([noise(1), voice(0.15), noise(1.2), voice(1.0), noise(0.4), voice(1.0), noise(1.5)]))
    check("a cough is ignored, a pause doesn't split a sentence", [x for x in r if x != "start"] and
          len([x for x in r if x != "start"]) == 1)
    r = ends(np.concatenate([noise(4, 0.012), voice(1.5, 0.12) + noise(1.5, 0.012), noise(1.5, 0.012)]))
    check("a noisy room (fan) still works", r[:1] == ["start"] and len(r) == 2)
    heard, busy = [], {"v": True}
    call = E.Call(types.SimpleNamespace(transcribe=lambda a: "words"), on_start=lambda: None,
                  on_text=heard.append, muted=lambda: busy["v"])
    call.running = True
    threading.Thread(target=call._loop, daemon=True).start()
    a = np.concatenate([voice(2.0), noise(0.3)])
    for i in range(0, len(a) - E.BLOCK + 1, E.BLOCK):
        call.q.put(a[i:i + E.BLOCK])
    time.sleep(0.3)
    busy["v"] = False
    a = np.concatenate([noise(1.0), voice(1.5), noise(1.5)])
    for i in range(0, len(a) - E.BLOCK + 1, E.BLOCK):
        call.q.put(a[i:i + E.BLOCK])
    time.sleep(1.0)
    call.running = False
    check("on a call she never hears herself, only you", heard == ["words"], heard)


def test_safe_updates():
    import shutil
    import tempfile
    from pathlib import Path
    from eris import updater
    root = Path(tempfile.mkdtemp())
    (root / "eris").mkdir()
    (root / "VERSION").write_text("1.0")
    updater.ROOT = root
    config.UPDATE_REPO = "someone/eris"

    def attempt(files, expected=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for k, v in files.items():
                z.writestr(k, v)
        updater._get = lambda url, timeout=10: buf.getvalue()
        (root / "VERSION").write_text("1.0")
        try:
            return updater.install_update(lambda *a: None, expected=expected)
        except Exception as e:
            return f"refused: {e}"
    good = {"eris-main/VERSION": "9.9", "eris-main/eris/new.py": "x = 1\n"}
    check("a normal update installs", attempt(good, "9.9") is True and (root / "eris/new.py").exists())
    attempt({**good, "eris-main/../../evil.py": "x", "eris-main/eris/x.exe": "MZ", "eris-main/.venv/a.py": "x"}, "9.9")
    check("files outside Eris's own are never written", not (root.parent.parent / "evil.py").exists()
          and not (root / "eris/x.exe").exists() and not (root / ".venv").exists())
    check("downgrades refused", "refused" in str(attempt({"eris-main/VERSION": "0.1"})))
    check("a changed version refused", "refused" in str(attempt(good, "9.8")))
    updater._get = lambda url, timeout=10: b"x" * (updater.MAX_DOWNLOAD + 1)
    try:
        updater.install_update(lambda *a: None)
        check("huge downloads refused", False)
    except ValueError:
        check("huge downloads refused", True)
    config.UPDATES = "off"
    updater._get = lambda url, timeout=10: b"99.0"
    check("automatic checks can be turned off", updater.remote_version() is None
          and updater.remote_version(manual=True) == "99.0")
    config.UPDATES = "ask"
    shutil.rmtree(root, ignore_errors=True)


def test_saved_key():
    from eris import settings
    settings.sys = types.SimpleNamespace(platform="win32")
    settings._protect_key = lambda k: "ENC(" + k[::-1] + ")"
    settings._unprotect_key = lambda t: t[4:-1][::-1]
    config.API_KEY = "sk-ant-SECRET123"
    settings.save()
    raw = settings.FILE.read_text()
    config.API_KEY = ""
    settings.load()
    check("the API key is never stored as plain text", "SECRET123" not in raw and config.API_KEY == "sk-ant-SECRET123")
    settings.FILE.write_text('{"API_KEY": "sk-ant-OLD"}')
    settings.load()
    check("an old plain-text key gets encrypted", "OLD\"" not in settings.FILE.read_text() and config.API_KEY == "sk-ant-OLD")
    settings._unprotect_key = lambda t: (_ for _ in ()).throw(OSError())
    settings.load()
    check("a copied settings file just asks for the key again", config.API_KEY == "")
    settings.sys = __import__("sys")
    config.API_KEY = ""


def test_privacy():
    from eris import privacy, screen, uia
    check("sensitive fields recognised", uia.is_sensitive(True, "") and uia.is_sensitive(False, "Email address")
          and not uia.is_sensitive(False, "Search Wikipedia"))
    privacy.foreground_title = lambda: "Vault - Bitwarden"
    check("password managers are never looked at", "Bitwarden" in privacy.should_look_away())
    privacy.foreground_title = lambda: "Unity"
    privacy.typing_secret = lambda: True
    check("typing a secret: look away", privacy.should_look_away() == "you're typing something private")
    privacy.typing_secret = lambda: False
    img = Image.new("RGB", (800, 400), "white")
    mon = {"left": 0, "top": 0, "width": 800, "height": 400}
    screen.black_out(img, [(100, 100, 400, 140)], mon)
    shot = screen.finish(img, mon)
    check("private fields are blacked out before anything else",
          max(shot.full.getpixel((250, 120))) < 60 and min(shot.full.getpixel((600, 300))) > 200)


for name, fn in list(globals().items()):
    if name.startswith("test_"):
        fn()
done("parts")
