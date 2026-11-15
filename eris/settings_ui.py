"""Eris's settings window: a sidebar of sections, and every change saves instantly."""
import threading
import time
import webbrowser

import customtkinter as ctk
from PIL import Image, ImageDraw

from . import config, settings, updater
from . import theme as T
from .brain import local_models
from .speech import PREVIEW, VOICES
from .theme import font, tint_titlebar

PAGES = [("brain", "Brain"), ("voice", "Voice"), ("guiding", "Guiding"), ("privacy", "Privacy"),
         ("eris", "Eris"), ("keys", "Keys"), ("app", "App")]
SUBTITLES = {
    "brain": "What does Eris think with?",
    "voice": "How she sounds and how well she hears you.",
    "guiding": "How she points things out on your screen.",
    "privacy": "What she never looks at.",
    "eris": "Her personality, her picture and what she remembers.",
    "keys": "Click a key, then press the one you want.",
    "app": "Updates, logs and resetting things.",
}
BRAINS = [
    ("claude", "Best", "Claude Opus", "about 2¢ a step",
     "Smartest and most accurate. Needs an API key."),
    ("claude-cheap", "Cheap", "Claude Haiku", "about 40x cheaper",
     "$5 lasts thousands of steps. A bit less precise. Needs an API key."),
    ("local", "Free", "Runs on your PC", "free",
     "Uses your graphics card through Ollama. No key, nothing leaves your PC. Less smart."),
]
VOICE_INFO = {  # label in speech.VOICES -> (name, accent/feel)
    label: (label.split(" (")[0], label.split(" (")[1].rstrip(")")) for label in VOICES
}
KEY_NAMES = {f"F{i}": f"f{i}" for i in range(1, 21)}
KEY_NAMES.update({"Insert": "insert", "Home": "home", "End": "end", "Prior": "page_up",
                  "Next": "page_down", "Pause": "pause", "Scroll_Lock": "scroll_lock"})


def key_label(name):
    return name.replace("_", " ").title() if not name.startswith("f") else name.upper()


