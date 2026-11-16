"""Which app you're working in: its name, window title and where its window is.

Eris's own windows are skipped, so if you just typed your question into Eris, this is
still the app behind her. A handful of direct Windows calls: practically free.
"""
import ctypes
import os
import sys

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


def front_window():
    """{"hwnd", "title", "exe", "name", "rect"} for the app in front (not Eris), or None."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetWindow.restype = wintypes.HWND
    u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    me = os.getpid()
    hwnd = u32.GetForegroundWindow()
    for _ in range(300):          # walk down the window stack until we find a real app
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != me and u32.IsWindowVisible(hwnd) and not u32.IsIconic(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            exstyle = u32.GetWindowLongW(hwnd, -20)
            r = wintypes.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            big = r.right - r.left > 200 and r.bottom - r.top > 150
            if n and big and not exstyle & 0x80:          # skip tool windows / tiny popups
                title = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, title, n + 1)
                exe = _exe(pid.value)
                return {"hwnd": hwnd, "title": title.value, "exe": exe.lower(),
                        "name": FRIENDLY.get(exe.lower(), exe or "an app"),
                        "rect": (r.left, r.top, r.right, r.bottom)}
        hwnd = u32.GetWindow(hwnd, 2)                      # GW_HWNDNEXT: the window below
    return None


def describe(win):
    """One line for the AI, e.g.: App in front: Blender (window title: "untitled.blend")."""
    if not win:
        return ""
    title = win["title"][:80]
    return f'App in front: {win["name"]} (window title: "{title}")'
