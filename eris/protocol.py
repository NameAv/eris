"""Turns Claude's streamed text into events, line by line, as it arrives.

Claude is told to answer in this exact shape:
    BOX x1 y1 x2 y2        (or NOBOX)  <- first line, so the box shows instantly
    TYPE exact text                    <- optional: what to type, shown big on screen
    SAY one short sentence             <- spoken as soon as each line arrives
    SAY ...
    WAIT click | WAIT next | DONE      <- how this step ends
or just:
    KEEP                               <- (after an automatic look) nothing to add, keep waiting
"""
from dataclasses import dataclass


@dataclass
class Event:
    kind: str            # "box" | "nobox" | "type" | "say" | "wait" | "done" | "keep"
    value: object = None


def parse_line(line: str):
    line = line.strip().strip("`").strip()
    if not line:
        return None
    head, _, rest = line.partition(" ")
    head = head.upper().rstrip(":")
    rest = rest.strip()
    if head == "BOX":
        nums = []
        for tok in rest.replace(",", " ").split():
            try:
                nums.append(float(tok))
            except ValueError:
                pass
        if len(nums) == 4:
            x1, y1, x2, y2 = nums
            return Event("box", (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
        return None
    if head == "NOBOX":
        return Event("nobox")
    if head == "SAY":
        return Event("say", rest) if rest else None
    if head == "WAIT":
        mode = rest.lower()
        return Event("wait", "click" if mode.startswith("click") else "next")
    if head == "DONE":
        return Event("done")
    if head == "KEEP":
        return Event("keep")
    if head == "TYPE":
        return Event("type", rest.strip('"').strip("'")) if rest else None
    # Anything off-format: just say it, rather than lose it.
    return Event("say", line)


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
