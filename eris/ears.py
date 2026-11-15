"""Push-to-talk recording + local speech-to-text (faster-whisper)."""
import threading

import numpy as np
import sounddevice as sd

from . import config

RATE = 16000
HALLUCINATIONS = {"thank you", "thanks for watching", "you", "bye", "thank you for watching"}


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
        if np.sqrt(np.mean(audio ** 2)) < 0.0015:  # basically silence: don't let Whisper invent words
            return ""
        peak = float(np.max(np.abs(audio)))
        if 0.02 < peak < 0.3:   # quiet mic: turn it up so Whisper hears it clearly
            audio = audio * (0.5 / peak)
        segments, _ = self.model.transcribe(audio, beam_size=1, language="en",
                                            initial_prompt=config.WHISPER_HINT,
                                            condition_on_previous_text=False)
        # Drop bits Whisper is unsure were speech at all (it invents "Thank you." on noise).
        text = " ".join(s.text.strip() for s in segments
                        if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)).strip()
        return "" if text.lower().strip(" .!") in HALLUCINATIONS else text
