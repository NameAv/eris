"""Eris's voice. Speaks one sentence at a time and can be cut off instantly."""
import queue
import sys
import threading

from . import config


class Voice:
    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text: str):
        if not config.VOICE_ON:
            return
        self.q.put(("say", text))

    def stop(self):
        # Drop anything not yet spoken, then cut off the current sentence.
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        self.q.put(("stop", None))

    def _run(self):
        if sys.platform == "win32":
            self._run_sapi()
        else:
            self._run_pyttsx3()

    def _run_sapi(self):
        # Windows built-in voice. Async + purge means no lag and instant stop.
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Rate = config.VOICE_RATE
        ASYNC, PURGE = 1, 2
        while True:
            cmd, text = self.q.get()
            if cmd == "stop":
                voice.Speak("", ASYNC | PURGE)
            else:
                voice.Rate = int(config.VOICE_RATE)
                voice.Speak(text, ASYNC)  # queues behind the current sentence

    def _run_pyttsx3(self):
        import pyttsx3
        engine = pyttsx3.init()
        while True:
            cmd, text = self.q.get()
            if cmd == "say":
                engine.say(text)
                engine.runAndWait()


def beep(kind="start"):
    """Tiny sound so you know Eris heard you, before any thinking happens."""
    if sys.platform != "win32":
        return
    import winsound
    freq = {"start": 880, "stop": 660, "done": 990}.get(kind, 800)
    threading.Thread(target=winsound.Beep, args=(freq, 70), daemon=True).start()
