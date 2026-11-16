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
# UI Automation property ids
P_RECT, P_TYPE, P_NAME, P_AUTOMATION_ID, P_HELP = 30001, 30003, 30005, 30011, 30013
P_PASSWORD, P_OFFSCREEN = 30019, 30022
TYPE_NAMES = {BUTTON: "button", CHECKBOX: "checkbox", COMBOBOX: "dropdown", EDIT: "text box",
              HYPERLINK: "link", IMAGE: "image", LISTITEM: "list item", MENUITEM: "menu item",
              RADIO: "option", SLIDER: "slider", TABITEM: "tab", TREEITEM: "tree item",
              DATAITEM: "item", SPLITBUTTON: "button", HEADERITEM: "header"}
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


SENSITIVE_WORDS = ("password", "passcode", "passwort", "pin code", "email", "e-mail",
                   "card number", "credit card", "debit card", "cvv", "cvc", "security code",
                   "expiry", "expiration", "iban", "account number", "sort code", "routing",
                   "ssn", "social security", "national insurance", "tax id", "one-time code",
                   "verification code", "2fa", "otp")


def is_sensitive(is_password, *labels):
    if is_password:
        return True
    text = " ".join(l for l in labels if l).lower()
    return any(w in text for w in SENSITIVE_WORDS)


_helpers = {}
_lock = threading.Lock()


def get(role="main"):
    """A UI Automation helper (None if not on Windows). Privacy checks use their own
    ("privacy"), so a slow scan of a huge web page can never hold them up."""
    import sys
    if sys.platform != "win32":
        return None
    with _lock:
        if role not in _helpers:
            _helpers[role] = UIA()
        return _helpers[role]


class UIA:
    def __init__(self):
        self.q = queue.Queue()
        self.ok = True
        threading.Thread(target=self._run, daemon=True).start()

    def _ask(self, kind, arg, timeout):
        if not self.ok:
            return None
        done, out = threading.Event(), {}
        self.q.put((kind, arg, out, done))
        if not done.wait(timeout):
            return None
        return out.get("result")

    def focus_is_sensitive(self, timeout=0.3):
        """True if you're typing into a password / email / card field right now,
        None if Windows didn't answer in time."""
        return self._ask("focus", None, timeout)

    def sensitive_rects(self, timeout=0.8):
        """Screen rects of password/email/card fields in the window in front.
        None if Windows didn't answer in time."""
        return self._ask("fields", None, timeout)

    def scan(self, hwnd=None, timeout=0.9):
        """One pass over the window in front: its clickable things (with names and exact
        rectangles) and its private fields. {"elements": [...], "sensitive": [...]} or
        None if Windows didn't answer in time."""
        return self._ask("scan", hwnd, timeout)

    def snap(self, box, timeout=0.6):
        """box: screen coords incl. padding. Returns an exact padded box or None."""
        from . import config
        p = config.BOX_PADDING
        target = (box[0] + p, box[1] + p, box[2] - p, box[3] - p)
        rect = self._ask("snap", target, timeout)
        if not rect:
            return None
        x1, y1, x2, y2 = rect
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
            kind, arg, out, done = self.q.get()
            try:
                if kind == "snap":
                    out["result"] = best_match(arg, self._candidates(uia, walker, U, arg))
                elif kind == "focus":
                    el = uia.GetFocusedElement()
                    sensitive = False
                    if el and (el.CurrentIsPassword or el.CurrentControlType == EDIT):
                        sensitive = is_sensitive(el.CurrentIsPassword, el.CurrentName,
                                                 el.CurrentAutomationId, el.CurrentHelpText)
                    out["result"] = sensitive
                elif kind == "fields":
                    out["result"] = self._sensitive_fields(uia, U)
                elif kind == "scan":
                    out["result"] = self._scan(uia, arg)
            except Exception:
                out["result"] = None
            done.set()

    @staticmethod
    def _scan(uia, hwnd=None):
        """Everything clickable in the app's window, fetched in ONE round trip to the
        app (a cache request), because asking a browser element-by-element is slow."""
        import ctypes
        hwnd = hwnd or ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return {"elements": [], "sensitive": []}
        root = uia.ElementFromHandle(hwnd)
        cache = uia.CreateCacheRequest()
        for prop in (P_RECT, P_TYPE, P_NAME, P_AUTOMATION_ID, P_HELP, P_PASSWORD, P_OFFSCREEN):
            cache.AddProperty(prop)
        kinds = None
        for t in sorted(CLICKABLE):
            c = uia.CreatePropertyCondition(P_TYPE, t)
            kinds = c if kinds is None else uia.CreateOrCondition(kinds, c)
        cond = uia.CreateAndCondition(kinds, uia.CreatePropertyCondition(P_OFFSCREEN, False))
        found = root.FindAllBuildCache(4, cond, cache)          # 4 = all descendants
        elements, sensitive = [], []
        for i in range(min(found.Length, 600)):
            el = found.GetElement(i)
            try:
                r = el.CachedBoundingRectangle
                rect = (r.left, r.top, r.right, r.bottom)
                if rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4:
                    continue
                ctype, name = el.CachedControlType, (el.CachedName or "").strip()
                if is_sensitive(el.CachedIsPassword, name, el.CachedAutomationId, el.CachedHelpText):
                    sensitive.append(rect)
                    elements.append({"type": ctype, "name": "(private field)", "rect": rect})
                    continue
                if not name and ctype != EDIT:
                    continue
                elements.append({"type": ctype, "name": name[:60], "rect": rect})
            except Exception:
                continue
        return {"elements": elements, "sensitive": sensitive}

    @staticmethod
    def _sensitive_fields(uia, U):
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return []
        root = uia.ElementFromHandle(hwnd)
        cond = uia.CreatePropertyCondition(30003, EDIT)          # ControlType == Edit
        found = root.FindAll(4, cond)                            # TreeScope_Descendants
        rects = []
        for i in range(min(found.Length, 200)):
            el = found.GetElement(i)
            try:
                if is_sensitive(el.CurrentIsPassword, el.CurrentName, el.CurrentAutomationId,
                                el.CurrentHelpText):
                    r = el.CurrentBoundingRectangle
                    if r.right > r.left and r.bottom > r.top:
                        rects.append((r.left, r.top, r.right, r.bottom))
            except Exception:
                continue
        return rects

    @staticmethod
    def _candidates(uia, walker, U, t):
        """Elements under a few points of the box, plus their parents."""
        x1, y1, x2, y2 = t
        w = x2 - x1
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
