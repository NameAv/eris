"""Eris's voice.

"natural": Microsoft's free neural voices (the ones Edge's Read Aloud uses), via
edge-tts. No key needed, but needs internet. Every sentence starts being made the
moment it arrives (a few at once) and they play in order, so there are no gaps.
"windows": the built-in Windows voice. Offline, instant, but robotic.
If natural fails (offline etc.) Eris falls back to the Windows voice by herself.
"""
import asyncio
import os
import random
import queue
import re
import sys
import tempfile
import threading
import time

from . import config

VOICES = {  # label in settings -> edge-tts voice name
    "Ava (US, warm)": "en-US-AvaNeural",
    "Emma (US, bright)": "en-US-EmmaNeural",
    "Jenny (US, friendly)": "en-US-JennyNeural",
    "Aria (US, confident)": "en-US-AriaNeural",
    "Sonia (UK)": "en-GB-SoniaNeural",
    "Libby (UK, soft)": "en-GB-LibbyNeural",
    "Natasha (Australia)": "en-AU-NatashaNeural",
}
ACKS = ["Mm-hm.", "On it.", "Okay, let me look.", "Sure thing.", "One sec."]
PREVIEW = "Hi, I'm Eris. Ask me anything, and I'll show you exactly where to click."


def pieces(text, shortest=25, split_over=60):
    """A long line split at its commas (and ; : dashes) into pieces of a sensible size: the
    online voice makes a whole piece before any of it plays, so the first piece of a long
    line can start playing while the rest are still being made."""
    if len(text) <= split_over:
        return [text]
    out, piece = [], ""
    for part in re.split(r"(?<=[,;:\u2013\u2014])\s+", text):
        piece = f"{piece} {part}".strip()
        if len(piece) >= shortest:
            out.append(piece)
            piece = ""
    if piece:                     # a short tail joins the last piece
        if out:
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


class _Clip:
    """One line on its way to being spoken: made in the background, played in order."""

    def __init__(self, gen, text="", path=None, voice=None):
        self.gen, self.text, self.path, self.voice = gen, text, path, voice
        self.failed = self.skip = False
        self.ready = threading.Event()
        if path:
            self.ready.set()


