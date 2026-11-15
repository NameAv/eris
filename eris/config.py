"""Eris settings. Change things here."""

# --- Brain (Claude) ---
BRAIN = "claude"        # "claude" (best), "claude-cheap" (Haiku, ~40x cheaper), "local" (free, Ollama)
API_KEY = ""            # set in the app: Settings -> API key
MODEL = "claude-opus-5-5"
CHEAP_MODEL = "claude-haiku-5-5"
LOCAL_MODEL = "qwen2.5vl:7b"   # any Ollama vision model
OLLAMA_URL = "http://localhost:11434"
EFFORT = "low"          # low = fastest replies. Try "medium" if steps get sloppy.
FAST_MODE = False       # True = up to ~2.5x faster output, but costs 2x per token.
MAX_TOKENS = 4000        # room for her (hidden) thinking plus the short reply

# --- Keys (hold TALK_KEY while speaking) ---
TALK_KEY = "f8"         # hold to talk
NEXT_KEY = "f9"         # "I did it" -> next step (for steps that aren't a click)
CANCEL_KEY = "f10"      # stop everything, clear the box

# --- Red box ---
BOX_COLOR = "#ff2a3d"
BOX_WIDTH = 4
BOX_PADDING = 4         # px of extra room around the target
BOX_TIMEOUT = 20        # seconds before the box hides itself no matter what
CLICK_SLOP = 12         # px: a click this close to the box still counts
SETTLE_DELAY = 0.7      # seconds to let the UI update after your click before looking again

# --- Screenshots ---
SHOT_MAX_WIDTH = 1280   # downscale before sending (smaller = faster upload)
SHOT_JPEG_QUALITY = 70

# --- Speech to text (runs locally) ---
WHISPER_MODEL = "base.en"   # "tiny.en" is faster, "small.en" is more accurate
WHISPER_HINT = ("Unity, Rigidbody, Rigidbody 2D, Inspector, Hierarchy, GameObject, prefab, "
                "collider, Box Collider, script, C#, Add Component, Scene view, Game view, Project window")

# --- Voice ---
VOICE_ON = True
VOICE_ENGINE = "natural"   # "natural" (free neural voice, needs internet) or "windows"
VOICE_NAME = "en-US-AvaNeural"
VOICE_RATE = 1          # Windows voice speed: -10 (slow) .. 10 (fast)

REFINE = True           # zoom in to snap the box exactly onto the target
WATCH = True            # watch the screen while waiting and react to what you do
PANEL_ON_TOP = False    # keep the Eris window above other windows

# --- Updates (GitHub "owner/repo"; the app checks it on startup) ---
UPDATE_REPO = "nameAv/eris"
UPDATE_BRANCH = "main"

MAX_STEPS = 20          # safety limit per task
