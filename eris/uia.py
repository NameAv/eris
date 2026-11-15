"""Ask Windows (UI Automation) for the exact rectangle of the thing at a spot.

Browsers (Chrome, Edge, Firefox) and most Windows apps describe their buttons,
links, text fields and images to Windows for screen readers. We use that to get
pixel-perfect edges. Everything runs on one background thread (COM likes that)
and every call has a short timeout, so it can never slow Eris down or crash her.
"""
import queue
import threading

# UI Automation control types
BUTTON, CHECKBOX, COMBOBOX, EDIT, HYPERLINK, IMAGE, LISTITEM = 50000, 50002, 50003, 50004, 50005, 50006, 50007
MENUITEM, RADIO, SLIDER, TABITEM, TREEITEM, DATAITEM, SPLITBUTTON, HEADERITEM = (
    50011, 50013, 50015, 50019, 50024, 50029, 50031, 50035)
TEXT = 50020
CLICKABLE = {BUTTON, CHECKBOX, COMBOBOX, EDIT, HYPERLINK, IMAGE, LISTITEM, MENUITEM, RADIO,
             SLIDER, TABITEM, TREEITEM, DATAITEM, SPLITBUTTON, HEADERITEM}
# Big containers: almost never what you'd point at
CONTAINERS = {50008, 50009, 50010, 50018, 50021, 50023, 50026, 50028, 50030, 50032, 50033, 50036, 50037}


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def best_match(target, candidates):
    """target: (x1,y1,x2,y2). candidates: [(rect, control_type)]. Returns the rect
    that best matches, or None if nothing matches well enough."""
    area = max(1, (target[2] - target[0]) * (target[3] - target[1]))
    best, best_score = None, 0.0
    for rect, ctype in candidates:
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w < 4 or h < 4 or w * h > 8 * area:
            continue
        score = _iou(rect, target)
        if ctype in CLICKABLE:
            score += 0.15
        elif ctype in CONTAINERS:
            score -= 0.3
        if score > best_score:
            best, best_score = rect, score
    return best if best_score >= 0.45 else None


class UIA:
    def __init__(self):
        self.q = queue.Queue()
        self.ok = True
        threading.Thread(target=self._run, daemon=True).start()

    def snap(self, box, timeout=0.6):
        """box: screen coords incl. padding. Returns an exact padded box or None."""
        if not self.ok:
            return None
        from . import config
        p = config.BOX_PADDING
        target = (box[0] + p, box[1] + p, box[2] - p, box[3] - p)
        done = threading.Event()
        out = {}
        self.q.put((target, out, done))
        if not done.wait(timeout) or not out.get("rect"):
            return None
        x1, y1, x2, y2 = out["rect"]
        return (x1 - p, y1 - p, x2 + p, y2 + p)

    def _run(self):
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitialize()
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as U
            uia = comtypes.client.CreateObject(U.CUIAutomation._reg_clsid_,
                                               interface=U.IUIAutomation)
            walker = uia.ControlViewWalker
        except Exception:
            self.ok = False
            return
        while True:
            target, out, done = self.q.get()
            try:
                out["rect"] = best_match(target, self._candidates(uia, walker, U, target))
            except Exception:
                out["rect"] = None
            done.set()

    @staticmethod
    def _candidates(uia, walker, U, t):
        """Elements under a few points of the box, plus their parents."""
        x1, y1, x2, y2 = t
        w, h = x2 - x1, y2 - y1
        points = [((x1 + x2) // 2, (y1 + y2) // 2), (x1 + w // 4, (y1 + y2) // 2),
                  (x2 - w // 4, (y1 + y2) // 2)]
        seen, out = set(), []
        for x, y in points:
            try:
                el = uia.ElementFromPoint(U.tagPOINT(x, y))
            except Exception:
                continue
            for _ in range(6):   # the element and up to 5 parents
                if el is None:
                    break
                try:
                    r = el.CurrentBoundingRectangle
                    rect = (r.left, r.top, r.right, r.bottom)
                    if rect not in seen:
                        seen.add(rect)
                        out.append((rect, el.CurrentControlType))
                    el = walker.GetParentElement(el)
                except Exception:
                    break
        return out
