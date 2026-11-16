"""Hearing you: push-to-talk recording, "call mode" (always listening, works out by
itself when you start and stop talking), and local speech-to-text (faster-whisper).
Audio never leaves your PC and is never saved."""
import collections
import queue
import threading

import numpy as np
import sounddevice as sd

from . import config

RATE = 16000
BLOCK = 480                      # 30 ms of audio
HALLUCINATIONS = {"thank you", "thanks for watching", "you", "bye", "thank you for watching"}


class Ears:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
        self.frames = []
        self.stream = None
        self.lock = threading.Lock()
        self.model_lock = threading.Lock()
        # Warm up so the first real question isn't slow.
        self.model.transcribe(np.zeros(RATE // 2, dtype=np.float32), beam_size=1)

    # ---------- push-to-talk ----------
    def start(self):
        with self.lock:
            if self.stream:
                return
            self.frames = []
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                         callback=lambda d, *_: self.frames.append(d.copy()))
            self.stream.start()

    def _stop(self):
        with self.lock:
            if not self.stream:
                return None
            self.stream.stop(); self.stream.close(); self.stream = None
            return self.frames

    def abort(self):
        """Stop recording and throw the audio away (e.g. the button was only clicked)."""
        self._stop()

    def stop_and_transcribe(self) -> str:
        frames = self._stop()
        if not frames:
            return ""
        return self.transcribe(np.concatenate(frames).flatten())

    # ---------- speech to text ----------
    def transcribe(self, audio) -> str:
        if len(audio) < RATE * 0.3:  # under 0.3s = accidental tap
            return ""
        if np.sqrt(np.mean(audio ** 2)) < 0.0015:  # basically silence: don't let Whisper invent words
            return ""
        peak = float(np.max(np.abs(audio)))
        if 0.02 < peak < 0.3:   # quiet mic: turn it up so Whisper hears it clearly
            audio = audio * (0.5 / peak)
        with self.model_lock:
            segments, _ = self.model.transcribe(audio, beam_size=1, language="en",
                                                initial_prompt=config.WHISPER_HINT,
                                                condition_on_previous_text=False)
            # Drop bits Whisper is unsure were speech at all (it invents "Thank you." on noise).
            text = " ".join(s.text.strip() for s in segments
                            if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)).strip()
        return "" if text.lower().strip(" .!") in HALLUCINATIONS else text


class Speech:
    """Finds where speech starts and ends in a stream of 30 ms audio blocks, by
    comparing loudness to the room's background noise (which it keeps learning)."""

    START_BLOCKS = 3          # ~90 ms of voice to count as "started talking"
    END_SILENCE = 27          # ~0.8 s of quiet to count as "finished"
    MAX_BLOCKS = 667          # ~20 s: send it anyway
    MIN_VOICE = 10            # need ~0.3 s of actual voice, or it was a cough or a click

    def __init__(self):
        self.floor = None          # background noise level, measured in the first ~0.5 s
        self.warm = []
        self.reset()

    def reset(self):
        self.pre = collections.deque(maxlen=10)   # ~300 ms kept from before you started
        self.talking = False
        self.voiced = self.quiet = self.loud = 0
        self.buf = []

    def feed(self, block):
        """Returns ("start", None), ("end", audio) or (None, None)."""
        rms = float(np.sqrt(np.mean(block ** 2)))
        if self.floor is None:     # first: listen to the room for a moment
            self.warm.append(rms)
            if len(self.warm) >= 16:
                self.floor = max(0.0008, float(np.median(self.warm)))
            return None, None
        if not self.talking:
            # keep learning the background: drop quickly, rise slowly (so talking
            # doesn't count as background, but a fan switching on soon does)
            rate = 0.1 if rms < self.floor else 0.004
            self.floor = min(0.05, max(0.0008, (1 - rate) * self.floor + rate * rms))
            self.pre.append(block)
            self.voiced = self.voiced + 1 if rms > max(self.floor * 3.5, 0.006) else 0
            if self.voiced >= self.START_BLOCKS:
                self.talking, self.buf, self.quiet = True, list(self.pre), 0
                self.loud = self.voiced
                return "start", None
            return None, None
        self.buf.append(block)
        if rms > max(self.floor * 3.5, 0.006):
            self.loud += 1
        self.quiet = self.quiet + 1 if rms < max(self.floor * 2.2, 0.004) else 0
        if self.quiet >= self.END_SILENCE or len(self.buf) >= self.MAX_BLOCKS:
            audio, loud = np.concatenate(self.buf), self.loud
            self.reset()
            if loud >= self.MIN_VOICE:
                return "end", audio
            return "drop", None   # just a click or a cough
        return None, None


class Call:
    """Call mode: the microphone stays open and every time you finish a sentence it's
    transcribed and handed to Eris. While she's talking (and a moment after) it doesn't
    listen, so it never hears her own voice from your speakers."""

    def __init__(self, ears, on_start, on_text, muted):
        self.ears, self.on_start, self.on_text, self.muted = ears, on_start, on_text, muted
        self.q = queue.Queue()
        self.running = False
        self.stream = None

    def start(self):
        self.running = True
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                     blocksize=BLOCK, callback=lambda d, *_: self.q.put(d[:, 0].copy()))
        self.stream.start()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
            self.stream = None

    def _loop(self):
        det = Speech()
        tail = 0
        while self.running:
            try:
                block = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.muted():
                det.reset()
                tail = 12        # then skip ~0.35 s more, so the echo of her voice dies down
                continue
            if tail:
                tail -= 1
                continue
            event, audio = det.feed(block)
            if event == "start":
                self.on_start()
            elif event == "drop":
                self.on_text("")          # back to normal: it was nothing
            elif event == "end":
                threading.Thread(target=self._hear, args=(audio,), daemon=True).start()

    def _hear(self, audio):
        text = self.ears.transcribe(audio)
        self.on_text(text)
