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
