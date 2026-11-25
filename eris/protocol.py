"""Turns the AI's streamed text into events, line by line, as it arrives.

The AI is told to answer in this shape (one thing per line):
    ELEMENT n  or  BOX x1 y1 x2 y2  or  NOBOX   <- first, so the box shows instantly
    WHAT the exact thing                       <- used to make the box exact
    AVATAR                                     <- the box is her new profile picture
    TYPE exact text                            <- what to type, shown inside the box
    KEY Ctrl+S                                 <- a key or shortcut to press, shown big
    TO ELEMENT n  or  TO x1 y1 x2 y2           <- a drag: where to drop the boxed thing
    SCROLL down | up | left | right            <- what they need is scrolled out of view
    SAY one short sentence                     <- spoken the moment each line arrives
    WHY why it works                           <- Eris Unity: the lesson in the step
    PROJECT something they made                <- Eris Unity: kept about their game
    REMEMBER a fact about you                  <- saved to her memory
    PLAN step | step | step                    <- first reply of a task: the steps ahead
    WAIT click | WAIT next | DONE              <- how this step ends
or just KEEP (after an automatic look: nothing new, keep waiting). The zoom-in check
answers BOX or NONE.
"""
from dataclasses import dataclass


@dataclass
class Event:
    kind: str           # the line's first word, lower case ("box", "say", ...), or "fail"
    value: object = None


BARE = {"NOBOX", "DONE", "KEEP", "AVATAR", "NONE"}       # just the word
WORDS = {"SAY", "WHY", "WHAT", "REMEMBER", "PROJECT", "TYPE", "PLAN"}     # the word and some text


def _box(rest):
    nums = []
    for tok in rest.replace(",", " ").split():
        try:
            nums.append(float(tok))
        except ValueError:
            pass
    if len(nums) != 4:
        return None
    x1, y1, x2, y2 = nums
    return Event("box", (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))


SCROLLS = ("down", "up", "left", "right")


def _keys(text):
    """'ctrl+shift+s' -> 'Ctrl + Shift + S'."""
    parts = [p.strip() for p in text.replace(" + ", "+").split("+") if p.strip()]
    return " + ".join(p.upper() if len(p) == 1 else p[:1].upper() + p[1:] for p in parts)


def parse_line(line: str):
    line = line.strip().strip("`").strip()
    if not line:
        return None
    head, _, rest = line.partition(" ")
    head, rest = head.upper().rstrip(":"), rest.strip()
    if head in BARE:
        return Event(head.lower())
    if head in WORDS:
        if head == "TYPE":
            rest = rest.strip('"').strip("'")
        return Event(head.lower(), rest) if rest else None
    if head == "BOX":
        return _box(rest)
    if head == "ELEMENT":
        num = rest.strip("[]#. ").split(" ")[0].strip("[]#.")
        return Event("element", int(num)) if num.isdigit() else None
    if head == "KEY":
        return Event("key", _keys(rest)) if rest else None
    if head == "SCROLL":
        way = rest.lower().split(" ")[0] if rest else "down"
        return Event("scroll", way if way in SCROLLS else "down")
    if head == "TO":
        if rest.upper().startswith("ELEMENT"):
            num = rest[7:].strip("[]#.: ").split(" ")[0].strip("[]#.")
            return Event("to", int(num)) if num.isdigit() else None
        box = _box(rest)
        return Event("to", box.value) if box else None
    if head == "WAIT":
        return Event("wait", "click" if rest.lower().startswith("click") else "next")
    return Event("say", line)   # anything off-format: just say it, rather than lose it


class LineStream:
    """Feed text chunks in, get complete-line events out."""

    def __init__(self):
        self.buf = ""

    def feed(self, chunk: str):
        self.buf += chunk
        out = []
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            ev = parse_line(line)
            if ev:
                out.append(ev)
        return out

    def flush(self):
        ev = parse_line(self.buf)
        self.buf = ""
        return [ev] if ev else []
