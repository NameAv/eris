"""The test lab's grader: a brain that always answers right must pass every test, and
one that makes every classic mistake must fail every test, for the right reasons."""
from helpers import LineStream, check, done

from eris import bench, ocr

# A stand-in for Windows' text reader: reports each drawn word where it really is.
_draw_text = bench.Screen.text
CURRENT = {}


def recording_text(self, xy, s, size=16, color="#202124", bold=False):
    rect = _draw_text(self, xy, s, size, color, bold)
    f, x, words = bench._font(size, bold), xy[0], []
    for w in s.split(" "):
        if w:
            words.append((w, self.d.textbbox((x, xy[1]), w, font=f)))
        x += f.getlength(w + " ")
    self.__dict__.setdefault("ocr_lines", []).append(words)
    CURRENT["screen"] = self
    return rect


bench.Screen.text = recording_text
ocr.reader = lambda: type("R", (), {"read": lambda self, img, left=0, top=0, timeout=1.5:
                                    ocr.group(CURRENT["screen"].ocr_lines)})()


class AnswerKey:
    """Answers from the test's answer key (good=True) or makes every classic mistake."""

    def __init__(self, good):
        self.good, self.history = good, []

    def turn(self, shot, text, on_event, alive):
        t, sc = self.test, self.screen

        def img(r):
            return " ".join(str(int(v)) for v in ((r[0] - shot.left) / shot.sx, (r[1] - shot.top) / shot.sy,
                                                   (r[2] - shot.left) / shot.sx, (r[3] - shot.top) / shot.sy))
        if not self.good:
            r = sc.things.get(t.avoid[0]) if t.avoid else (5, 5, 60, 40)
            reply = f"BOX {img(r)}\nTYPE my password\nSAY Type your password here.\nWAIT done"
        elif "keep" in t.expect:
            reply = "KEEP"
        elif not t.targets:
            words = "That page is just a pancake recipe: flour, eggs and milk." if "flour" in t.say_any \
                else "Do what exactly? Tell me a bit more?"
            reply = f"NOBOX\nSAY {words}\nDONE"
        else:
            tgt = sc.things[t.targets[0]]
            inside = lambda r: tgt[0] - 2 <= (r[0] + r[2]) / 2 <= tgt[2] + 2 and tgt[1] - 2 <= (r[1] + r[3]) / 2 <= tgt[3] + 2
            n = next((i for i, e in enumerate(shot.elements, 1) if e["rect"] == tgt), None) or \
                next((i for i, e in enumerate(shot.elements, 1) if e.get("src") == "ocr" and inside(e["rect"])), None)
            reply = (f"ELEMENT {n}" if n else f"BOX {img(tgt)}") + "\nWHAT the thing"
            if t.type_has:
                reply += f"\nTYPE {t.type_has}"
            reply += "\nSAY " + (f"That's a {t.say_any[0]} - close it." if t.say_any else "Click here.")
            reply += f"\nWAIT {t.wait[0] if t.wait else 'click'}"
        for ev in LineStream().feed(reply + "\n"):
            on_event(ev)
        self.history.append({"role": "assistant", "content": reply})


def run(good):
    key, results = AnswerKey(good), []
    for t in bench.TESTS:
        key.test = t

        def draw(original=t.screen):
            key.screen = original()
            return key.screen
        results.append(bench.run_test(key, bench.Test(**{**t.__dict__, "screen": draw})))
    return results


right = run(True)
check(f"the right answers pass all {len(right)} tests", all(r["pass"] for r in right),
      [(r["name"], r["fails"]) for r in right if not r["pass"]])
wrong = run(False)
check("the classic mistakes fail every test", not any(r["pass"] for r in wrong),
      [r["name"] for r in wrong if r["pass"]])
reasons = " ".join(" ".join(r["fails"]) for r in wrong)
check("...for the right reasons", all(s in reasons for s in ("pointed at 'ad'", "TYPE contains 'password'", "box missed")))
grown = [r for r in right if "grown to its button" in r["pointed"]]
check("words read off the screen grow to their buttons", len(grown) >= 2, [r["pointed"] for r in right])
path, passed, total = bench.report(right)
check("a report is written", path.exists() and "# Eris test report" in path.read_text(encoding="utf-8"))
done("lab")
