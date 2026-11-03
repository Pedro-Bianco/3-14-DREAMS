import logging
import asyncio
import queue
import numpy as np
import sounddevice as sd
from pidreams.core.config import CONFIG

log = logging.getLogger(__name__)


class AudioRecorder:
    def __init__(self, mic_device_ref: list | None = None):
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._threshold: float = CONFIG.silence_threshold
        self._mic_device_ref = mic_device_ref if mic_device_ref is not None else [CONFIG.mic_device_index]

    def _callback(self, indata: np.ndarray, frames: int, time, status):
        if status:
            log.info(f"[Audio: {status}]")
        self._queue.put(indata.copy())

    def _stream_kwargs(self) -> dict:
        kwargs = dict(
            samplerate=CONFIG.sample_rate,
            channels=CONFIG.channels,
            blocksize=CONFIG.chunk_size,
            dtype="float32",
            callback=self._callback,
        )
        device = self._mic_device_ref[0]
        if device is not None:
            kwargs["device"] = device
        return kwargs

    def _flush_queue(self):
        while not self._queue.empty():
            self._queue.get_nowait()

    def _chunks_timing(self) -> tuple[int, int, int]:
        chunks_per_sec = CONFIG.sample_rate / CONFIG.chunk_size
        silence_needed = int(CONFIG.silence_duration_sec * chunks_per_sec)
        max_chunks = int(CONFIG.max_recording_sec * chunks_per_sec)
        return chunks_per_sec, silence_needed, max_chunks

    async def calibrate(self):
        log.info("[VAD] Calibrating noise level... (do not speak)")
        samples: list[np.ndarray] = []

        with sd.InputStream(**self._stream_kwargs()):
            deadline = asyncio.get_event_loop().time() + 1.5
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = self._queue.get_nowait()
                    samples.append(chunk)
                except queue.Empty:
                    await asyncio.sleep(0.02)

        if samples:
            noise_rms = float(np.sqrt(np.mean(np.concatenate(samples) ** 2)))
            self._threshold = min(max(noise_rms * 1.8, 0.004), 0.05)
            log.info(f"[VAD] Ambient noise: {noise_rms:.4f} -> threshold: {self._threshold:.4f}")
        else:
            log.warning(f"[VAD] Calibration failed, using the default threshold: {self._threshold:.4f}")

    async def record_until_silence(self, cancel_check=None) -> np.ndarray:
        self._flush_queue()

        frames: list[np.ndarray] = []
        silent_chunks = 0
        speaking_started = False
        _, silence_needed, max_chunks = self._chunks_timing()

        with sd.InputStream(**self._stream_kwargs()):
            while len(frames) < max_chunks:
                if cancel_check and cancel_check():
                    break
                try:
                    chunk = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.02)
                    continue

                rms = float(np.sqrt(np.mean(chunk ** 2)))
                frames.append(chunk)

                if rms > self._threshold:
                    if not speaking_started:
                        log.info("🎤 Listening...")
                        speaking_started = True
                    silent_chunks = 0
                elif speaking_started:
                    silent_chunks += 1
                    if silent_chunks >= silence_needed:
                        break

        audio = np.concatenate(frames, axis=0).flatten()
        return audio

    async def record_while_agent_speaks(self, interrupt_cb, cancel_check=None) -> np.ndarray:
        self._flush_queue()

        interrupt_threshold = self._threshold * CONFIG.interrupt_threshold_factor
        min_chunks = CONFIG.interrupt_min_chunks
        _, silence_needed, max_chunks = self._chunks_timing()

        pre_buffer: list[np.ndarray] = []
        frames: list[np.ndarray] = []
        consecutive_loud = 0
        interrupt_triggered = False
        silent_chunks = 0

        with sd.InputStream(**self._stream_kwargs()):
            while True:
                if cancel_check and cancel_check():
                    break
                try:
                    chunk = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.02)
                    continue

                rms = float(np.sqrt(np.mean(chunk ** 2)))

                if not interrupt_triggered:
                    if rms > interrupt_threshold:
                        consecutive_loud += 1
                        pre_buffer.append(chunk)
                        if consecutive_loud >= min_chunks:
                            interrupt_triggered = True
                            interrupt_cb()
                            frames = list(pre_buffer)
                            pre_buffer = []
                    else:
                        consecutive_loud = 0
                        pre_buffer = pre_buffer[-(min_chunks - 1):]
                else:
                    frames.append(chunk)
                    if rms > self._threshold:
                        silent_chunks = 0
                    else:
                        silent_chunks += 1
                        if silent_chunks >= silence_needed or len(frames) >= max_chunks:
                            break

        if not frames:
            return np.array([], dtype=np.float32)
        return np.concatenate(frames, axis=0).flatten()
