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
        self.pieces = None
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
            self.pieces = Pieces(self)

            def heard(d, *_):
                self.pieces.feed(d[:, 0].copy())
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                         blocksize=BLOCK, callback=heard)
            self.stream.start()

    def _stop(self):
        with self.lock:
            if not self.stream:
                return None
            self.stream.stop(); self.stream.close(); self.stream = None
            return self.pieces

    def abort(self):
        """Stop recording and throw the audio away (e.g. the button was only clicked)."""
        pieces = self._stop()
        if pieces:
            pieces.drop()

    def stop_and_transcribe(self) -> str:
        pieces = self._stop()
        return pieces.finish() if pieces else ""

    # ---------- speech to text ----------
    def transcribe(self, audio, before="") -> str:
        """before: what was said just before this piece (helps Whisper with the next words)."""
        if len(audio) < RATE * 0.3:  # under 0.3s = accidental tap
            return ""
        if np.sqrt(np.mean(audio ** 2)) < 0.0015:  # basically silence: don't let Whisper invent words
            return ""
        peak = float(np.max(np.abs(audio)))
        if 0.02 < peak < 0.3:   # quiet mic: turn it up so Whisper hears it clearly
            audio = audio * (0.5 / peak)
        with self.model_lock:
            segments, _ = self.model.transcribe(audio, beam_size=1, language="en",
                                                initial_prompt=f"{config.WHISPER_HINT}. {before}".strip(),
                                                condition_on_previous_text=False)
            # Drop bits Whisper is unsure were speech at all (it invents "Thank you." on noise).
            text = " ".join(s.text.strip() for s in segments
                            if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)).strip()
        return "" if text.lower().strip(" .!") in HALLUCINATIONS else text


class Pieces:
    """Turns what you say into text while you're still saying it: each time you pause,
    the words since the last pause are transcribed in the background, so when you stop
    only your last few words are left to do (instead of the whole thing)."""

    PAUSE = 12               # ~0.36 s of quiet after some voice ends a piece
    MIN_PIECE = 20           # ~0.6 s: shorter bits wait to join the next piece

    def __init__(self, ears):
        self.ears = ears
        self.blocks = []
        self.cut = 0             # where the piece being spoken now started
        self.voiced = False
        self.quiet = 0
        self.floor = None
        self.texts = []
        self.work = queue.Queue()
        self.total = 0
        threading.Thread(target=self._worker, daemon=True).start()

    def feed(self, block):
        self.blocks.append(block)
        self.total += len(block)
        rms = float(np.sqrt(np.mean(block ** 2)))
        if self.floor is None and len(self.blocks) >= 5:    # the room, before you speak
            self.floor = float(np.median([np.sqrt(np.mean(b ** 2)) for b in self.blocks]))
        loud = rms > max((self.floor or 0.002) * 3.0, 0.006)
        self.voiced = self.voiced or loud
        self.quiet = 0 if loud else self.quiet + 1
        if self.voiced and self.quiet >= self.PAUSE and len(self.blocks) - self.cut >= self.MIN_PIECE:
            self._send(len(self.blocks))

    def _send(self, end):
        piece, self.cut = self.blocks[self.cut:end], end
        self.voiced = False
        if piece:
            self.work.put(np.concatenate(piece))

    def _worker(self):
        while True:
            audio = self.work.get()
            if audio is None:
                return
            if isinstance(audio, threading.Event):
                audio.set()                  # everything before it is done
                continue
            text = self.ears.transcribe(audio, before=" ".join(self.texts)[-200:])
            if text:
                self.texts.append(text)

    def finish(self):
        """You stopped talking: the last words, then the whole thing as text."""
        if self.total < RATE * 0.3:          # under 0.3 s: an accidental tap
            self.drop()
            return ""
        self._send(len(self.blocks))
        done = threading.Event()
        self.work.put(done)
        done.wait(30)
        self.drop()
        return " ".join(self.texts).strip()

    def drop(self):
        self.work.put(None)


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
        pieces = None
        while self.running:
            try:
                block = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.muted():
                if det.talking and pieces:
                    pieces.drop()
                det.reset()
                tail = 12        # then skip ~0.35 s more, so the echo of her voice dies down
                continue
            if tail:
                tail -= 1
                continue
            event, _ = det.feed(block)
            if event == "start":
                pieces = Pieces(self.ears)        # transcribe while you're still talking
                for b in det.buf:
                    pieces.feed(b)
                self.on_start()
            elif det.talking:
                pieces.feed(block)
            elif event == "drop":
                pieces.drop()
                self.on_text("")          # back to normal: it was nothing
            elif event == "end":
                pieces.feed(block)
                threading.Thread(target=lambda p=pieces: self.on_text(p.finish()), daemon=True).start()
