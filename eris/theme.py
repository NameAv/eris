"""Eris's look: deep near-black with crimson accents."""
import sys

FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

BG = "#0d0809"          # window background
CARD = "#170f11"        # cards / chat area
CARD_2 = "#211518"      # Eris bubbles, inputs
BORDER = "#2e1a1f"
ACCENT = "#e3263f"      # crimson
ACCENT_HOVER = "#c01c33"
ACCENT_DIM = "#4a1520"  # your bubbles
GLOW = "#ff4d63"
TEXT = "#f6ecee"
MUTED = "#9b8a8f"
GOLD = "#e6b85c"
ERROR = "#ff8a8a"
CAPTION_BG = "#1a0a0e"

STATES = {  # state -> (label, dot colour)
    "loading": ("Waking up", MUTED),
    "ready": ("Ready", "#4fd18b"),
    "listening": ("Listening", GLOW),
    "thinking": ("Thinking", GOLD),
    "guiding": ("Guiding", ACCENT),
    "off": ("Paused", MUTED),
}


def font(size=13, weight="normal"):
    import customtkinter as ctk
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def tint_titlebar(win):
    """Dark crimson-black title bar on Windows 11 so the window looks seamless."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        u32.GetParent.restype = wintypes.HWND
        hwnd = u32.GetParent(win.winfo_id())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)          # dark mode
        r, g, b = (int(BG[i:i + 2], 16) for i in (1, 3, 5))
        caption = ctypes.c_int(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)     # title bar colour
        r, g, b = (int(ACCENT[i:i + 2], 16) for i in (1, 3, 5))
        border = ctypes.c_int(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)      # crimson outline
    except Exception:
        pass


