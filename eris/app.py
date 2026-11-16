"""The Eris window: chat bubbles, talk button, settings. Neon red on black."""
import gc
import os
import queue
import sys
import threading
import time
import tkinter as tk

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
from .theme import font, tint_titlebar
from .core import Eris
from .overlay import Overlay

OVERLAY_CMDS = {"box", "move_box", "type_hint", "clear_box", "status", "monitor", "drop",
                "scroll_hint", "badge"}
SUGGESTIONS = ["How do I add a Rigidbody in Unity?", "Take me to Wikipedia",
               "Pick yourself a profile picture"]


class Avatar(tk.Canvas):
    """Glowing red orb with an E. Pulses while listening/thinking."""

    def __init__(self, master, size=54):
        super().__init__(master, width=size, height=size, bg=T.BG, highlightthickness=0)
        self.size, self.phase, self.pulsing = size, 0, False
        self.photo = None
        self.load()
        self._tick()

    def load(self):
        """Use the picture Eris chose for herself, cut into a circle."""
        self.photo = None
        try:
            if settings.AVATAR.exists():
                from PIL import Image, ImageDraw, ImageTk
                d = self.size - 22
                img = Image.open(settings.AVATAR).convert("RGB").resize((d * 3, d * 3))
                mask = Image.new("L", img.size, 0)
                ImageDraw.Draw(mask).ellipse((0, 0, img.width - 1, img.height - 1), fill=255)
                bg = Image.new("RGB", img.size, "#16090c")
                bg.paste(img, (0, 0), mask)
                self.photo = ImageTk.PhotoImage(bg.resize((d, d), Image.LANCZOS))
        except Exception:
            self.photo = None
        self._draw(0)

    def _draw(self, glow):
        self.delete("all")
        s = self.size
        for i, c in enumerate(["#2a0c12", "#3d0f18", "#5a1320"]):
            pad = 1 + i * 3 - (1 if glow and i == 0 else 0)
            self.create_oval(pad, pad, s - pad, s - pad, fill=c, outline="")
        self.create_oval(10, 10, s - 10, s - 10, fill="#16090c",
                         outline=T.GLOW if glow else T.ACCENT, width=3)
        if self.photo:
            self.create_image(s / 2, s / 2, image=self.photo)
            self.create_oval(10, 10, s - 10, s - 10, outline=T.GLOW if glow else T.ACCENT, width=3)
        else:
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
        self._rects = []
        self._ticks = 0

        self.overlay = Overlay(self)
        self._build()
        self.eris = Eris(self)
        self._set_state("loading")

        keyboard.Listener(on_press=self.eris.on_press, on_release=self.eris.on_release).start()
        mouse.Listener(on_click=self.eris.on_click).start()
        self.after(30, self._pump)
        # Python's cycle cleanup can run on any thread; if it frees an old Tk font or image
        # from a background thread, Tk crashes. So clean up only here, on the window's thread.
        gc.disable()
        self.after(3000, self._collect)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        threading.Thread(target=self.check_updates, daemon=True).start()
        if config.BRAIN == "local":   # load the local model into the graphics card now
            threading.Thread(target=self.load_local_brain, daemon=True).start()
        if config.BRAIN != "local" and not settings.api_key():
            self.after(700, self.open_settings)

    def _collect(self):
        gc.collect()
        self.after(3000, self._collect)

    # ---------- thread-safe API used by Eris ----------
    def cmd(self, name, *args):
        self.q.put((name, args))

    def log(self, who, text):
        self.q.put(("log", (who, text)))

    def box_in_screenshots(self):
        """True if screenshots can see the red box and its type hint (older Windows, or
        you chose to show the box in recordings)."""
        return not getattr(getattr(self, "overlay", None), "hidden_from_capture", False)

    def window_rects(self):
        """Screen rects of Eris's own windows (the watcher ignores them)."""
        return self._rects

    def _cache_rects(self):
        rects = []
        for w in (self, getattr(self, "_settings", None)):
            try:
                if w is not None and w.winfo_exists() and w.state() == "normal":
                    x, y = w.winfo_rootx(), w.winfo_rooty()
                    rects.append((x - 40, y - 50, x + w.winfo_width() + 20, y + w.winfo_height() + 20))
            except Exception:
                pass
        self._rects = rects

    def _pump(self):
        """Carry out everything Eris asked the window to do. One bad message must never
        stop the loop (that would freeze the window), so each is handled on its own."""
        self._ticks += 1
        if self._ticks % 15 == 0:   # about twice a second is plenty
            self._cache_rects()
        for _ in range(200):
            try:
                name, args = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle(name, args)
            except Exception as e:
                self._write_log("error", f"window couldn't do {name}{args}: {e}")
        self.after(30, self._pump)

    def _handle(self, name, args):
        if name in OVERLAY_CMDS:
            getattr(self.overlay, name)(*args)
            if name in ("box", "clear_box"):
                self.wrong_btn.configure(state="normal" if name == "box" else "disabled")
        elif name == "log":
            self._append(*args)
        elif name == "state":
            self._set_state(*args)
        elif name == "update_available":
            self.update_version = args[0]
            self.update_btn.configure(text=f"Update to v{args[0]}")
            self.update_btn.pack(side="right", padx=(0, 8))
        elif name == "restart":
            updater.restart()
            self._quit()
        elif name == "update_failed":
            self.update_btn.configure(state="normal", text="Retry update")
        elif name == "avatar":
            self.avatar.load()
        elif name == "clear_chat":
            self._clear_chat()
        elif name == "call":
            self._set_call(args[0])
        elif name == "active":
            self.active_switch.select() if args[0] else self.active_switch.deselect()
        elif name == "run":
            args[0]()                     # a background job's UI update (e.g. Settings)

    # ---------- layout ----------
    def _build(self):
        # header: avatar, name, status chip
        from .glitch import Banner
        self.banner = Banner(self).pack(fill="x")    # streaks of red light drifting across the top
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 8))
        self.avatar = Avatar(top)
        self.avatar.pack(side="left")
        names = ctk.CTkFrame(top, fg_color="transparent")   # packed after the right side, below
        ctk.CTkLabel(names, text="Eris", font=font(24, "bold"), text_color=T.TEXT,
                     height=26).pack(anchor="w")
        self.subtitle = ctk.CTkLabel(names, text="", font=font(12), text_color=T.MUTED, height=16)
        self.subtitle.pack(anchor="w")
        ctk.CTkButton(top, text="Settings", width=78, height=32, corner_radius=T.r(12), font=font(12),
                      fg_color=T.CARD_2, hover_color=T.BORDER, text_color=T.TEXT,
                      command=self.open_settings).pack(side="right")
        self.chip = ctk.CTkFrame(top, fg_color=T.CARD_2, corner_radius=T.r(14), height=28)
        self.chip.pack(side="right", padx=8)
        self.chip_dot = ctk.CTkFrame(self.chip, width=9, height=9, corner_radius=T.r(4),
                                     fg_color=T.MUTED)
        self.chip_dot.pack(side="left", padx=(11, 6))
        self.chip_text = ctk.CTkLabel(self.chip, text="", font=font(12, "bold"),
                                      text_color=T.TEXT)
        self.chip_text.pack(side="left", padx=(0, 12))
        names.pack(side="left", padx=12)   # last: when the window is narrow, the subtitle gives way, not the status
        self.update_btn = ctk.CTkButton(top, text="Update", width=110, height=30, corner_radius=T.r(15),
                                        fg_color="#1f6b45", hover_color="#185437",
                                        font=font(12, "bold"), command=self.do_update)

        # thin red line
        ctk.CTkFrame(self, fg_color=T.ACCENT, height=2, corner_radius=T.r(1)).pack(fill="x", padx=18)

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
        self.chat = ctk.CTkScrollableFrame(self, fg_color=T.CARD, corner_radius=T.r(18),
                                           scrollbar_button_color=T.BORDER,
                                           scrollbar_button_hover_color=T.ACCENT_DIM)
        self.chat.pack(fill="both", expand=True, padx=18, pady=12)
        self.chat.bind("<Configure>", self._rewrap)
        self._welcome()

        # status line (filled by _note)
        self.note_row = ctk.CTkFrame(self, fg_color="transparent")
        self.note_dot = ctk.CTkFrame(self.note_row, width=7, height=7, corner_radius=T.r(3),
                                     fg_color=T.MUTED)
        self.note_dot.pack(side="left", padx=(2, 8))
        self.note_label = ctk.CTkLabel(self.note_row, text="", font=font(12), text_color=T.MUTED,
                                       anchor="w")
        self.note_label.pack(side="left", fill="x", expand=True)

        # step controls
        ctl = self.ctl_row = ctk.CTkFrame(self, fg_color="transparent")
        ctl.pack(fill="x", padx=15)
        for text, fn in (("Next step", lambda: self.eris.advance()),
                         ("Wrong box", lambda: self.eris.wrong_box()),
                         ("Stop", lambda: self.eris.cancel()),
                         ("New task", lambda: self.eris.new_task())):
            b = ctk.CTkButton(ctl, text=text, width=40, height=34, corner_radius=T.r(17), font=font(13),
                              fg_color="transparent", border_width=1, border_color=T.BORDER,
                              hover_color=T.CARD_2, text_color=T.TEXT, text_color_disabled=T.MUTED,
                              command=fn)
            b.pack(side="left", expand=True, fill="x", padx=3)
            if text == "Wrong box":
                self.wrong_btn = b
                b.configure(state="disabled")   # only while a box is showing

        # type box
        typ = ctk.CTkFrame(self, fg_color=T.CARD_2, corner_radius=T.r(22))
        typ.pack(fill="x", padx=18, pady=(12, 8))
        self.entry = ctk.CTkEntry(typ, height=40, placeholder_text="Type a question...",
                                  fg_color=T.CARD_2, border_width=0, font=font(14),
                                  text_color=T.TEXT, placeholder_text_color=T.MUTED)
        self.entry.pack(side="left", fill="x", expand=True, padx=(14, 4), pady=2)
        self.entry.bind("<Return>", lambda e: self._send())
        ctk.CTkButton(typ, text="Ask", width=56, height=36, corner_radius=T.r(14), font=font(13, "bold"),
                      fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                      command=self._send).pack(side="right", padx=4, pady=3)

        # big talk button
        # Start with real text: CustomTkinter only creates the text label once there's text,
        # and clicks on the words land on that label, so it must exist before we bind.
        self.mic = ctk.CTkButton(self, text="Click to call", height=52, corner_radius=T.r(26),
                                 fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                                 font=font(15, "bold"), text_color="#ffffff")
        self.mic.pack(fill="x", padx=18, pady=(0, 18))
        self._bind_mic()
        self.on_call = False

    def _welcome(self):
        """Greeting + a few ideas. Tucks itself away once you start talking."""
        self.welcome = box = ctk.CTkFrame(self.chat, fg_color="transparent")
        box.pack(fill="x", padx=10, pady=(16, 8))
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x")
        try:
            from .settings_ui import _avatar_image
            pic = _avatar_image(46)
            ctk.CTkLabel(head, text="", image=ctk.CTkImage(light_image=pic, dark_image=pic,
                                                           size=(46, 46))).pack(side="left")
        except Exception:
            pass
        words = ctk.CTkFrame(head, fg_color="transparent")
        words.pack(side="left", padx=12, fill="x", expand=True)
        name = config.USER_NAME.strip()
        ctk.CTkLabel(words, text=f"Hi {name}, I'm Eris" if name else "Hi, I'm Eris",
                     font=font(19, "bold"), text_color=T.TEXT, anchor="w").pack(fill="x")
        self.welcome_label = ctk.CTkLabel(
            words, text="Ask me how to do anything. I'll point at it on your screen, one step "
                        "at a time.", font=font(13), text_color=T.MUTED, wraplength=300,
            justify="left", anchor="w")
        self.welcome_label.pack(fill="x")
        ctk.CTkLabel(box, text="TRY ASKING", font=font(10, "bold"), text_color=T.ACCENT,
                     anchor="w").pack(fill="x", pady=(16, 4))
        for text in SUGGESTIONS:
            self._suggestion(box, text)

    def _suggestion(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color=T.CARD_2, corner_radius=T.r(12), height=38)
        row.pack(fill="x", pady=3)
        lbl = ctk.CTkLabel(row, text=text, font=font(13), text_color=T.TEXT, anchor="w")
        lbl.pack(side="left", padx=14, pady=8, fill="x", expand=True)
        arrow = ctk.CTkLabel(row, text="›", font=font(18, "bold"), text_color=T.MUTED, width=20)
        arrow.pack(side="right", padx=10)

        def hover(on):
            row.configure(fg_color=T.ACCENT_DIM if on else T.CARD_2)
            arrow.configure(text_color=T.TEXT if on else T.MUTED)
        for w in (row, lbl, arrow):
            w.bind("<Button-1>", lambda _e: self.eris.ask(text))
            w.bind("<Enter>", lambda _e: hover(True))
            w.bind("<Leave>", lambda _e: hover(False))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

    def _clear_chat(self):
        """New task: empty the chat and show the welcome again."""
        for w in self.chat.winfo_children():
            w.destroy()
        self.bubbles, self.last_eris = [], None
        self._welcome()
        self._scroll_end()
        self._note("Fresh start. What are we doing?", hold=4)

    # ---------- status line (system messages live here, not in the chat) ----------
    def _note(self, text, hold=None):
        """Show a short system message under the chat. hold: seconds before it fades
        (None = stays until replaced, for things still in progress)."""
        if getattr(self, "_note_job", None):
            self.after_cancel(self._note_job)
            self._note_job = None
        self.note_label.configure(text=text)
        self.note_dot.configure(fg_color=T.GOLD if hold is None and text else T.MUTED)
        if text:
            self.note_row.pack(fill="x", padx=22, pady=(0, 6), before=self.ctl_row)
        if hold:
            self._note_job = self.after(int(hold * 1000), lambda: self._note(""))
        elif not text:
            self.note_row.pack_forget()

    # ---------- chat bubbles ----------
    def _wrap(self):
        return max(200, int(self.chat.winfo_width() * 0.74))

    def _rewrap(self, _e=None):
        w = self._wrap()
        for b in self.bubbles:
            if b.winfo_exists():
                b.configure(wraplength=w)
        if getattr(self, "welcome", None) is not None and self.welcome.winfo_exists():
            self.welcome_label.configure(wraplength=max(200, w - 40))

    def _scroll_end(self):
        def go():
            self.chat.update_idletasks()
            c = self.chat._parent_canvas
            box = c.bbox("all")
            if box:   # keep the scrollable area in sync with the messages
                c.configure(scrollregion=(0, 0, box[2], max(box[3], c.winfo_height())))
            c.yview_moveto(1.0)
        self.after(20, go)
        self.after(150, go)   # again once the new bubble has its final size

    def _bubble(self, row, text, bg):
        return ctk.CTkLabel(row, text=text, fg_color=bg, corner_radius=T.r(16), text_color=T.TEXT,
                            font=font(14), wraplength=self._wrap(), justify="left",
                            padx=14, pady=9)

    def _write_log(self, who, text):
        try:
            if self.log_file.exists() and self.log_file.stat().st_size > 2_000_000:
                os.replace(self.log_file, self.log_file.with_suffix(".old.log"))   # cap the log
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} [{who}] {text}\n")
        except OSError:
            pass

    def _append(self, who, text):
        self._write_log(who, text)
        if who == "debug":
            return
        if who == "info":   # system message: status line, not the chat
            self._note(text, hold=None if text.rstrip().endswith("...") else 6)
            return
        if who == "you" and getattr(self, "welcome", None) is not None and self.welcome.winfo_exists():
            self.welcome.destroy()
            self.welcome = None
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

    # ---------- talk button: hold = push-to-talk, click = call on/off ----------
    CLICK = 0.25   # pressed for less than this = a click

    def _bind_mic(self):
        """Bind press/release on the button AND everything inside it (its text label,
        its canvas), so a click anywhere on it counts."""
        widgets = [self.mic] + list(self.mic.winfo_children())
        for w in widgets:
            if getattr(w, "_eris_bound", False):
                continue
            for seq, fn in (("<ButtonPress-1>", self._mic_down), ("<ButtonRelease-1>", self._mic_up)):
                w.bind(seq, fn, add="+")
            w._eris_bound = True

    @staticmethod
    def _stamp(e):
        """When the mouse event really happened (ms). Uses the event's own timestamp so a
        busy moment in the app can't make a quick click look like a long hold."""
        t = getattr(e, "time", None)
        return t if isinstance(t, int) and t > 0 else int(time.time() * 1000)

    def _mic_down(self, e=None):
        if getattr(self, "_pressed", False):   # the button and its label both report it
            return
        self._pressed = True
        self._down_ms = self._stamp(e)
        if not self.eris.ears:
            self._note("My ears are still loading. Give me a moment.", hold=4)
        self.eris.press()                       # starts the mic on a helper thread
        self._hold_job = self.after(int(self.CLICK * 1000), self.eris.confirm_hold)

    def _mic_up(self, e=None):
        if not getattr(self, "_pressed", False):
            return
        self._pressed = False
        if getattr(self, "_hold_job", None):
            self.after_cancel(self._hold_job)
            self._hold_job = None
        held = (self._stamp(e) - self._down_ms) / 1000
        if held < self.CLICK:
            self.eris.release_click()           # a click: call on/off
        else:
            self.eris.release_hold()            # a hold: push-to-talk

    def _set_call(self, on):
        self.on_call = on
        self._set_state("ready")
        if on:
            self._call_pulse()

    def _call_pulse(self, phase=0):
        """The button breathes gently while you're on a call with her."""
        if not self.on_call:
            return
        if self.chip_text.cget("text") != "Listening":
            self.mic.configure(fg_color=T.ACCENT if phase else "#b01e33")
        self.after(800, lambda: self._call_pulse(1 - phase))

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
        if state in ("listening", "guiding") and state != getattr(self, "_last_state", None):
            self.banner.burst()          # a glitch as she starts listening / talking
        self._last_state = state
        on_call = getattr(self, "on_call", False)
        if state == "listening":
            self.mic.configure(text="Listening..." if on_call else "Listening... let go when you're done",
                               fg_color=T.GLOW)
        elif on_call:
            self.mic.configure(text="On a call with Eris  ·  click to hang up", fg_color=T.ACCENT)
            if state == "ready":
                self.chip_text.configure(text="On call")
        else:
            self.mic.configure(text=f"Click to call  ·  hold to talk ({config.TALK_KEY.upper()})",
                               fg_color=T.ACCENT)
        self._bind_mic()   # in case the button made new inner widgets
        brain = {"claude": "Opus brain", "claude-cheap": "Haiku brain",
                 "local": "free local brain"}.get(config.BRAIN, "")
        self.subtitle.configure(text=brain)

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
        self.eris.stop_call()
        self.eris.cancel()
        self.destroy()

    # ---------- updates ----------
    def check_updates(self, manual=False):
        v = updater.remote_version(manual)
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
                if updater.install_update(self.log, expected=getattr(self, "update_version", None)):
                    self.log("info", "Updated! Restarting...")
                    self.cmd("restart")
                    return
            except Exception as e:
                self.log("error", f"Update failed: {e}")
            self.cmd("update_failed")
        threading.Thread(target=work, daemon=True).start()

    def load_local_brain(self):
        """Load the free brain onto the graphics card, then check it actually fits:
        if part of it spills onto the processor, every answer gets several times slower."""
        from .brain import gpu_fit
        self.log("info", f"Loading {config.LOCAL_MODEL} onto your graphics card...")
        self.eris.brain.prewarm()
        fit = gpu_fit()
        if fit is None:
            self.log("info", "Free brain: couldn't reach Ollama. Is it running?")
        elif fit < 0.97:
            self.log("hint", f"Only {fit:.0%} of my brain fits on your graphics card (something "
                             "else, like Unity, is using its memory), so I'll be slower. "
                             "Settings → Brain has fixes.")
        else:
            self.log("info", "Free brain ready, 100% on your graphics card.")

    # ---------- settings ----------
    def on_settings_changed(self, keys):
        """Apply a setting the moment it changes (the settings window saves instantly)."""
        keys = set(keys)
        if "BOX_IN_RECORDINGS" in keys:
            self.overlay.apply_capture()
        if "PANEL_ON_TOP" in keys:
            self.attributes("-topmost", bool(config.PANEL_ON_TOP))
        if keys & {"TALK_KEY", "NEXT_KEY", "CANCEL_KEY"}:
            self._update_hint()
            self._set_state("ready")
        if "BRAIN" in keys or ("LOCAL_MODEL" in keys and config.BRAIN == "local"):
            self._set_state("ready")
            if config.BRAIN == "local":
                self.eris.brain.last_call = 0      # a new model: load it now
                threading.Thread(target=self.load_local_brain, daemon=True).start()
        if "WHISPER_MODEL" in keys:
            self.eris.load_ears()
        if keys & {"VOICE_NAME", "VOICE_ENGINE"}:
            threading.Thread(target=self.eris.voice.prepare_acks, daemon=True).start()
        if "VOICE_ON" in keys and not config.VOICE_ON:
            self.eris.voice.stop()

    def open_settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.focus()
            return
        from .settings_ui import SettingsWindow
        self._settings = SettingsWindow(self)


def _single_instance():
    """Only one Eris at a time (two would both answer F8 and talk over each other).
    Returns False if another copy is already running."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)   # reliable GetLastError
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    after_update = "--after-update" in sys.argv
    for _ in range(40 if after_update else 1):   # after an update, wait for the old copy to close
        handle = k32.CreateMutexW(None, False, "Local\\ErisScreenGuide")
        if ctypes.get_last_error() != 183:       # 183 = already exists
            globals()["_mutex"] = handle          # keep it alive for the whole run
            return True
        k32.CloseHandle(handle)
        time.sleep(0.25)
    return False


def main():
    if not _single_instance():
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "Eris is already running. Look for her window "
                                             "or her icon in the taskbar.", "Eris", 0x40)
        return
    App().mainloop()