class SettingsWindow(ctk.CTkToplevel):
    last_page = "brain"

    def __init__(self, app, page=None):
        super().__init__(app, fg_color=T.BG)
        self.app = app
        self.title("Eris settings")
        self.geometry("800x620")
        self.minsize(700, 520)
        self.after(150, self.lift)
        self.after(150, self.focus)
        self.after(200, lambda: tint_titlebar(self))
        self._jobs = {}
        self._capturing = None
        self._reset_armed = False

        # sidebar
        side = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=0, width=180)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        ctk.CTkLabel(side, text="Settings", font=font(20, "bold"), text_color=T.TEXT
                     ).pack(anchor="w", padx=18, pady=(20, 14))
        self.nav = {}
        for key, label in PAGES:
            item = ctk.CTkFrame(side, fg_color="transparent", height=38)
            item.pack(fill="x", padx=8, pady=1)
            bar = ctk.CTkFrame(item, width=3, height=22, corner_radius=2, fg_color="transparent")
            bar.pack(side="left", padx=(2, 6))
            btn = ctk.CTkButton(item, text=label, anchor="w", height=36, corner_radius=10,
                                font=font(14), fg_color="transparent", hover_color=T.CARD_2,
                                text_color=T.MUTED, command=lambda k=key: self.show(k))
            btn.pack(side="left", fill="x", expand=True)
            self.nav[key] = (btn, bar)
        ctk.CTkLabel(side, text=f"Eris v{updater.local_version()}", font=font(11),
                     text_color=T.MUTED).pack(side="bottom", anchor="w", padx=18, pady=14)

        # content
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)
        head = ctk.CTkFrame(main, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(20, 4))
        self.h_title = ctk.CTkLabel(head, text="", font=font(22, "bold"), text_color=T.TEXT)
        self.h_title.pack(side="left")
        self.toast_label = ctk.CTkLabel(head, text="", font=font(12, "bold"), text_color="#4fd18b")
        self.toast_label.pack(side="right")
        self.h_sub = ctk.CTkLabel(main, text="", font=font(13), text_color=T.MUTED, anchor="w")
        self.h_sub.pack(fill="x", padx=26)
        self.body = ctk.CTkScrollableFrame(main, fg_color="transparent",
                                           scrollbar_button_color=T.BORDER)
        self.body.pack(fill="both", expand=True, padx=14, pady=(10, 14))
        self.show(page or SettingsWindow.last_page)

    # ================= plumbing =================
    def show(self, key):
        SettingsWindow.last_page = key
        self._stop_capture()
        for k, (btn, bar) in self.nav.items():
            on = k == key
            btn.configure(fg_color=T.CARD_2 if on else "transparent",
                          text_color=T.TEXT if on else T.MUTED)
            bar.configure(fg_color=T.ACCENT if on else "transparent")
        self.h_title.configure(text=dict(PAGES)[key])
        self.h_sub.configure(text=SUBTITLES[key])
        for w in self.body.winfo_children():
            w.destroy()
        getattr(self, f"_page_{key}")()
        self.after(30, lambda: self.body._parent_canvas.yview_moveto(0))

    def set(self, **values):
        """Change settings, save them and apply them right away."""
        for k, v in values.items():
            setattr(config, k, v)
        settings.save()
        self.app.on_settings_changed(values.keys())
        self.toast()

    def toast(self, text="✓ Saved"):
        self.toast_label.configure(text=text)
        self._later("toast", 1600, lambda: self.toast_label.configure(text=""))

    def _later(self, name, ms, fn):
        """Run fn after ms, replacing any earlier pending one with the same name."""
        if name in self._jobs:
            try:
                self.after_cancel(self._jobs[name])
            except Exception:
                pass
        self._jobs[name] = self.after(ms, fn)

    def _ui(self, fn):
        """Run fn on the Tk thread (from a background thread), if the window still exists."""
        self.after(0, lambda: self.winfo_exists() and fn())

    def destroy(self):
        self._stop_capture()
        super().destroy()

    # ================= building blocks =================
    def card(self, title=None, sub=None):
        c = ctk.CTkFrame(self.body, fg_color=T.CARD, corner_radius=16)
        c.pack(fill="x", padx=10, pady=7)
        inner = ctk.CTkFrame(c, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        if title:
            ctk.CTkLabel(inner, text=title.upper(), font=font(11, "bold"), text_color=T.ACCENT,
                         anchor="w").pack(fill="x")
        if sub:
            self.muted(inner, sub).pack_configure(pady=(2, 4))
        return inner

    def muted(self, parent, text, size=12, wrap=500):
        lbl = ctk.CTkLabel(parent, text=text, font=font(size), text_color=T.MUTED, anchor="w",
                           justify="left", wraplength=wrap)
        lbl.pack(fill="x")
        return lbl

    def row(self, parent, title, help=None):
        """A settings row: title (and help) on the left, the control on the right."""
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", pady=6)
        right = ctk.CTkFrame(r, fg_color="transparent")
        right.pack(side="right", padx=(14, 0))
        left = ctk.CTkFrame(r, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=title, font=font(14), text_color=T.TEXT, anchor="w").pack(fill="x")
        if help:
            self.muted(left, help, wrap=330)
        return right

    def switch(self, parent, title, help, key, on_change=None):
        right = self.row(parent, title, help)
        sw = ctk.CTkSwitch(right, text="", width=46, progress_color=T.ACCENT, fg_color=T.BORDER,
                           button_color=T.TEXT, button_hover_color="#ffffff",
                           command=lambda: (self.set(**{key: bool(sw.get())}),
                                            on_change and on_change()))
        sw.select() if getattr(config, key) else sw.deselect()
        sw.pack()
        return sw

    def seg(self, parent, values, current, command, width=None):
        s = ctk.CTkSegmentedButton(parent, values=values, command=command, height=32,
                                   fg_color=T.CARD_2, unselected_color=T.CARD_2,
                                   unselected_hover_color=T.BORDER, selected_color=T.ACCENT,
                                   selected_hover_color=T.ACCENT_HOVER, font=font(13))
        if width:
            s.configure(width=width)
        s.set(current)
        s.pack(fill="x" if not width else None)
        return s

    def button(self, parent, text, command, primary=False, width=None):
        b = ctk.CTkButton(parent, text=text, command=command, height=34, corner_radius=12,
                          font=font(13, "bold" if primary else "normal"),
                          fg_color=T.ACCENT if primary else T.CARD_2,
                          hover_color=T.ACCENT_HOVER if primary else T.BORDER,
                          text_color="#ffffff" if primary else T.TEXT)
        if width:
            b.configure(width=width)
        return b

    def entry(self, parent, value, key, placeholder="", show=None, on_saved=None):
        """A text box that saves itself shortly after you stop typing."""
        e = ctk.CTkEntry(parent, height=36, fg_color=T.CARD_2, border_color=T.BORDER,
                         text_color=T.TEXT, placeholder_text=placeholder, show=show)
        if value:
            e.insert(0, value)

        def save(*_):
            v = e.get().strip()
            if v != getattr(config, key):
                self.set(**{key: v})
                on_saved and on_saved(v)
        e.bind("<KeyRelease>", lambda _e: self._later(f"entry-{key}", 700, save))
        e.bind("<FocusOut>", save)
        e.bind("<Return>", save)
        return e

    def select_card(self, parent, selected, title, tag, text, command, image=None):
        """A big clickable option card (crimson border when chosen)."""
        c = ctk.CTkFrame(parent, fg_color=T.CARD_2 if selected else T.CARD, corner_radius=14,
                         border_width=2, border_color=T.ACCENT if selected else T.BORDER)
        inner = ctk.CTkFrame(c, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=title, font=font(15, "bold"), text_color=T.TEXT).pack(side="left")
        if tag:   # price/info tag on its own line so it never collides with the title
            ctk.CTkLabel(inner, text=f"  {tag}  ", font=font(11, "bold"), corner_radius=8,
                         fg_color=T.ACCENT_DIM if selected else T.BORDER, text_color=T.TEXT
                         ).pack(anchor="w", pady=(4, 0))
        if image is not None:
            ctk.CTkLabel(inner, text="", image=image).pack(pady=(8, 4))
        if text:
            ctk.CTkLabel(inner, text=text, font=font(12), text_color=T.MUTED, anchor="w",
                         justify="left", wraplength=150).pack(fill="x", pady=(4, 0))
        for w in [c, inner, top] + list(inner.winfo_children()) + list(top.winfo_children()):
            w.bind("<Button-1>", lambda _e: command())
            _hand(w)
        return c

    def status_line(self, parent):
        lbl = ctk.CTkLabel(parent, text="", font=font(12), text_color=T.MUTED, anchor="w",
                           justify="left", wraplength=480)
        lbl.pack(fill="x", pady=(6, 0))
        return lbl

    # ================= pages =================
    def _page_brain(self):
        c = self.card()
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.pack(fill="x")
        for i, (value, title, model, tag, text) in enumerate(BRAINS):
            grid.columnconfigure(i, weight=1, uniform="b")
            card = self.select_card(grid, config.BRAIN == value, title, tag, f"{model}\n{text}",
                                    lambda v=value: (self.set(BRAIN=v), self.show("brain")))
            card.grid(row=0, column=i, sticky="nsew", padx=4)

        if config.BRAIN == "local":
            c = self.card("Free brain setup", "One time: install Ollama, download the model, done. "
                                              "Your 4070-class graphics card runs it.")
            self.ollama_status = self.status_line(c)
            steps = ctk.CTkFrame(c, fg_color="transparent")
            steps.pack(fill="x", pady=(8, 0))
            self.button(steps, "1. Download Ollama", lambda: webbrowser.open(
                "https://ollama.com/download")).pack(side="left")
            self.button(steps, "2. Copy the download command", self._copy_pull).pack(side="left", padx=8)
            self.button(steps, "Check again", self._check_ollama).pack(side="right")
            right = self.row(c, "Model", "Any Ollama vision model. qwen2.5vl:7b is a good fit for a 12 GB card.")
            e = self.entry(right, config.LOCAL_MODEL, "LOCAL_MODEL", "qwen2.5vl:7b",
                           on_saved=lambda _v: self._check_ollama())
            e.configure(width=200)
            e.pack()
            self._check_ollama()
        else:
            c = self.card("API key", "Get one at console.anthropic.com. Stored only on this PC.")
            row = ctk.CTkFrame(c, fg_color="transparent")
            row.pack(fill="x", pady=(6, 0))
            self.key_entry = self.entry(row, config.API_KEY, "API_KEY", "sk-ant-...", show="•")
            self.key_entry.pack(side="left", fill="x", expand=True)
            self.show_btn = self.button(row, "Show", self._toggle_key, width=64)
            self.show_btn.pack(side="left", padx=6)
            self.button(row, "Test key", self._test_key, primary=True, width=90).pack(side="left")
            self.key_status = self.status_line(c)
            link = ctk.CTkLabel(c, text="Open console.anthropic.com", font=ctk.CTkFont(
                family=T.FONT, size=12, underline=True), text_color=T.GLOW, cursor="hand2", anchor="w")
            link.pack(fill="x", pady=(4, 0))
            link.bind("<Button-1>", lambda e: webbrowser.open("https://console.anthropic.com/settings/keys"))

            c = self.card("Thinking")
            right = self.row(c, "How hard she thinks", "Low is fastest. Try Medium if steps go wrong.")
            self.seg(right, ["Low", "Medium", "High"], config.EFFORT.title(),
                     lambda v: self.set(EFFORT=v.lower()), width=230)
            if config.BRAIN == "claude":
                self.switch(c, "Fast mode", "Up to 2.5x quicker replies, but costs twice as much.",
                            "FAST_MODE")

    def _toggle_key(self):
        hidden = self.key_entry.cget("show") == "•"
        self.key_entry.configure(show="" if hidden else "•")
        self.show_btn.configure(text="Hide" if hidden else "Show")

    def _test_key(self):
        key = self.key_entry.get().strip()
        if key != config.API_KEY:
            self.set(API_KEY=key)
        if not key:
            self.key_status.configure(text="Paste your key first.", text_color=T.GOLD)
            return
        self.key_status.configure(text="Checking...", text_color=T.MUTED)

        def work():
            import anthropic
            try:
                anthropic.Anthropic(api_key=key, timeout=10.0, max_retries=0).models.retrieve(config.MODEL)
                msg, colour = "✓ Key works. Eris is ready to think.", "#4fd18b"
            except anthropic.AuthenticationError:
                msg, colour = "That key was rejected. Copy it again from the console.", T.ERROR
            except anthropic.PermissionDeniedError:
                msg, colour = "The key works but can't use this model. Check your console.", T.GOLD
            except anthropic.APIConnectionError:
                msg, colour = "Couldn't reach Anthropic. Check your internet.", T.ERROR
            except Exception as e:
                msg, colour = f"Something went wrong: {e}", T.ERROR
            self._ui(lambda: self.key_status.configure(text=msg, text_color=colour))
        threading.Thread(target=work, daemon=True).start()

    def _copy_pull(self):
        self.clipboard_clear()
        self.clipboard_append(f"ollama pull {config.LOCAL_MODEL}")
        self.toast("✓ Copied. Paste it into Command Prompt.")

    def _check_ollama(self):
        self.ollama_status.configure(text="Checking Ollama...", text_color=T.MUTED)
        want = config.LOCAL_MODEL

        def work():
            models = local_models()
            if models is None:
                msg, colour = "✗ Ollama isn't running. Install it (step 1) and open it.", T.ERROR
            elif not any(m == want or m.split(":")[0] == want for m in models):
                msg, colour = (f"✓ Ollama is running   ✗ {want} isn't downloaded yet (step 2).", T.GOLD)
            else:
                msg, colour = f"✓ Ollama is running   ✓ {want} is ready. Eris thinks for free.", "#4fd18b"
            self._ui(lambda: self.ollama_status.configure(text=msg, text_color=colour))
        threading.Thread(target=work, daemon=True).start()

    def _page_voice(self):
        c = self.card()
        self.switch(c, "Talks out loud", "Turn off to only see her replies in the chat.", "VOICE_ON")
        self.switch(c, "Quick \"on it\" reply", "A tiny instant reply so you know she heard you.", "ACK")
        right = self.row(c, "Voice type", "Natural sounds human (free, needs internet). Windows works offline.")
        self.seg(right, ["Natural", "Windows"], "Natural" if config.VOICE_ENGINE == "natural" else "Windows",
                 lambda v: (self.set(VOICE_ENGINE=v.lower()), self.show("voice")), width=200)

        if config.VOICE_ENGINE == "natural":
            c = self.card("Who she sounds like", "Click a voice to choose it, Play to hear it.")
            grid = ctk.CTkFrame(c, fg_color="transparent")
            grid.pack(fill="x", pady=(6, 0))
            for i, (label, name) in enumerate(VOICES.items()):
                who, feel = VOICE_INFO[label]
                chosen = config.VOICE_NAME == name
                cell = ctk.CTkFrame(grid, fg_color=T.CARD_2 if chosen else T.CARD, corner_radius=12,
                                    border_width=2, border_color=T.ACCENT if chosen else T.BORDER)
                cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)
                grid.columnconfigure(i % 2, weight=1, uniform="v")
                txt = ctk.CTkFrame(cell, fg_color="transparent")
                txt.pack(side="left", padx=12, pady=8, fill="x", expand=True)
                ctk.CTkLabel(txt, text=who, font=font(14, "bold"), text_color=T.TEXT, anchor="w").pack(fill="x")
                ctk.CTkLabel(txt, text=feel, font=font(12), text_color=T.MUTED, anchor="w").pack(fill="x")
                ctk.CTkButton(cell, text="Play", width=58, height=30, corner_radius=10, font=font(12, "bold"),
                              fg_color=T.ACCENT if chosen else T.BORDER, hover_color=T.ACCENT_HOVER,
                              command=lambda n=name: self._preview(n)).pack(side="right", padx=10)
                pick = lambda _e, n=name: (self.set(VOICE_NAME=n), self.show("voice"))
                for w in (cell, txt) + tuple(txt.winfo_children()):
                    w.bind("<Button-1>", pick)
                    _hand(w)

        c = self.card()
        right = self.row(c, "Talking speed")
        speed_lbl = ctk.CTkLabel(right, text="", font=font(12), text_color=T.MUTED, width=70)
        sl = ctk.CTkSlider(right, from_=-5, to=10, number_of_steps=15, width=220,
                           button_color=T.ACCENT, button_hover_color=T.GLOW,
                           progress_color=T.ACCENT, fg_color=T.BORDER)
        def speed_text(v):
            v = int(round(float(v)))
            speed_lbl.configure(text="normal" if v == 0 else (f"+{v * 6}%" if v > 0 else f"{v * 6}%"))
        sl.configure(command=lambda v: (speed_text(v), self._later(
            "rate", 400, lambda: self.set(VOICE_RATE=int(round(sl.get()))))))
        sl.set(config.VOICE_RATE)
        speed_text(config.VOICE_RATE)
        sl.pack(side="left")
        speed_lbl.pack(side="left", padx=(8, 0))
        right = self.row(c, "Hearing you", "Tiny is fastest, Small understands you best.")
        self.seg(right, ["Tiny", "Base", "Small"], config.WHISPER_MODEL.split(".")[0].title(),
                 lambda v: self.set(WHISPER_MODEL=f"{v.lower()}.en"), width=230)

    def _preview(self, name):
        self.app.eris.voice.stop()
        self.app.eris.voice.say(PREVIEW, force=True, voice=name)

    def _page_guiding(self):
        c = self.card("Box style")
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.pack(fill="x", pady=(6, 0))
        for i, (value, title, text) in enumerate([
                ("glow", "Glow", "Rounded, glowing, with a gentle pulse."),
                ("bars", "Simple", "Plain sharp box. Use it if Glow misbehaves.")]):
            grid.columnconfigure(i, weight=1, uniform="s")
            img = ctk.CTkImage(light_image=_style_preview(value), dark_image=_style_preview(value),
                               size=(220, 74))
            self.select_card(grid, config.BOX_STYLE == value, title, None, text,
                             lambda v=value: (self.set(BOX_STYLE=v), self.toast("✓ Saved: takes effect next time Eris opens"),
                                              self.show("guiding")), image=img
                             ).grid(row=0, column=i, sticky="nsew", padx=4)
        self.button(c, "Test the box", self._test_box, primary=True).pack(anchor="w", pady=(12, 0))

        c = self.card("Pointing")
        self.switch(c, "Extra-precise boxes", "She zooms in and snaps the box exactly onto the thing to click.",
                    "REFINE")
        self.switch(c, "Watch what I do", "She notices when your screen changes and carries on from there.",
                    "WATCH")
        right = self.row(c, "Box hides itself after")
        lbl = ctk.CTkLabel(right, text="", font=font(12), text_color=T.MUTED, width=40)
        sl = ctk.CTkSlider(right, from_=5, to=60, number_of_steps=11, width=200, button_color=T.ACCENT,
                           button_hover_color=T.GLOW, progress_color=T.ACCENT, fg_color=T.BORDER)
        sl.configure(command=lambda v: (lbl.configure(text=f"{int(float(v))}s"),
                                        self._later("timeout", 400, lambda: self.set(BOX_TIMEOUT=int(round(sl.get()))))))
        sl.set(config.BOX_TIMEOUT)
        lbl.configure(text=f"{config.BOX_TIMEOUT}s")
        sl.pack(side="left")
        lbl.pack(side="left", padx=(8, 0))

    def _test_box(self):
        x, y = self.winfo_rootx(), self.winfo_rooty()
        ov = self.app.overlay
        ov.monitor(0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        ov.box(x + 10, y + 10, x + self.winfo_width() - 10, y + self.winfo_height() - 10, "This is the box")
        self.after(3000, ov.clear_box)

    def _page_privacy(self):
        c = self.card()
        self.switch(c, "Look away from private things",
                    "No screenshots while you type in a password, email, card or code box, and "
                    "those boxes are blacked out everywhere else.", "PRIVACY")
        c = self.card("Never look at these apps",
                      "If the window in front has one of these in its title, Eris doesn't look at all.")
        self.apps_list = ctk.CTkFrame(c, fg_color="transparent")
        self.apps_list.pack(fill="x", pady=(6, 0))
        self._fill_apps()
        add = ctk.CTkFrame(c, fg_color="transparent")
        add.pack(fill="x", pady=(10, 0))
        new = ctk.CTkEntry(add, height=34, fg_color=T.CARD_2, border_color=T.BORDER,
                           placeholder_text="App name, e.g. My Bank")
        new.pack(side="left", fill="x", expand=True)
        def add_app(name=None):
            name = (name or new.get()).strip()
            if name and name.lower() not in (a.lower() for a in config.PRIVATE_APPS):
                self.set(PRIVATE_APPS=config.PRIVATE_APPS + [name])
                self._fill_apps()
            new.delete(0, "end")
        new.bind("<Return>", lambda e: add_app())
        self.button(add, "Add", add_app, primary=True, width=64).pack(side="left", padx=6)
        self.button(add, "Add the app in front...", lambda: self._grab_front_app(add_app)).pack(side="left")
        self.front_status = self.status_line(c)

        c = self.card("Good to know")
        self.muted(c, "• She only ever hears her own hotkeys and Enter. Everything else you type is "
                      "dropped instantly.\n• The Free brain keeps everything on your PC. With Claude, "
                      "screenshots go to Anthropic to be understood.\n• Apps that draw their own "
                      "password boxes can't be detected. Add them above, or turn Eris off with the "
                      "Active switch.", wrap=520)

    def _fill_apps(self):
        for w in self.apps_list.winfo_children():
            w.destroy()
        if not config.PRIVATE_APPS:
            self.muted(self.apps_list, "No apps yet.")
        for name in config.PRIVATE_APPS:
            r = ctk.CTkFrame(self.apps_list, fg_color=T.CARD_2, corner_radius=10)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=name, font=font(13), text_color=T.TEXT).pack(side="left", padx=12, pady=5)
            ctk.CTkButton(r, text="Remove", width=70, height=26, corner_radius=10, font=font(12),
                          fg_color="transparent", hover_color=T.ACCENT_DIM, text_color=T.MUTED,
                          command=lambda n=name: (self.set(PRIVATE_APPS=[a for a in config.PRIVATE_APPS if a != n]),
                                                  self._fill_apps())).pack(side="right", padx=6)

    def _grab_front_app(self, add_app):
        """Count down so you can click the app you want blocked, then read its title."""
        from .privacy import foreground_title

        def tick(n):
            if not self.winfo_exists():
                return
            if n > 0:
                self.front_status.configure(text=f"Click the app you want to block... {n}", text_color=T.GOLD)
                self.after(1000, lambda: tick(n - 1))
                return
            title = foreground_title()
            name = title.split(" - ")[-1].strip() if " - " in title else title.strip()
            if not name or name.startswith("Eris"):
                self.front_status.configure(text="Didn't catch another app. Try again.", text_color=T.ERROR)
                return
            add_app(name)
            self.front_status.configure(text=f"✓ Added \"{name}\".", text_color="#4fd18b")
        tick(3)

    def _page_eris(self):
        c = self.card()
        top = ctk.CTkFrame(c, fg_color="transparent")
        top.pack(fill="x")
        pic = _avatar_image(84)
        ctk.CTkLabel(top, text="", image=ctk.CTkImage(light_image=pic, dark_image=pic, size=(84, 84))
                     ).pack(side="left")
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", padx=16, fill="x", expand=True)
        ctk.CTkLabel(info, text="Eris", font=font(20, "bold"), text_color=T.TEXT, anchor="w").pack(fill="x")
        self.muted(info, "Ask her to pick herself a profile picture and it shows up here.", wrap=330)
        if settings.AVATAR.exists():
            self.button(info, "Remove picture", self._remove_avatar).pack(anchor="w", pady=(6, 0))

        c = self.card("Personality")
        right = self.row(c, "Vibe", "How playful she is. The instructions always come first.")
        self.seg(right, ["Calm", "Friendly", "Cheeky"], config.VIBE.title(),
                 lambda v: self.set(VIBE=v.lower()), width=260)
        right = self.row(c, "What should she call you?", "Leave empty and she won't use a name.")
        e = self.entry(right, config.USER_NAME, "USER_NAME", "Your name")
        e.configure(width=200)
        e.pack()

        mems = settings.memories()
        c = self.card("What she remembers", "Things she decided about herself or learned about you. "
                                            "Remove anything you don't want her to keep.")
        if not mems:
            self.muted(c, "Nothing yet.")
        for m in mems:
            r = ctk.CTkFrame(c, fg_color=T.CARD_2, corner_radius=10)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=m, font=font(13), text_color=T.TEXT, anchor="w", justify="left",
                         wraplength=400).pack(side="left", padx=12, pady=6, fill="x", expand=True)
            ctk.CTkButton(r, text="Remove", width=70, height=26, corner_radius=10, font=font(12),
                          fg_color="transparent", hover_color=T.ACCENT_DIM, text_color=T.MUTED,
                          command=lambda f=m: (settings.forget(f), self.toast("✓ Forgotten"),
                                               self.show("eris"))).pack(side="right", padx=6)
        if mems:
            self.button(c, "Forget everything", self._forget_all).pack(anchor="w", pady=(10, 0))

    def _remove_avatar(self):
        try:
            settings.AVATAR.unlink()
        except OSError:
            pass
        self.app.avatar.load()
        self.toast("✓ Picture removed")
        self.show("eris")

    def _forget_all(self):
        settings.forget_all()
        self.app.eris.brain.reset()
        self.app.avatar.load()
        self.toast("✓ She forgot everything")
        self.show("eris")

    def _page_keys(self):
        c = self.card()
        self.key_buttons = {}
        for key, title, help in (("TALK_KEY", "Hold to talk", "Hold it while you speak, let go when done."),
                                 ("NEXT_KEY", "Next step", "For steps she can't see you finish."),
                                 ("CANCEL_KEY", "Stop", "Clears the box and stops her talking.")):
            right = self.row(c, title, help)
            b = ctk.CTkButton(right, text=key_label(getattr(config, key)), width=150, height=38,
                              corner_radius=12, font=font(15, "bold"), fg_color=T.CARD_2,
                              hover_color=T.BORDER, border_width=2, border_color=T.BORDER,
                              command=lambda k=key: self._start_capture(k))
            b.pack()
            self.key_buttons[key] = b
        self.keys_status = self.status_line(c)
        self.muted(c, "Use F1 to F20, Insert, Home, End, Page Up/Down, Pause or Scroll Lock. These don't "
                      "type anything, so they won't get in your way.")

    def _start_capture(self, key):
        self._stop_capture()
        self._capturing = key
        self.app.eris.hotkeys_paused = True
        self.key_buttons[key].configure(text="Press a key...", border_color=T.ACCENT)
        self.keys_status.configure(text="Press the key you want (Esc to cancel).", text_color=T.MUTED)
        self.focus_force()
        self.bind("<KeyPress>", self._captured)

    def _captured(self, event):
        key = self._capturing
        if not key:
            return
        if event.keysym == "Escape":
            self._stop_capture()
            return
        name = KEY_NAMES.get(event.keysym)
        if not name:
            self.keys_status.configure(text=f"\"{event.keysym}\" types something. Pick an F-key or "
                                            "one of the keys below.", text_color=T.GOLD)
            return
        others = {k: getattr(config, k) for k in self.key_buttons if k != key}
        if name in others.values():
            clash = next(k for k, v in others.items() if v == name)
            self.set(**{key: name, clash: getattr(config, key)})   # swap them
            self.keys_status.configure(text="Swapped those two keys.", text_color=T.MUTED)
        else:
            self.set(**{key: name})
            self.keys_status.configure(text="", text_color=T.MUTED)
        self._stop_capture()

    def _stop_capture(self):
        was = self._capturing
        if was:
            try:
                self.unbind("<KeyPress>")
            except Exception:
                pass
        self._capturing = None
        if was and hasattr(self.app, "eris"):
            # a moment later (so the key you just pressed doesn't trigger her), unless
            # you've started choosing another key in the meantime
            self.app.after(300, lambda: self._capturing is None and
                           setattr(self.app.eris, "hotkeys_paused", False))
        for k, b in getattr(self, "key_buttons", {}).items():
            if b.winfo_exists():
                b.configure(text=key_label(getattr(config, k)), border_color=T.BORDER)

    def _page_app(self):
        c = self.card("Updates")
        right = self.row(c, f"Version {updater.local_version()}", "Updates only install when you click "
                                                                   "Update, and are safety-checked first.")
        self.button(right, "Check now", self._check_updates).pack()
        self.update_status = self.status_line(c)
        right = self.row(c, "Check when Eris opens", "Turn off to only check when you click Check now.")
        sw = ctk.CTkSwitch(right, text="", width=46, progress_color=T.ACCENT, fg_color=T.BORDER,
                           button_color=T.TEXT, button_hover_color="#ffffff",
                           command=lambda: self.set(UPDATES="ask" if sw.get() else "off"))
        sw.select() if config.UPDATES != "off" else sw.deselect()
        sw.pack()

        c = self.card("Window")
        self.switch(c, "Keep Eris on top", "Her window stays above your other windows.", "PANEL_ON_TOP")
        right = self.row(c, "Logs", "If something goes wrong, send Claude the eris.log file from here.")
        self.button(right, "Open log folder", lambda: webbrowser.open(settings.folder().as_uri())).pack()

        c = self.card("Start over")
        right = self.row(c, "Reset all settings", "Back to how Eris came. Your API key and her memories stay.")
        self.reset_btn = self.button(right, "Reset", self._reset)
        self.reset_btn.pack()

    def _check_updates(self):
        self.update_status.configure(text="Checking...", text_color=T.MUTED)

        def work():
            v = updater.remote_version(manual=True)
            if v:
                self.app.cmd("update_available", v)
                msg, colour = f"v{v} is ready. Click the green Update button in Eris's window.", "#4fd18b"
            else:
                msg, colour = "You're on the latest version.", T.MUTED
            self._ui(lambda: self.update_status.configure(text=msg, text_color=colour))
        threading.Thread(target=work, daemon=True).start()

    def _reset(self):
        if not self._reset_armed:
            self._reset_armed = True
            self.reset_btn.configure(text="Click again to reset", fg_color=T.ACCENT)
            self._later("reset", 3000, lambda: (setattr(self, "_reset_armed", False),
                                                self.reset_btn.winfo_exists() and
                                                self.reset_btn.configure(text="Reset", fg_color=T.CARD_2)))
            return
        settings.reset_all(keep_key=True)
        self.app.on_settings_changed(settings.SAVED)
        self.toast("✓ Reset")
        self.show("app")


