import logging
import asyncio
import collections
import queue
import statistics
import numpy as np
import sounddevice as sd
from pidreams.core.config import CONFIG

log = logging.getLogger(__name__)

# The speech threshold comes from the room's quiet moments (20th percentile of the chunk levels), not the
# mean: one loud sound during the 1.5 s calibration measured 0.055 against the usual 0.002-0.006, the
# threshold went over the user's voice, speech never "started" and every recording ran to the 30 s cap
# (2026-11-09). The cap is below normal speech levels for the same reason.
_QUIET_PERCENTILE = 20
_MIN_THRESHOLD, _MAX_THRESHOLD = 0.004, 0.02


def _threshold_from(levels: list[float]) -> tuple[float, float]:
    """Chunk levels (rms) of a stretch of room sound → (noise floor, speech threshold)."""
    noise = float(np.percentile(levels, _QUIET_PERCENTILE))
    return noise, min(max(noise * 1.8, _MIN_THRESHOLD), _MAX_THRESHOLD)


class AudioRecorder:
    def __init__(self, mic_device_ref: list | None = None):
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._threshold: float = CONFIG.silence_threshold
        self._mic_device_ref = mic_device_ref if mic_device_ref is not None else [CONFIG.mic_device_index]
        # Microphone level / playback level while the assistant speaks: how much of its own voice the
        # microphone hears back from the speakers. Learned across turns.
        self._echo_ratios: collections.deque[float] = collections.deque(maxlen=80)

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
            noise_rms, self._threshold = _threshold_from([float(np.sqrt(np.mean(c ** 2))) for c in samples])
            log.info(f"[VAD] Ambient noise: {noise_rms:.4f} -> threshold: {self._threshold:.4f}")
        else:
            log.warning(f"[VAD] Calibration failed, using the default threshold: {self._threshold:.4f}")

    async def record_until_silence(self, cancel_check=None) -> np.ndarray:
        self._flush_queue()

        frames: list[np.ndarray] = []
        levels: list[float] = []
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
                levels.append(rms)

                if rms > self._threshold:
                    if not speaking_started:
                        log.info("🎤 Listening...")
                        speaking_started = True
                    silent_chunks = 0
                elif speaking_started:
                    silent_chunks += 1
                    if silent_chunks >= silence_needed:
                        break

        if not frames:              # cancelled before any audio arrived (closing, switching mode)
            return np.array([], dtype=np.float32)
        if not speaking_started and len(frames) >= max_chunks:
            # A whole recording without crossing the threshold: if the room is quieter than it was at
            # calibration, the threshold is relearned from this recording's quiet moments.
            noise, threshold = _threshold_from(levels)
            if threshold < self._threshold:
                log.info("[VAD] threshold %.4f -> %.4f (room noise now %.4f)", self._threshold, threshold, noise)
                self._threshold = threshold
        return np.concatenate(frames, axis=0).flatten()

    def _echo_gain(self) -> float:
        """90th percentile of the microphone/playback ratio: the loud parts of the echo, not the typical
        one (with the median, "do avião podentes." still interrupted the news, 2026-11-04). 1.0 (the
        echo as loud as the voice) until learned."""
        if len(self._echo_ratios) < 8:
            return 1.0
        return statistics.quantiles(self._echo_ratios, n=10)[-1]

    async def record_while_agent_speaks(self, interrupt_cb, cancel_check=None, playback_level=None) -> np.ndarray:
        """playback_level() → level of the assistant's voice playing now. Speech only counts as an
        interruption when the microphone is well above the echo expected from that level: on
        2026-11-04 the speakers' echo reached the microphone louder than the user's own voice
        (peaks 0.17-0.24 vs 0.07-0.14) and the assistant kept interrupting itself."""
        self._flush_queue()
        recent_playback: collections.deque[float] = collections.deque(maxlen=5)   # ~320 ms: output latency + room tail

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
                    loud = rms > interrupt_threshold
                    if playback_level is not None:
                        recent_playback.append(playback_level())
                        playing = max(recent_playback)
                        if playing > 0.005:
                            loud = loud and rms > CONFIG.interrupt_echo_margin * self._echo_gain() * playing
                            if not loud:
                                self._echo_ratios.append(rms / playing)
                    if loud:
                        consecutive_loud += 1
                        pre_buffer.append(chunk)
                        if consecutive_loud >= min_chunks:
                            log.info("[VAD] interrupted: mic %.4f, playback %.4f, echo gain %.3f (%d samples)",
                                     rms, max(recent_playback, default=0.0), self._echo_gain(), len(self._echo_ratios))
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
