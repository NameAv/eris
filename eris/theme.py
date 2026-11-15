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
