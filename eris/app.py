"""The Eris window: chat bubbles, talk button, settings. Crimson on near-black."""
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser

# Must happen before any window/screenshot so all coordinates are real pixels.
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

import customtkinter as ctk
from pynput import keyboard, mouse

from . import config, settings, updater
from . import theme as T
from .brain import local_models
from .core import Eris
from .overlay import Overlay
from .speech import PREVIEW, VOICES

FKEYS = [f"f{i}" for i in range(1, 13)]
OVERLAY_CMDS = {"box", "caption", "clear_box", "status", "monitor"}
SUGGESTIONS = ["How do I add a Rigidbody?", "How do I make a new C# script?",
               "Where do I change the camera background?"]
BRAINS = {  # segmented label -> (config value, description)
    "Best": ("claude", "Claude Opus. Smartest and most accurate. About 2 cents per step."),
    "Cheap": ("claude-cheap", "Claude Haiku. About 40x cheaper (5 dollars lasts thousands "
                              "of steps), a bit less precise."),
    "Free": ("local", "Runs on your own PC with Ollama. Totally free, no key. Needs a decent "
                      "graphics card, and it's less smart than Claude."),
}


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=T.FONT, size=size, weight=weight)


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
        r, g, b = (int(T.BG[i:i + 2], 16) for i in (1, 3, 5))
        caption = ctypes.c_int(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)     # title bar colour
        r, g, b = (int(T.ACCENT[i:i + 2], 16) for i in (1, 3, 5))
        border = ctypes.c_int(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)      # crimson outline
    except Exception:
        pass


class Avatar(tk.Canvas):
    """Glowing crimson orb with an E. Pulses while listening/thinking."""

    def __init__(self, master, size=54):
        super().__init__(master, width=size, height=size, bg=T.BG, highlightthickness=0)
        self.size, self.phase, self.pulsing = size, 0, False
        self._draw(0)
        self._tick()

    def _draw(self, glow):
        self.delete("all")
        s = self.size
        for i, c in enumerate(["#2a0c12", "#3d0f18", "#5a1320"]):
            pad = 1 + i * 3 - (1 if glow and i == 0 else 0)
            self.create_oval(pad, pad, s - pad, s - pad, fill=c, outline="")
        self.create_oval(10, 10, s - 10, s - 10, fill="#16090c",
                         outline=T.GLOW if glow else T.ACCENT, width=3)
        self.create_text(s / 2, s / 2 + 1, text="E", fill=T.TEXT, font=(T.FONT, 15, "bold"))

    def _tick(self):
        if self.pulsing:
            self.phase = (self.phase + 1) % 2
            self._draw(self.phase)
        self.after(420, self._tick)

    def pulse(self, on):
        self.pulsing = on
        if not on:
            self._draw(0)


