"""Which app you're working in: its name, window title and where its window is.

Eris's own windows are skipped: if you just typed your question into Eris, this is the
last app you were actually using. A handful of direct Windows calls: practically free.
"""
import ctypes
import os
import sys
import threading
import time

FRIENDLY = {   # program file -> the name people know it by
    "chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox",
    "opera": "Opera", "brave": "Brave", "unity": "Unity", "blender": "Blender",
    "code": "Visual Studio Code", "devenv": "Visual Studio", "explorer": "File Explorer",
    "discord": "Discord", "steam": "Steam", "spotify": "Spotify", "photoshop": "Photoshop",
    "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "notepad": "Notepad",
    "systemsettings": "Windows Settings", "applicationframehost": "a Windows app",
    "obs64": "OBS Studio", "gimp-2.10": "GIMP", "unrealeditor": "Unreal Editor",
    "godot": "Godot", "rider64": "Rider", "minecraft": "Minecraft",
}


def _exe(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)            # query-limited-information
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = ctypes.c_ulong(520)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.splitext(os.path.basename(buf.value))[0]
        return ""
    finally:
        k32.CloseHandle(h)


_last = {"hwnd": None}      # the last app you were actually using (not Eris)


def _window(hwnd):
    """{"hwnd", "title", "exe", "name", "rect"} for a real app window, or None (Eris's own
    windows, tool windows, tiny popups, hidden or minimised windows)."""
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    if not hwnd or not u32.IsWindow(hwnd):
        return None
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid() or not u32.IsWindowVisible(hwnd) or u32.IsIconic(hwnd):
        return None
    n = u32.GetWindowTextLengthW(hwnd)
    exstyle = u32.GetWindowLongW(hwnd, -20)
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    if not n or exstyle & 0x80 or r.right - r.left <= 200 or r.bottom - r.top <= 150:
        return None
    title = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, title, n + 1)
    exe = _exe(pid.value)
    return {"hwnd": hwnd, "title": title.value, "exe": exe.lower(),
            "name": FRIENDLY.get(exe.lower(), exe or "an app"), "rect": (r.left, r.top, r.right, r.bottom)}


def _follow_focus():
    """Keep note of the last app you were in, so that when you talk to Eris (and her
    window has the focus) she looks at that app, on its screen."""
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    while True:
        try:
            hwnd = u32.GetForegroundWindow()
            if hwnd and hwnd != _last["hwnd"] and _window(hwnd):
                _last["hwnd"] = hwnd
        except Exception:
            pass
        time.sleep(0.3)


def front_window():
    """The app you're working in (never Eris): the one in front, or if Eris is in front,
    the last app you were using; failing both, the window just behind Eris's."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetWindow.restype = wintypes.HWND
    u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    if not _last.get("watching"):
        _last["watching"] = True
        threading.Thread(target=_follow_focus, daemon=True).start()
    for hwnd in (u32.GetForegroundWindow(), _last["hwnd"]):
        win = _window(hwnd)
        if win:
            return win
    hwnd = u32.GetForegroundWindow()
    for _ in range(300):          # walk down the window stack until we find a real app
        if not hwnd:
            return None
        win = _window(hwnd)
        if win:
            return win
        hwnd = u32.GetWindow(hwnd, 2)                      # GW_HWNDNEXT: the window below
    return None


def describe(win):
    """One line for the AI, e.g.: App in front: Blender (window title: "untitled.blend")."""
    if not win:
        return ""
    title = win["title"][:80]
    return f'App in front: {win["name"]} (window title: "{title}")'
