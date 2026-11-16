"""Reading the words on screen with Windows' own built-in text reader (OCR).

For apps that don't tell Windows about their buttons (Unity, Blender, games...), the
words on screen are the next best thing: each label becomes an item in the numbered
list, so the AI can pick it by number and the box lands exactly on it.

Kept light: it's free and offline, it only reads the window of the app you're in, and
only for apps that need it. Private fields are blacked out before it reads anything.
"""
import asyncio
import queue
import sys
import threading

OCR_TEXT = -1          # element "type" for things found by reading the screen
MAX_ITEMS = 50


def group(lines):
    """Turn OCR lines into clickable-sized items.

    lines: [[(word, (x1, y1, x2, y2)), ...], ...]. Words on one line that are far apart
    (like a menu bar: "File   Edit   Assets") become separate items; long sentences
    (paragraphs of text) are dropped, since buttons and labels are short."""
    items = []
    for words in lines:
        words = sorted(words, key=lambda w: w[1][0])
        if not words:
            continue
        chunk = [words[0]]
        for prev, cur in zip(words, words[1:]):
            height = max(prev[1][3] - prev[1][1], cur[1][3] - cur[1][1], 8)
            if cur[1][0] - prev[1][2] > max(12, 1.1 * height):   # a big gap: a new item
                items.append(chunk)
                chunk = []
            chunk.append(cur)
        items.append(chunk)
    out = []
    for chunk in items:
        text = " ".join(w for w, _ in chunk).strip()
        if len(text) < 2 or len(text) > 40 or len(chunk) > 6:
            continue
        rect = (int(min(r[0] for _, r in chunk)), int(min(r[1] for _, r in chunk)),
                int(round(max(r[2] for _, r in chunk))), int(round(max(r[3] for _, r in chunk))))
        out.append({"type": OCR_TEXT, "name": text, "rect": rect, "src": "ocr"})
    return out[:MAX_ITEMS]


def merge(uia, found):
    """Windows' own list wins; add only the words that aren't already inside one of its
    items (so nothing is listed twice)."""
    uia = list(uia or [])
    out = list(uia)
    for item in found:
        x1, y1, x2, y2 = item["rect"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if not any(e["rect"][0] <= cx <= e["rect"][2] and e["rect"][1] <= cy <= e["rect"][3]
                   for e in uia):
            out.append(item)
    return out


class Reader:
    """Runs Windows' OCR on its own thread (it's async and likes a steady home)."""

    def __init__(self):
        self.q = queue.Queue()
        self.ok = sys.platform == "win32"
        if self.ok:
            threading.Thread(target=self._run, daemon=True).start()

    def read(self, img, left=0, top=0, timeout=1.5):
        """Items found in a PIL image whose top-left corner is at (left, top) on screen.
        [] if OCR isn't available or too slow."""
        if not self.ok:
            return []
        done, out = threading.Event(), {}
        self.q.put((img, left, top, out, done))
        if not done.wait(timeout):
            return []
        return out.get("items", [])

    def _run(self):
        try:
            from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter
            engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                raise RuntimeError("no OCR language installed")
        except Exception:
            self.ok = False
            return
        loop = asyncio.new_event_loop()
        while True:
            img, left, top, out, done = self.q.get()
            try:
                rgba = img.convert("RGBA")
                writer = DataWriter()
                writer.write_bytes(rgba.tobytes())
                bitmap = SoftwareBitmap.create_copy_from_buffer(
                    writer.detach_buffer(), BitmapPixelFormat.RGBA8, rgba.width, rgba.height)
                result = loop.run_until_complete(engine.recognize_async(bitmap))
                lines = []
                for line in result.lines:
                    words = []
                    for w in line.words:
                        b = w.bounding_rect
                        words.append((w.text, (int(left + b.x), int(top + b.y),
                                               int(left + b.x + b.width), int(top + b.y + b.height))))
                    lines.append(words)
                out["items"] = group(lines)
            except Exception:
                out["items"] = []
            done.set()


_reader = None


def reader():
    global _reader
    if _reader is None:
        _reader = Reader()
    return _reader