class Voice:
    MAKERS = 3                     # sentences made at the same time

    def __init__(self, log=None):
        self.log = log or (lambda *a: None)
        self.gen = 0
        self.audio_q = queue.Queue()   # clips, in the order they're said
        self.sapi_q = queue.Queue()
        self.tmp = tempfile.mkdtemp(prefix="eris-voice-")
        self.warned = False
        self.natural_off_until = 0.0   # after a failure, use the Windows voice for a bit
        self.playing = False           # a natural-voice clip is playing (or about to) right now
        self.fetching = 0              # sentences being turned into speech right now
        self._makers = threading.Semaphore(self.MAKERS)
        self._n = 0
        self._lock = threading.Lock()
        self._first = None             # (gen, time) of the first line queued since the last stop
        self.sapi_speaking = False     # the Windows voice is speaking right now
        self.sapi_alive = False        # the Windows voice is up and running
        self.made_early = {}           # (line, voice, rate) -> clip made before it's needed
        threading.Thread(target=self.prepare_acks, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()
        threading.Thread(target=self._sapi_loop, daemon=True).start()

    # ---------- public ----------
    def say(self, text: str, force=False, voice=None):
        """voice: a specific natural voice for this line (used by the preview button)."""
        if not (config.VOICE_ON or force):
            return
        if self._first is None or self._first[0] != self.gen:
            self._first = (self.gen, time.time())
        early = self.made_early.get(self._early_key(text)) if voice is None else None
        if self._natural() and early and os.path.exists(early):
            self.audio_q.put(_Clip(self.gen, text, path=early))     # made ahead: plays at once
        elif self._natural():
            for piece in pieces(text):        # long lines start sooner in pieces
                clip = _Clip(self.gen, piece, voice=voice)
                self.audio_q.put(clip)
                threading.Thread(target=self._make, args=(clip,), daemon=True).start()
        else:
            self.sapi_q.put(("say", text))

    @staticmethod
    def _early_key(text):
        return text, config.VOICE_NAME, int(config.VOICE_RATE)

    def prepare(self, text):
        """Make a line's speech now, before it's needed (a step planned ahead), so that
        when it's said it plays at once."""
        if not (config.VOICE_ON and text and self._natural()):
            return
        key = self._early_key(text)

        def make():
            clip = _Clip(-1, text)
            clip.path = os.path.join(self.tmp, f"early{abs(hash(key)) % 10**8}.mp3")
            try:
                import edge_tts
                comm = edge_tts.Communicate(text, config.VOICE_NAME, rate=f"{int(config.VOICE_RATE) * 6:+d}%")
                asyncio.run(asyncio.wait_for(comm.save(clip.path), 6))
            except Exception:
                return
            self.made_early[key] = clip.path
            while len(self.made_early) > 8:          # keep just the last few
                self.made_early.pop(next(iter(self.made_early)))
        threading.Thread(target=make, daemon=True).start()

    def ack(self):
        """A tiny instant reply ("On it.") so you know she heard you. Natural-voice
        clips are made once in the background and kept, so they play instantly."""
        if not (config.VOICE_ON and config.ACK):
            return
        clips = self._ack_clips()
        if self._natural() and clips:
            self.audio_q.put(_Clip(self.gen, path=random.choice(clips)))
        elif not self._natural():
            self.sapi_q.put(("say", random.choice(ACKS)))

    def _ack_dir(self):
        from . import settings
        return settings.folder() / "voice" / config.VOICE_NAME

    def _ack_clips(self):
        d = self._ack_dir()
        return [str(p) for p in sorted(d.glob("ack*.mp3"))] if d.exists() else []

    def prepare_acks(self):
        """Make the quick-reply clips for the current voice (once, in the background)."""
        if sys.platform != "win32" or config.VOICE_ENGINE != "natural":
            return
        try:
            import edge_tts
            d = self._ack_dir()
            d.mkdir(parents=True, exist_ok=True)
            loop = asyncio.new_event_loop()
            for i, text in enumerate(ACKS):
                path = d / f"ack{i}.mp3"
                if not path.exists():
                    tmp = d / f"ack{i}.tmp"
                    comm = edge_tts.Communicate(text, config.VOICE_NAME, rate="+8%")
                    loop.run_until_complete(asyncio.wait_for(comm.save(str(tmp)), 8))
                    os.replace(tmp, path)
            loop.close()
        except Exception:
            pass

    def _natural(self):
        return (config.VOICE_ENGINE == "natural" and sys.platform == "win32"
                and time.time() >= self.natural_off_until)

    def busy(self):
        """Is she talking (or about to)? Call mode doesn't listen while she is."""
        return (self.playing or self.fetching > 0 or self.sapi_speaking or not self.audio_q.empty()
                or self.sapi_alive and any(cmd == "say" for cmd, _ in list(self.sapi_q.queue)))

    def stop(self):
        """Stop talking now (a new task, Stop, a new question)."""
        self.gen += 1
        self._drain()
        self.sapi_q.put(("stop", None))

    def _drain(self):
        for q in (self.audio_q, self.sapi_q):
            try:
                while True:
                    item = q.get_nowait()
                    if isinstance(item, _Clip):
                        item.skip = True
            except queue.Empty:
                pass

    # ---------- natural voice ----------
    def _make(self, clip):
        """Turn one line into speech (several run at once; each waits for a free maker)."""
        with self._makers:
            if clip.skip or clip.gen != self.gen or time.time() < self.natural_off_until:
                clip.failed = True           # dropped, or the server is down (Windows voice)
                clip.ready.set()
                return
            with self._lock:
                self._n += 1
                self.fetching += 1
                clip.path = os.path.join(self.tmp, f"s{self._n % 50}.mp3")
            try:
                import edge_tts
                rate = f"{int(config.VOICE_RATE) * 6:+d}%"
                comm = edge_tts.Communicate(clip.text, clip.voice or config.VOICE_NAME, rate=rate)
                asyncio.run(asyncio.wait_for(comm.save(clip.path), 6))
            except Exception as e:
                # Don't make every sentence wait for a slow/offline server: switch to
                # the Windows voice for a minute, then try the natural one again.
                clip.failed = True
                self.natural_off_until = time.time() + 60
                if not self.warned:
                    self.warned = True
                    self.log("hint", f"Natural voice unavailable ({e.__class__.__name__}), "
                                     "using the Windows voice. Needs internet.")
            finally:
                with self._lock:
                    self.fetching -= 1
                clip.ready.set()

    def _play_loop(self):
        if sys.platform != "win32":
            return
        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW
        buf = ctypes.create_unicode_buffer(64)
        while True:
            clip = self.audio_q.get()
            g = clip.gen
            if g != self.gen or clip.skip:
                continue
            self.playing = True
            while not clip.ready.wait(0.05):          # still being made
                if g != self.gen or clip.skip:
                    break
            if g != self.gen or clip.skip or clip.failed:
                if g == self.gen and not clip.skip and clip.text:
                    self.sapi_q.put(("say", clip.text))   # natural voice failed: Windows voice
                self.playing = False
                continue
            path = clip.path
            if self._first and self._first[0] == g and "ack" not in os.path.basename(path):
                self.log("debug", f"speed: voice started {time.time() - self._first[1]:.2f}s "
                                  "after her first line arrived (natural voice)")
                self._first = (None, 0)
            mci(f'open "{path}" type mpegvideo alias eris', None, 0, None)
            mci("play eris", None, 0, None)
            time.sleep(0.05)
            while True:
                if g != self.gen:
                    mci("stop eris", None, 0, None)
                    break
                mci("status eris mode", buf, 64, None)
                if buf.value != "playing":
                    break
                time.sleep(0.03)
            mci("close eris", None, 0, None)
            self.playing = False

    # ---------- Windows voice ----------
    def _sapi_loop(self):
        try:
            self._run_windows_voice()
        finally:
            self.sapi_alive = False     # it stopped: queued lines can't be spoken, so don't wait on them

    def _run_windows_voice(self):
        if sys.platform != "win32":
            try:
                import pyttsx3
                engine = pyttsx3.init()
            except Exception:
                return
            self.sapi_alive = True
            while True:
                cmd, text = self.sapi_q.get()
                if cmd == "say":
                    engine.say(text)
                    engine.runAndWait()
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        self.sapi_alive = True
        try:  # prefer a female voice if one is installed (e.g. Zira)
            for v in voice.GetVoices():
                if "zira" in v.GetDescription().lower():
                    voice.Voice = v
                    break
        except Exception:
            pass
        ASYNC, PURGE = 1, 2
        while True:
            try:
                cmd, text = self.sapi_q.get(timeout=0.15)
            except queue.Empty:
                try:
                    self.sapi_speaking = voice.Status.RunningState == 2   # 2 = speaking
                except Exception:
                    self.sapi_speaking = False
                continue
            self.sapi_speaking = True
            if cmd == "stop":
                voice.Speak("", ASYNC | PURGE)
            else:
                voice.Rate = int(config.VOICE_RATE)
                voice.Speak(text, ASYNC)


def beep(kind="start"):
    """Tiny sound so you know Eris heard you, before any thinking happens."""
    if sys.platform != "win32":
        return
    import winsound
    freq = {"start": 880, "stop": 660, "done": 990}.get(kind, 800)
    threading.Thread(target=winsound.Beep, args=(freq, 60), daemon=True).start()
