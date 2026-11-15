"""The Eris window: chat log, mic button, text box, settings."""
import queue
import sys
import threading
import time
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
from .core import Eris
from .overlay import Overlay

RED = "#ff2a2a"
RED_DARK = "#b81d1d"
BG = "#141418"
PANEL = "#1d1d23"
MUTED = "#8b8b99"
STATES = {  # state -> (label, pill colour)
    "loading": ("Starting...", "#3a3a46"),
    "ready": ("Ready", "#2b7a4b"),
    "listening": ("Listening", RED),
    "thinking": ("Thinking", "#8a6d1f"),
    "guiding": ("Guiding", "#2d5fa8"),
    "off": ("Paused", "#3a3a46"),
}
FKEYS = [f"f{i}" for i in range(1, 13)]
OVERLAY_CMDS = {"box", "caption", "clear_box", "status", "monitor"}


class App(ctk.CTk):
    def __init__(self):
        settings.load()
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG)
        self.title("Eris")
        self.geometry("440x680")
        self.minsize(380, 520)
        self.attributes("-topmost", bool(config.PANEL_ON_TOP))
        self._set_icon()
        self.q = queue.Queue()
        self.log_file = settings.folder() / "eris.log"

        self.overlay = Overlay(self)
        self._build()
        self.eris = Eris(self)
        self._set_state("loading")

        keyboard.Listener(on_press=self.eris.on_press, on_release=self.eris.on_release).start()
        mouse.Listener(on_click=self.eris.on_click).start()
        self.after(30, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        threading.Thread(target=self.check_updates, daemon=True).start()
        if not settings.api_key():
            self.after(600, self.open_settings)
            self.log("hint", "First, paste your Anthropic API key into Settings.")

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
        # header
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(top, text="Eris", font=ctk.CTkFont(size=26, weight="bold")).pack(side="left")
        ctk.CTkButton(top, text="Settings", width=80, height=30, fg_color=PANEL,
                      hover_color="#2a2a33", command=self.open_settings).pack(side="right")
        self.update_btn = ctk.CTkButton(top, text="Update", width=110, height=30,
                                        fg_color="#2b7a4b", hover_color="#22603b",
                                        command=self.do_update)  # shown only when there's one
        self.pill = ctk.CTkLabel(top, text="", width=96, height=26, corner_radius=13,
                                 font=ctk.CTkFont(size=12, weight="bold"))
        self.pill.pack(side="right", padx=8)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16)
        self.active_switch = ctk.CTkSwitch(row, text="Active", progress_color=RED,
                                           command=lambda: self.eris.set_active(
                                               bool(self.active_switch.get())))
        self.active_switch.select()
        self.active_switch.pack(side="left")
        self.hint = ctk.CTkLabel(row, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.hint.pack(side="right")
        self._update_hint()

        # chat log
        self.chat = ctk.CTkTextbox(self, fg_color=PANEL, corner_radius=12, wrap="word",
                                   font=ctk.CTkFont(size=14), border_spacing=10)
        self.chat.pack(fill="both", expand=True, padx=16, pady=10)
        self.chat.tag_config("you", foreground="#9ec5ff")
        self.chat.tag_config("eris", foreground="#ffffff")
        self.chat.tag_config("name_eris", foreground=RED)
        self.chat.tag_config("info", foreground=MUTED)
        self.chat.tag_config("hint", foreground="#d9b45a")
        self.chat.tag_config("error", foreground="#ff7b7b")
        self.chat.configure(state="disabled")

        # step controls
        ctl = ctk.CTkFrame(self, fg_color="transparent")
        ctl.pack(fill="x", padx=16)
        for text, fn in (("Next step", lambda: self.eris.advance()),
                         ("Stop", lambda: self.eris.cancel()),
                         ("New task", lambda: self.eris.new_task())):
            ctk.CTkButton(ctl, text=text, height=32, fg_color=PANEL, hover_color="#2a2a33",
                          command=fn).pack(side="left", expand=True, fill="x", padx=3)

        # input
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(10, 16))
        self.mic = ctk.CTkButton(bottom, text="Hold to talk", width=110, height=42,
                                 fg_color=RED, hover_color=RED_DARK,
                                 font=ctk.CTkFont(size=13, weight="bold"))
        self.mic.pack(side="left")
        self.mic.bind("<ButtonPress-1>", lambda e: self.eris.start_listening())
        self.mic.bind("<ButtonRelease-1>", lambda e: self.eris.stop_listening())
        self.entry = ctk.CTkEntry(bottom, height=42, placeholder_text="...or type a question",
                                  fg_color=PANEL, border_width=0)
        self.entry.pack(side="left", fill="x", expand=True, padx=(8, 6))
        self.entry.bind("<Return>", lambda e: self._send())
        ctk.CTkButton(bottom, text="Ask", width=56, height=42, fg_color="#2d5fa8",
                      command=self._send).pack(side="left")

    # ---------- updates ----------
    def check_updates(self, manual=False):
        v = updater.remote_version()
        if v:
            notes = updater.changes()
            self.cmd("update_available", v)
            self.log("hint", f"New version v{v} is ready. Click the green Update button."
                     + (f"\n{notes}" if notes else ""))
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

    def _send(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self.eris.ask(text)

    def _append(self, who, text):
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} [{who}] {text}\n")
        except OSError:
            pass
        if who == "debug":
            return
        self.chat.configure(state="normal")
        if who == "you":
            self.chat.insert("end", "\nYou  ", "you")
            self.chat.insert("end", text + "\n", "you")
        elif who == "eris":
            self.chat.insert("end", "Eris  ", "name_eris")
            self.chat.insert("end", text + "\n", "eris")
        else:
            self.chat.insert("end", text + "\n", who)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _set_state(self, state):
        label, colour = STATES.get(state, STATES["ready"])
        self.pill.configure(text=label, fg_color=colour)
        self.mic.configure(text="Listening..." if state == "listening" else "Hold to talk")

    def _update_hint(self):
        self.hint.configure(text=f"{config.TALK_KEY.upper()} talk · {config.NEXT_KEY.upper()} next"
                                 f" · {config.CANCEL_KEY.upper()} stop")

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

    # ---------- settings ----------
    def open_settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.focus()
            return
        self._settings = SettingsWindow(self)


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app: App):
        super().__init__(app, fg_color=BG)
        self.app = app
        self.title("Eris settings")
        self.geometry("420x640")
        self.resizable(False, True)
        self.after(150, self.lift)
        self.after(150, self.focus)

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)

        def section(title):
            ctk.CTkLabel(body, text=title, font=ctk.CTkFont(size=15, weight="bold"),
                         anchor="w").pack(fill="x", pady=(14, 4))

        def label(text):
            ctk.CTkLabel(body, text=text, text_color=MUTED, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(fill="x")

        section("API key")
        self.key = ctk.CTkEntry(body, show="•", placeholder_text="sk-ant-...")
        self.key.insert(0, config.API_KEY)
        self.key.pack(fill="x")
        link = ctk.CTkLabel(body, text="Get a key at console.anthropic.com", text_color="#7fb0ff",
                            cursor="hand2", anchor="w", font=ctk.CTkFont(size=12, underline=True))
        link.pack(fill="x", pady=(2, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open("https://console.anthropic.com/settings/keys"))
        label("Saved only on this PC.")

        section("Brain")
        label("Thinking: low is fastest, high is most careful")
        self.effort = ctk.CTkSegmentedButton(body, values=["low", "medium", "high"],
                                             selected_color=RED, selected_hover_color=RED_DARK)
        self.effort.set(config.EFFORT)
        self.effort.pack(fill="x", pady=(2, 6))
        self.fast = ctk.CTkSwitch(body, text="Fast mode (quicker replies, costs 2x)",
                                  progress_color=RED)
        self.fast.select() if config.FAST_MODE else self.fast.deselect()
        self.fast.pack(fill="x")

        section("Voice")
        self.voice_on = ctk.CTkSwitch(body, text="Eris talks out loud", progress_color=RED)
        self.voice_on.select() if config.VOICE_ON else self.voice_on.deselect()
        self.voice_on.pack(fill="x")
        label("Talking speed")
        self.rate = ctk.CTkSlider(body, from_=-5, to=10, number_of_steps=15,
                                  button_color=RED, progress_color=RED)
        self.rate.set(config.VOICE_RATE)
        self.rate.pack(fill="x", pady=(2, 6))
        label("Speech recognition: tiny = fastest, small = most accurate")
        self.whisper = ctk.CTkSegmentedButton(body, values=["tiny.en", "base.en", "small.en"],
                                              selected_color=RED, selected_hover_color=RED_DARK)
        self.whisper.set(config.WHISPER_MODEL)
        self.whisper.pack(fill="x", pady=(2, 0))

        section("Keys")
        self.keys = {}
        for name, text in (("TALK_KEY", "Hold to talk"), ("NEXT_KEY", "Next step"),
                           ("CANCEL_KEY", "Stop")):
            r = ctk.CTkFrame(body, fg_color="transparent")
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=text, anchor="w").pack(side="left")
            m = ctk.CTkOptionMenu(r, values=[k.upper() for k in FKEYS], width=90,
                                  fg_color=PANEL, button_color="#2a2a33")
            m.set(getattr(config, name).upper())
            m.pack(side="right")
            self.keys[name] = m

        section("Red box")
        self.timeout_label = ctk.CTkLabel(body, text="", text_color=MUTED, anchor="w",
                                          font=ctk.CTkFont(size=12))
        self.timeout_label.pack(fill="x")
        self.timeout = ctk.CTkSlider(body, from_=5, to=60, number_of_steps=11,
                                     button_color=RED, progress_color=RED,
                                     command=self._timeout_text)
        self.timeout.set(config.BOX_TIMEOUT)
        self._timeout_text(config.BOX_TIMEOUT)
        self.timeout.pack(fill="x", pady=(2, 6))
        ctk.CTkButton(body, text="Test the red box", fg_color=PANEL, hover_color="#2a2a33",
                      command=self._test_box).pack(fill="x")
        label("Draws a box around this window. If it's off, tell Claude.")

        section("Window")
        self.on_top = ctk.CTkSwitch(body, text="Keep Eris window on top", progress_color=RED)
        self.on_top.select() if config.PANEL_ON_TOP else self.on_top.deselect()
        self.on_top.pack(fill="x")
        r = ctk.CTkFrame(body, fg_color="transparent")
        r.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(r, text=f"Version {updater.local_version()}", text_color=MUTED).pack(side="left")
        ctk.CTkButton(r, text="Check for updates", width=140, fg_color=PANEL, hover_color="#2a2a33",
                      command=lambda: threading.Thread(target=self.app.check_updates, args=(True,),
                                                       daemon=True).start()).pack(side="right")
        link2 = ctk.CTkLabel(body, text="Open log folder", text_color="#7fb0ff", cursor="hand2",
                             anchor="w", font=ctk.CTkFont(size=12, underline=True))
        link2.pack(fill="x", pady=(8, 0))
        link2.bind("<Button-1>", lambda e: webbrowser.open(settings.folder().as_uri()))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(foot, text="Save", fg_color=RED, hover_color=RED_DARK,
                      command=self._save).pack(side="right")
        ctk.CTkButton(foot, text="Cancel", fg_color=PANEL, hover_color="#2a2a33",
                      command=self.destroy).pack(side="right", padx=8)

    def _timeout_text(self, v):
        self.timeout_label.configure(text=f"Box hides itself after {int(float(v))} seconds")

    def _test_box(self):
        w = self
        x, y = w.winfo_rootx(), w.winfo_rooty()
        self.app.overlay.monitor(0, 0, w.winfo_screenwidth(), w.winfo_screenheight())
        self.app.overlay.box(x, y, x + w.winfo_width(), y + w.winfo_height(), "Test box")
        self.after(3000, self.app.overlay.clear_box)

    def _save(self):
        old_whisper = config.WHISPER_MODEL
        config.API_KEY = self.key.get().strip()
        config.EFFORT = self.effort.get()
        config.FAST_MODE = bool(self.fast.get())
        config.VOICE_ON = bool(self.voice_on.get())
        config.VOICE_RATE = int(round(self.rate.get()))
        config.WHISPER_MODEL = self.whisper.get()
        for name, m in self.keys.items():
            setattr(config, name, m.get().lower())
        config.BOX_TIMEOUT = int(round(self.timeout.get()))
        config.PANEL_ON_TOP = bool(self.on_top.get())
        settings.save()
        self.app.attributes("-topmost", config.PANEL_ON_TOP)
        self.app._update_hint()
        if config.WHISPER_MODEL != old_whisper:
            self.app.eris.load_ears()
        self.app.log("info", "Settings saved.")
        self.destroy()


def main():
    App().mainloop()
