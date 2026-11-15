"""Push-to-talk recording + local speech-to-text (faster-whisper)."""
import threading

import numpy as np
import sounddevice as sd

from . import config

RATE = 16000


class Ears:
    def __init__(self):
        print("Loading speech model (first run downloads it)...")
        from faster_whisper import WhisperModel
        self.model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
        self.frames = []
        self.stream = None
        self.lock = threading.Lock()
        # Warm up so the first real question isn't slow.
        self.model.transcribe(np.zeros(RATE // 2, dtype=np.float32), beam_size=1)

    def start(self):
        with self.lock:
            if self.stream:
                return
            self.frames = []
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                         callback=lambda d, *_: self.frames.append(d.copy()))
            self.stream.start()

    def stop_and_transcribe(self) -> str:
        with self.lock:
            if not self.stream:
                return ""
            self.stream.stop(); self.stream.close(); self.stream = None
            frames = self.frames
        if not frames:
            return ""
        audio = np.concatenate(frames).flatten()
        if len(audio) < RATE * 0.3:  # under 0.3s = accidental tap
            return ""
        if np.sqrt(np.mean(audio ** 2)) < 0.004:  # basically silence: don't let Whisper invent words
            return ""
        segments, _ = self.model.transcribe(audio, beam_size=1, language="en",
                                            initial_prompt=config.WHISPER_HINT)
        return " ".join(s.text.strip() for s in segments).strip()