class App(ctk.CTk):
    def __init__(self):
        settings.load()
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=T.BG)
        self.title("Eris")
        self.geometry("480x760")
        self.minsize(400, 560)
        self.attributes("-topmost", bool(config.PANEL_ON_TOP))
        self._set_icon()
        self.after(50, lambda: tint_titlebar(self))
        self.q = queue.Queue()
        self.log_file = settings.folder() / "eris.log"
        self.bubbles = []
        self.last_eris = None

        self.overlay = Overlay(self)
        self._build()
        self.eris = Eris(self)
        self._set_state("loading")

        keyboard.Listener(on_press=self.eris.on_press, on_release=self.eris.on_release).start()
        mouse.Listener(on_click=self.eris.on_click).start()
        self.after(30, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        threading.Thread(target=self.check_updates, daemon=True).start()
        if config.BRAIN != "local" and not settings.api_key():
            self.after(700, self.open_settings)

    # ---------- thread-safe API used by Eris ----------
    def cmd(self, name, *args):
        self.q.put((name, args))

    def log(self, who, text):
        self.q.put(("log", (who, text)))

    def _pump(self):
        try:
            while True:
                name, args = self.q.get_nowait()
                if name in OVERLAY_CMDS:
                    getattr(self.overlay, name)(*args)
                elif name == "log":
                    self._append(*args)
                elif name == "state":
                    self._set_state(*args)
                elif name == "update_available":
                    self.update_btn.configure(text=f"Update to v{args[0]}")
                    self.update_btn.pack(side="right", padx=(0, 8))
                elif name == "restart":
                    updater.restart()
                    self._quit()
                elif name == "update_failed":
                    self.update_btn.configure(state="normal", text="Retry update")
                elif name == "active":
                    self.active_switch.select() if args[0] else self.active_switch.deselect()
        except queue.Empty:
            pass
        self.after(30, self._pump)

    # ---------- layout ----------
    def _build(self):
        # header: avatar, name, status chip
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 8))
        self.avatar = Avatar(top)
        self.avatar.pack(side="left")
        names = ctk.CTkFrame(top, fg_color="transparent")
        names.pack(side="left", padx=12)
        ctk.CTkLabel(names, text="Eris", font=font(24, "bold"), text_color=T.TEXT,
                     height=26).pack(anchor="w")
        self.subtitle = ctk.CTkLabel(names, text="", font=font(12), text_color=T.MUTED, height=16)
        self.subtitle.pack(anchor="w")
        ctk.CTkButton(top, text="Settings", width=78, height=32, corner_radius=12, font=font(12),
                      fg_color=T.CARD_2, hover_color=T.BORDER, text_color=T.TEXT,
                      command=self.open_settings).pack(side="right")
        self.chip = ctk.CTkFrame(top, fg_color=T.CARD_2, corner_radius=14, height=28)
        self.chip.pack(side="right", padx=8)
        self.chip_dot = ctk.CTkFrame(self.chip, width=9, height=9, corner_radius=4,
                                     fg_color=T.MUTED)
        self.chip_dot.pack(side="left", padx=(11, 6))
        self.chip_text = ctk.CTkLabel(self.chip, text="", font=font(12, "bold"),
                                      text_color=T.TEXT)
        self.chip_text.pack(side="left", padx=(0, 12))
        self.update_btn = ctk.CTkButton(top, text="Update", width=110, height=30, corner_radius=15,
                                        fg_color="#1f6b45", hover_color="#185437",
                                        font=font(12, "bold"), command=self.do_update)

        # thin crimson line
        ctk.CTkFrame(self, fg_color=T.ACCENT, height=2, corner_radius=1).pack(fill="x", padx=18)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(10, 0))
        self.active_switch = ctk.CTkSwitch(
            row, text="Active", font=font(13), progress_color=T.ACCENT, button_color=T.TEXT,
            button_hover_color="#ffffff", fg_color=T.BORDER,
            command=lambda: self.eris.set_active(bool(self.active_switch.get())))
        self.active_switch.select()
        self.active_switch.pack(side="left")
        self.hint = ctk.CTkLabel(row, text="", text_color=T.MUTED, font=font(12))
        self.hint.pack(side="right")
        self._update_hint()

        # chat
        self.chat = ctk.CTkScrollableFrame(self, fg_color=T.CARD, corner_radius=18,
                                           scrollbar_button_color=T.BORDER,
                                           scrollbar_button_hover_color=T.ACCENT_DIM)
        self.chat.pack(fill="both", expand=True, padx=18, pady=12)
        self.chat.bind("<Configure>", self._rewrap)
        self._welcome()

        # step controls
        ctl = ctk.CTkFrame(self, fg_color="transparent")
        ctl.pack(fill="x", padx=15)
        for text, fn in (("Next step", lambda: self.eris.advance()),
                         ("Stop", lambda: self.eris.cancel()),
                         ("New task", lambda: self.eris.new_task())):
            ctk.CTkButton(ctl, text=text, height=34, corner_radius=17, font=font(13),
                          fg_color="transparent", border_width=1, border_color=T.BORDER,
                          hover_color=T.CARD_2, text_color=T.TEXT,
                          command=fn).pack(side="left", expand=True, fill="x", padx=3)

        # type box
        typ = ctk.CTkFrame(self, fg_color=T.CARD_2, corner_radius=22)
        typ.pack(fill="x", padx=18, pady=(12, 8))
        self.entry = ctk.CTkEntry(typ, height=40, placeholder_text="Type a question...",
                                  fg_color=T.CARD_2, border_width=0, font=font(14),
                                  text_color=T.TEXT, placeholder_text_color=T.MUTED)
        self.entry.pack(side="left", fill="x", expand=True, padx=(14, 4), pady=2)
        self.entry.bind("<Return>", lambda e: self._send())
        ctk.CTkButton(typ, text="Ask", width=56, height=36, corner_radius=14, font=font(13, "bold"),
                      fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                      command=self._send).pack(side="right", padx=4, pady=3)

        # big talk button
        self.mic = ctk.CTkButton(self, text="", height=52, corner_radius=26,
                                 fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                                 font=font(15, "bold"), text_color="#ffffff")
        self.mic.pack(fill="x", padx=18, pady=(0, 18))
        self.mic.bind("<ButtonPress-1>", lambda e: self.eris.start_listening())
        self.mic.bind("<ButtonRelease-1>", lambda e: self.eris.stop_listening())

    def _welcome(self):
        box = ctk.CTkFrame(self.chat, fg_color="transparent")
        box.pack(fill="x", padx=8, pady=(14, 6))
        ctk.CTkLabel(box, text="Hi, I'm Eris", font=font(20, "bold"),
                     text_color=T.TEXT).pack(anchor="w")
        self.welcome_label = ctk.CTkLabel(
            box, text="Ask me how to do something and I'll point at it on your screen, "
                      "one step at a time.", font=font(13), text_color=T.MUTED,
            wraplength=340, justify="left")
        self.welcome_label.pack(anchor="w", pady=(2, 10))
        for s in SUGGESTIONS:
            ctk.CTkButton(box, text=s, height=30, corner_radius=15, anchor="w", font=font(12),
                          fg_color=T.CARD_2, hover_color=T.ACCENT_DIM, text_color=T.TEXT,
                          command=lambda s=s: self.eris.ask(s)).pack(anchor="w", pady=3)

    # ---------- chat bubbles ----------
    def _wrap(self):
        return max(200, int(self.chat.winfo_width() * 0.74))

    def _rewrap(self, _e=None):
        w = self._wrap()
        for b in self.bubbles:
            if b.winfo_exists():
                b.configure(wraplength=w)
        self.welcome_label.configure(wraplength=w + 40)

    def _scroll_end(self):
        self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _bubble(self, row, text, bg):
        return ctk.CTkLabel(row, text=text, fg_color=bg, corner_radius=16, text_color=T.TEXT,
                            font=font(14), wraplength=self._wrap(), justify="left",
                            padx=14, pady=9)

    def _append(self, who, text):
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} [{who}] {text}\n")
        except OSError:
            pass
        if who == "debug":
            return
        if who == "eris" and self.last_eris is not None and self.last_eris.winfo_exists():
            self.last_eris.configure(text=self.last_eris.cget("text") + "\n" + text)
            self._scroll_end()
            return
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=4)
        if who == "you":
            b = self._bubble(row, text, T.ACCENT_DIM)
            b.pack(side="right")
            self.last_eris = None
        elif who == "eris":
            ctk.CTkLabel(row, text="ERIS", font=font(10, "bold"), text_color=T.ACCENT,
                         height=14).pack(anchor="w", padx=6)
            b = self._bubble(row, text, T.CARD_2)
            b.pack(side="left")
            self.last_eris = b
        else:
            colour = {"hint": T.GOLD, "error": T.ERROR}.get(who, T.MUTED)
            b = ctk.CTkLabel(row, text=text, font=font(12), text_color=colour,
                             wraplength=self._wrap() + 60, justify="center")
            b.pack()
            self.last_eris = None
        self.bubbles.append(b)
        for old in self.chat.winfo_children()[:-150]:   # keep the chat light
            old.destroy()
        self.bubbles = [x for x in self.bubbles if x.winfo_exists()]
        self._scroll_end()

    def _send(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self.eris.ask(text)

    def _set_state(self, state):
        label, colour = T.STATES.get(state, T.STATES["ready"])
        self.chip_text.configure(text=label)
        self.chip_dot.configure(fg_color=colour)
        self.avatar.pulse(state in ("listening", "thinking"))
        if state == "listening":
            self.mic.configure(text="Listening... let go when you're done", fg_color=T.GLOW)
        else:
            self.mic.configure(text=f"Hold to talk  ·  {config.TALK_KEY.upper()}",
                               fg_color=T.ACCENT)
        brain = {"claude": "Opus brain", "claude-cheap": "Haiku brain",
                 "local": "free local brain"}.get(config.BRAIN, "")
        self.subtitle.configure(text=f"screen guide · {brain}")

    def _update_hint(self):
        self.hint.configure(text=f"{config.TALK_KEY.upper()} talk   {config.NEXT_KEY.upper()} next"
                                 f"   {config.CANCEL_KEY.upper()} stop")

    def _set_icon(self):
        if sys.platform != "win32":
            return
        try:
            from .icon import path
            ico = str(path())
            self.iconbitmap(ico)
            self.after(300, lambda: self.iconbitmap(ico))  # CTk resets it once on start
        except Exception:
            pass

    def _quit(self):
        self.eris.cancel()
        self.destroy()

    # ---------- updates ----------
    def check_updates(self, manual=False):
        v = updater.remote_version()
        if v:
            notes = updater.changes()
            self.cmd("update_available", v)
            self.log("hint", f"New version v{v} is ready. Click the green Update button."
                     + (f"\n{notes.splitlines()[0]}" if notes else ""))
        elif manual:
            self.log("info", "You're on the latest version." if config.UPDATE_REPO
                     else "Updates aren't set up yet.")

    def do_update(self):
        self.update_btn.configure(state="disabled", text="Updating...")
        self.eris.cancel()

        def work():
            try:
                if updater.install_update(self.log):
                    self.log("info", "Updated! Restarting...")
                    self.cmd("restart")
                    return
            except Exception as e:
                self.log("error", f"Update failed: {e}")
            self.cmd("update_failed")
        threading.Thread(target=work, daemon=True).start()

    # ---------- settings ----------
    def open_settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.focus()
            return
        self._settings = SettingsWindow(self)


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app: App):
        super().__init__(app, fg_color=T.BG)
        self.app = app
        self._restore = None
        self.title("Eris settings")
        self.geometry("460x700")
        self.minsize(420, 500)
        self.after(150, self.lift)
        self.after(150, self.focus)
        self.after(200, lambda: tint_titlebar(self))

        ctk.CTkLabel(self, text="Settings", font=font(22, "bold"), text_color=T.TEXT
                     ).pack(anchor="w", padx=20, pady=(16, 4))
        body = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                      scrollbar_button_color=T.BORDER)
        body.pack(fill="both", expand=True, padx=10)

        # ---- Brain ----
        c = self._card(body, "Brain")
        self.brain = self._seg(c, list(BRAINS), command=self._brain_changed)
        self.brain.set(next((k for k, v in BRAINS.items() if v[0] == config.BRAIN), "Best"))
        self.brain_desc = self._muted(c, "")
        self.claude_box = ctk.CTkFrame(c, fg_color="transparent")
        self._label(self.claude_box, "API key")
        self.key = ctk.CTkEntry(self.claude_box, show="•", placeholder_text="sk-ant-...",
                                fg_color=T.CARD_2, border_color=T.BORDER, height=36)
        self.key.insert(0, config.API_KEY)
        self.key.pack(fill="x")
        self._link(self.claude_box, "Get a key at console.anthropic.com",
                   "https://console.anthropic.com/settings/keys")
        self._label(self.claude_box, "Thinking: low is fastest, high is most careful")
        self.effort = self._seg(self.claude_box, ["low", "medium", "high"])
        self.effort.set(config.EFFORT)
        self.fast = self._switch(self.claude_box, "Fast mode (Best only, quicker, costs 2x)",
                                 config.FAST_MODE)
        self.local_box = ctk.CTkFrame(c, fg_color="transparent")
        self._muted(self.local_box, "One-time setup:\n1. Install Ollama (link below) and open it.\n"
                                    "2. Open Command Prompt and run the command below.\n"
                                    "3. Click Test.")
        self._link(self.local_box, "Download Ollama", "https://ollama.com/download")
        cmd_row = ctk.CTkFrame(self.local_box, fg_color=T.CARD_2, corner_radius=10)
        cmd_row.pack(fill="x", pady=6)
        self.cmd_label = ctk.CTkLabel(cmd_row, text="", text_color=T.TEXT,
                                      font=ctk.CTkFont(family="Consolas", size=13))
        self.cmd_label.pack(side="left", padx=10, pady=6)
        ctk.CTkButton(cmd_row, text="Copy", width=56, height=26, corner_radius=13,
                      fg_color=T.ACCENT_DIM, hover_color=T.ACCENT,
                      command=self._copy_cmd).pack(side="right", padx=6)
        self._label(self.local_box, "Model")
        self.local_model = ctk.CTkEntry(self.local_box, fg_color=T.CARD_2, border_color=T.BORDER,
                                        height=34)
        self.local_model.insert(0, config.LOCAL_MODEL)
        self.local_model.pack(fill="x")
        self.local_model.bind("<KeyRelease>", lambda e: self._update_cmd())
        trow = ctk.CTkFrame(self.local_box, fg_color="transparent")
        trow.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(trow, text="Test", width=80, height=30, corner_radius=15, fg_color=T.CARD_2,
                      hover_color=T.BORDER, command=self._test_local).pack(side="left")
        self.local_status = ctk.CTkLabel(trow, text="", font=font(12), text_color=T.MUTED,
                                         wraplength=280, justify="left")
        self.local_status.pack(side="left", padx=10)
        self._update_cmd()
        self._brain_changed(self.brain.get())

        # ---- Voice ----
        c = self._card(body, "Voice")
        self.voice_on = self._switch(c, "Eris talks out loud", config.VOICE_ON)
        self._label(c, "Voice type")
        self.engine = self._seg(c, ["Natural", "Windows"])
        self.engine.set("Natural" if config.VOICE_ENGINE == "natural" else "Windows")
        self._muted(c, "Natural sounds human (free, needs internet). Windows works offline.")
        self._label(c, "Who she sounds like")
        vrow = ctk.CTkFrame(c, fg_color="transparent")
        vrow.pack(fill="x", pady=(4, 0))
        names = list(VOICES)
        current = next((k for k, v in VOICES.items() if v == config.VOICE_NAME), names[0])
        self.voice_pick = ctk.CTkOptionMenu(vrow, values=names, fg_color=T.CARD_2,
                                            button_color=T.ACCENT_DIM, button_hover_color=T.ACCENT,
                                            dropdown_fg_color=T.CARD_2,
                                            dropdown_hover_color=T.ACCENT_DIM)
        self.voice_pick.set(current)
        self.voice_pick.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(vrow, text="▶ Preview", width=96, corner_radius=14, fg_color=T.ACCENT,
                      hover_color=T.ACCENT_HOVER, command=self._preview).pack(side="right", padx=(8, 0))
        self._label(c, "Talking speed")
        self.rate = ctk.CTkSlider(c, from_=-5, to=10, number_of_steps=15, button_color=T.ACCENT,
                                  button_hover_color=T.GLOW, progress_color=T.ACCENT,
                                  fg_color=T.BORDER)
        self.rate.set(config.VOICE_RATE)
        self.rate.pack(fill="x", pady=(4, 2))
        self._label(c, "Hearing you: tiny = fastest, small = most accurate")
        self.whisper = self._seg(c, ["tiny.en", "base.en", "small.en"])
        self.whisper.set(config.WHISPER_MODEL)

        # ---- Keys ----
        c = self._card(body, "Keys")
        self.keys = {}
        for name, text in (("TALK_KEY", "Hold to talk"), ("NEXT_KEY", "Next step"),
                           ("CANCEL_KEY", "Stop")):
            r = ctk.CTkFrame(c, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=text, font=font(13), text_color=T.TEXT).pack(side="left")
            m = ctk.CTkOptionMenu(r, values=[k.upper() for k in FKEYS], width=90,
                                  fg_color=T.CARD_2, button_color=T.ACCENT_DIM,
                                  button_hover_color=T.ACCENT, dropdown_fg_color=T.CARD_2)
            m.set(getattr(config, name).upper())
            m.pack(side="right")
            self.keys[name] = m

        # ---- Red box ----
        c = self._card(body, "Red box")
        self.timeout_label = self._label(c, "")
        self.timeout = ctk.CTkSlider(c, from_=5, to=60, number_of_steps=11, button_color=T.ACCENT,
                                     button_hover_color=T.GLOW, progress_color=T.ACCENT,
                                     fg_color=T.BORDER, command=self._timeout_text)
        self.timeout.set(config.BOX_TIMEOUT)
        self._timeout_text(config.BOX_TIMEOUT)
        self.timeout.pack(fill="x", pady=(4, 8))
        ctk.CTkButton(c, text="Test the red box", corner_radius=14, fg_color=T.CARD_2,
                      hover_color=T.BORDER, command=self._test_box).pack(fill="x")
        self._muted(c, "Draws the box around this window for 3 seconds.")

        # ---- App ----
        c = self._card(body, "App")
        self.on_top = self._switch(c, "Keep Eris window on top", config.PANEL_ON_TOP)
        r = ctk.CTkFrame(c, fg_color="transparent")
        r.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(r, text=f"Version {updater.local_version()}", font=font(12),
                     text_color=T.MUTED).pack(side="left")
        ctk.CTkButton(r, text="Check for updates", width=140, corner_radius=14, fg_color=T.CARD_2,
                      hover_color=T.BORDER,
                      command=lambda: threading.Thread(target=self.app.check_updates, args=(True,),
                                                       daemon=True).start()).pack(side="right")
        self._link(c, "Open log folder", settings.folder().as_uri())

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=12)
        ctk.CTkButton(foot, text="Save", width=110, height=38, corner_radius=19, fg_color=T.ACCENT,
                      hover_color=T.ACCENT_HOVER, font=font(14, "bold"),
                      command=self._save).pack(side="right")
        ctk.CTkButton(foot, text="Cancel", width=90, height=38, corner_radius=19,
                      fg_color="transparent", border_width=1, border_color=T.BORDER,
                      hover_color=T.CARD_2, command=self.destroy).pack(side="right", padx=8)

    # ---- little builders ----
    def _card(self, parent, title):
        c = ctk.CTkFrame(parent, fg_color=T.CARD, corner_radius=16)
        c.pack(fill="x", pady=6, padx=6)
        inner = ctk.CTkFrame(c, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(inner, text=title.upper(), font=font(11, "bold"), text_color=T.ACCENT
                     ).pack(anchor="w", pady=(0, 6))
        return inner

    def _label(self, parent, text):
        lbl = ctk.CTkLabel(parent, text=text, font=font(12), text_color=T.MUTED, anchor="w")
        lbl.pack(fill="x", pady=(8, 0))
        return lbl

    def _muted(self, parent, text):
        lbl = ctk.CTkLabel(parent, text=text, font=font(12), text_color=T.MUTED, anchor="w",
                           justify="left", wraplength=360)
        lbl.pack(fill="x", pady=(4, 0))
        return lbl

    def _link(self, parent, text, url):
        lbl = ctk.CTkLabel(parent, text=text, text_color=T.GLOW, cursor="hand2", anchor="w",
                           font=ctk.CTkFont(family=T.FONT, size=12, underline=True))
        lbl.pack(fill="x", pady=(4, 0))
        lbl.bind("<Button-1>", lambda e: webbrowser.open(url))

    def _seg(self, parent, values, command=None):
        s = ctk.CTkSegmentedButton(parent, values=values, command=command, height=32,
                                   fg_color=T.CARD_2, unselected_color=T.CARD_2,
                                   unselected_hover_color=T.BORDER, selected_color=T.ACCENT,
                                   selected_hover_color=T.ACCENT_HOVER, font=font(13))
        s.pack(fill="x", pady=(4, 0))
        return s

    def _switch(self, parent, text, on):
        s = ctk.CTkSwitch(parent, text=text, font=font(13), progress_color=T.ACCENT,
                          fg_color=T.BORDER, button_color=T.TEXT, button_hover_color="#ffffff")
        s.select() if on else s.deselect()
        s.pack(fill="x", pady=(8, 0))
        return s

    # ---- behaviour ----
    def _brain_changed(self, label):
        self.brain_desc.configure(text=BRAINS[label][1])
        if BRAINS[label][0] == "local":
            self.claude_box.pack_forget()
            self.local_box.pack(fill="x")
        else:
            self.local_box.pack_forget()
            self.claude_box.pack(fill="x")

    def _update_cmd(self):
        self.cmd_label.configure(text=f"ollama pull {self.local_model.get().strip() or 'qwen2.5vl:7b'}")

    def _copy_cmd(self):
        self.clipboard_clear()
        self.clipboard_append(self.cmd_label.cget("text"))
        self.local_status.configure(text="Copied! Paste it into Command Prompt.", text_color=T.MUTED)

    def _test_local(self):
        want = self.local_model.get().strip()
        self.local_status.configure(text="Checking...", text_color=T.MUTED)

        def work():
            models = local_models()
            if models is None:
                msg, colour = "Can't find Ollama. Is it installed and running?", T.ERROR
            elif not any(m == want or m.split(":")[0] == want for m in models):
                msg, colour = f"Ollama works, but {want} isn't downloaded yet. Run the command above.", T.GOLD
            else:
                msg, colour = "All good! Eris can think for free.", "#4fd18b"
            self.after(0, lambda: self.local_status.configure(text=msg, text_color=colour))
        threading.Thread(target=work, daemon=True).start()

    def _preview(self):
        if self._restore is None:   # remember the saved voice in case you cancel
            self._restore = (config.VOICE_ENGINE, config.VOICE_NAME, config.VOICE_RATE)
        config.VOICE_ENGINE = "natural" if self.engine.get() == "Natural" else "windows"
        config.VOICE_NAME = VOICES[self.voice_pick.get()]
        config.VOICE_RATE = int(round(self.rate.get()))
        self.app.eris.voice.stop()
        self.app.eris.voice.say(PREVIEW, force=True)

    def _timeout_text(self, v):
        self.timeout_label.configure(text=f"Box hides itself after {int(float(v))} seconds")

    def _test_box(self):
        x, y = self.winfo_rootx(), self.winfo_rooty()
        ov = self.app.overlay
        ov.monitor(0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        ov.box(x, y, x + self.winfo_width(), y + self.winfo_height(), "This is the red box")
        self.after(3000, ov.clear_box)

    def destroy(self):
        if self._restore:   # previewed a voice but didn't save
            config.VOICE_ENGINE, config.VOICE_NAME, config.VOICE_RATE = self._restore
        super().destroy()

    def _save(self):
        old_whisper = config.WHISPER_MODEL
        config.BRAIN = BRAINS[self.brain.get()][0]
        config.API_KEY = self.key.get().strip()
        config.EFFORT = self.effort.get()
        config.FAST_MODE = bool(self.fast.get())
        config.LOCAL_MODEL = self.local_model.get().strip() or "qwen2.5vl:7b"
        config.VOICE_ON = bool(self.voice_on.get())
        config.VOICE_ENGINE = "natural" if self.engine.get() == "Natural" else "windows"
        config.VOICE_NAME = VOICES[self.voice_pick.get()]
        config.VOICE_RATE = int(round(self.rate.get()))
        config.WHISPER_MODEL = self.whisper.get()
        for name, m in self.keys.items():
            setattr(config, name, m.get().lower())
        config.BOX_TIMEOUT = int(round(self.timeout.get()))
        config.PANEL_ON_TOP = bool(self.on_top.get())
        settings.save()
        self._restore = None
        self.app.attributes("-topmost", config.PANEL_ON_TOP)
        self.app._update_hint()
        self.app._set_state("ready")
        if config.WHISPER_MODEL != old_whisper:
            self.app.eris.load_ears()
        if config.BRAIN != "local" and not config.API_KEY:
            self.app.log("hint", "That brain needs an API key. Add one, or pick Free.")
        self.app.log("info", "Settings saved.")
        self.destroy()


def main():
    App().mainloop()