def _hand(widget):
    """Pointing-hand cursor, where the widget supports it."""
    try:
        widget.configure(cursor="hand2")
    except Exception:
        pass


def _avatar_image(size):
    """Her picture as a circle (or a crimson orb with an E if she hasn't picked one)."""
    from PIL import ImageFont
    big = size * 3
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((6, 6, big - 6, big - 6), fill=255)
    if settings.AVATAR.exists():
        try:
            face = Image.open(settings.AVATAR).convert("RGB").resize((big, big))
            img.paste(face, (0, 0), mask)
        except Exception:
            pass
    else:
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, big - 6, big - 6), fill=(22, 9, 12, 255))
        try:
            f = ImageFont.truetype("segoeuib.ttf", big // 2)
        except OSError:
            try:
                f = ImageFont.truetype("DejaVuSans-Bold.ttf", big // 2)
            except OSError:
                f = ImageFont.load_default()
        d.text((big / 2, big / 2), "E", fill=(246, 236, 238, 255), font=f, anchor="mm")
    ImageDraw.Draw(img).ellipse((6, 6, big - 6, big - 6), outline=(227, 38, 63, 255), width=big // 22)
    return img.resize((size, size), Image.LANCZOS)


def _style_preview(style):
    """Little picture of each box style around a fake button."""
    from PIL import ImageFont
    W, H = 440, 148
    img = Image.new("RGB", (W, H), "#211518")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("segoeui.ttf", 26)
    except OSError:
        try:
            f = ImageFont.truetype("DejaVuSans.ttf", 26)
        except OSError:
            f = ImageFont.load_default()
    bx1, by1, bx2, by2 = 110, 46, 330, 102
    d.rounded_rectangle((bx1, by1, bx2, by2), 8, fill="#3a3a3a")
    d.text(((bx1 + bx2) / 2, (by1 + by2) / 2), "Add Component", fill="#e0e0e0", font=f, anchor="mm")
    if style == "glow":
        from .glowbox import render, GLOW
        g = render(bx2 - bx1 + 16, by2 - by1 + 16, "")
        img.paste(g, (bx1 - 8 - GLOW, by1 - 8 - GLOW), g)
    else:
        red = config.BOX_COLOR
        t = 6
        d.rectangle((bx1 - 8 - t, by1 - 8 - t, bx2 + 8 + t, by1 - 8), fill=red)
        d.rectangle((bx1 - 8 - t, by2 + 8, bx2 + 8 + t, by2 + 8 + t), fill=red)
        d.rectangle((bx1 - 8 - t, by1 - 8, bx1 - 8, by2 + 8), fill=red)
        d.rectangle((bx2 + 8, by1 - 8, bx2 + 8 + t, by2 + 8), fill=red)
    return img
