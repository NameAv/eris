"""Eris's voice.

"natural": Microsoft's free neural voices (the ones Edge's Read Aloud uses), via
edge-tts. No key needed, but needs internet. The next sentence is generated
while the current one plays, so there are no gaps.
"windows": the built-in Windows voice. Offline, instant, but robotic.
If natural fails (offline etc.) Eris falls back to the Windows voice by herself.
"""
import asyncio
import os
import random
import queue
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
PREVIEW = "Hi, I'm Eris. Hold F8 and ask me anything, and I'll show you where to click."


class Voice:
    def __init__(self, log=None):
        self.log = log or (lambda *a: None)
        self.gen = 0
        self.text_q = queue.Queue()
        self.audio_q = queue.Queue()
        self.sapi_q = queue.Queue()
        self.tmp = tempfile.mkdtemp(prefix="eris-voice-")
        self.warned = False
        self.natural_off_until = 0.0   # after a failure, use the Windows voice for a bit
        threading.Thread(target=self.prepare_acks, daemon=True).start()
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()
        threading.Thread(target=self._sapi_loop, daemon=True).start()

    # ---------- public ----------
    def say(self, text: str, force=False, voice=None):
        """voice: a specific natural voice for this line (used by the preview button)."""
        if not (config.VOICE_ON or force):
            return
        if self._natural():
            self.text_q.put((self.gen, text, voice))
        else:
            self.sapi_q.put(("say", text))

    def ack(self):
        """A tiny instant reply ("On it.") so you know she heard you. Natural-voice
        clips are made once in the background and kept, so they play instantly."""
        if not (config.VOICE_ON and config.ACK):
            return
        clips = self._ack_clips()
        if self._natural() and clips:
            self.audio_q.put((self.gen, random.choice(clips)))
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

    def stop(self):
        self.gen += 1
        for q in (self.text_q, self.audio_q, self.sapi_q):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
        self.sapi_q.put(("stop", None))

    # ---------- natural voice ----------
    def _synth_loop(self):
        loop = asyncio.new_event_loop()
        n = 0
        while True:
            g, text, voice = self.text_q.get()
            if g != self.gen:
                continue
            if time.time() < self.natural_off_until:   # already queued, but server is down
                self.sapi_q.put(("say", text))
                continue
            n += 1
            path = os.path.join(self.tmp, f"s{n % 50}.mp3")
            try:
                import edge_tts
                rate = f"{int(config.VOICE_RATE) * 6:+d}%"
                comm = edge_tts.Communicate(text, voice or config.VOICE_NAME, rate=rate)
                loop.run_until_complete(asyncio.wait_for(comm.save(path), 6))
                self.audio_q.put((g, path))
            except Exception as e:
                # Don't make every sentence wait for a slow/offline server: switch to
                # the Windows voice for a minute, then try the natural one again.
                self.natural_off_until = time.time() + 60
                if not self.warned:
                    self.warned = True
                    self.log("hint", f"Natural voice unavailable ({e.__class__.__name__}), "
                                     "using the Windows voice. Needs internet.")
                if g == self.gen:
                    self.sapi_q.put(("say", text))

    def _play_loop(self):
        if sys.platform != "win32":
            return
        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW
        buf = ctypes.create_unicode_buffer(64)
        while True:
            g, path = self.audio_q.get()
            if g != self.gen:
                continue
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

    # ---------- Windows voice ----------
    def _sapi_loop(self):
        if sys.platform != "win32":
            try:
                import pyttsx3
                engine = pyttsx3.init()
            except Exception:
                return
            while True:
                cmd, text = self.sapi_q.get()
                if cmd == "say":
                    engine.say(text)
                    engine.runAndWait()
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        try:  # prefer a female voice if one is installed (e.g. Zira)
            for v in voice.GetVoices():
                if "zira" in v.GetDescription().lower():
                    voice.Voice = v
                    break
        except Exception:
            pass
        ASYNC, PURGE = 1, 2
        while True:
            cmd, text = self.sapi_q.get()
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
