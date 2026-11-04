import logging
import re
import asyncio
from time import perf_counter     # not "import time": the audio callback has a parameter named time
import threading
import queue as stdlib_queue
import collections
import numpy as np
import sounddevice as sd
from num2words import num2words
from pidreams.audio import effects, english, voices
from pidreams.core import paths
from pidreams.core.config import CONFIG
from pidreams.core.settings import SETTINGS
from pidreams.core.text import remove_emojis

log = logging.getLogger(__name__)

_BLOCKSIZE = 2048
KOKORO_RATE = 24000          # Kokoro v1.0 always outputs 24 kHz

# RMS of the block playing right now (0 = silence). Written by the audio callback,
# read by the panel's face to open the mouth in time with the syllables.
VOICE_LEVEL: list[float] = [0.0]
# Sentence whose audio is playing right now ("" = silence). Set by the audio callback the
# moment the sentence starts sounding, so the window's caption follows the voice, not the text.
SPEAKING_TEXT: list[str] = [""]

# Normalization — compiled patterns
_MARKDOWN_RE = re.compile(r'(\*{1,3}|_{1,3}|~~|`+|#{1,6})\s*')
_NUM_RE = re.compile(r'\b\d+(?:[.,]\d+)?\b')
_LIST_MARK_RE = re.compile(r'^\s*[-•]\s+')       # "- headline": the list marker is not spoken


def _num_to_words(m: re.Match) -> str:
    raw = m.group(0)
    try:
        if ',' in raw or '.' in raw:
            return num2words(float(raw.replace(',', '.')), lang='pt_BR')
        return num2words(int(raw), lang='pt_BR')
    except Exception:
        return raw


def _normalize(text: str) -> str:
    text = _LIST_MARK_RE.sub('', text)
    text = _MARKDOWN_RE.sub(' ', text)
    text = remove_emojis(text)
    text = _NUM_RE.sub(_num_to_words, text)
    return re.sub(r'\s+', ' ', text).strip()


def sample(name: str, text: str) -> np.ndarray:
    """One sentence in the voice `name`, with the assistant effect when it is on (the first-run
    wizard's preview). 24 kHz."""
    engine = TTSEngine()
    engine._load_voice(name)
    return np.concatenate([np.zeros(0, np.float32), *engine._synthesize(_normalize(text))])


class TTSEngine:
    """
    Local TTS: the default Pocket TTS voice (streaming) or the optional Kokoro ones, both on the CPU
    at 24 kHz.

    Two threads:
      - synth thread: text → PCM through the loaded voice (blocking)
      - stream callback: plays the deque in real time (no gap between sentences)
    """

    BLOCKSIZE = _BLOCKSIZE
    # When the turn's first sentence started sounding (perf_counter); the loop resets it per turn
    # to log how long the user waited.
    first_audio_at: float | None = None

    def __init__(self, out_device_ref=None, volume_ref=None):
        self._out_device_ref = out_device_ref if out_device_ref is not None else [None]
        self._volume_ref     = volume_ref if volume_ref is not None else [1.0]

        self._pocket = None                  # audio.pocket.PocketVoice when the Pocket voice is loaded
        self._kokoro = None                  # kokoro_onnx.Kokoro when a Kokoro voice is loaded
        self._kokoro_voice = ""              # voice id, or a blended style vector
        self._sample_rate: int               = KOKORO_RATE

        # Playback buffer — the callback reads from here
        self._play_buf: collections.deque[np.ndarray] = collections.deque()
        self._buf_lock  = threading.Lock()
        self._current:  np.ndarray | None = None
        self._pos:      int = 0
        # (first chunk of a sentence, its original text): marks where each caption starts
        self._captions: collections.deque[tuple[np.ndarray, str]] = collections.deque()

        # Continuous stream
        self._stream:        sd.OutputStream | None = None
        self._stream_device                         = None

        # Synthesis queue
        self._synth_q:    stdlib_queue.Queue    = stdlib_queue.Queue()
        self._synth_busy: bool                  = False
        self._synth_thread: threading.Thread | None = None

        # Interruption control
        self._interrupted = threading.Event()

    # ─────────────────────────────────────────────────────────────────────────
    #  Initialization
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        try:
            self._load_voice(CONFIG.voice_model)
        except Exception as e:
            # The voice files are downloaded with the install; without them the app still opens
            # (text chat works) and choosing a voice in the settings downloads them.
            log.error("[TTS] No voice: %s", e)
        # Changing the voice in the settings applies to the next sentence, without restarting.
        SETTINGS.subscribe(lambda st: self._switch_voice(st.get("voice.model")))

        self._synth_thread = threading.Thread(
            target=self._synth_loop, daemon=True, name="tts-synth")
        self._synth_thread.start()

    def _load_voice(self, name: str) -> None:
        from pidreams.hardware import models
        name = voices.resolve(name)
        if not voices.is_kokoro(name):
            from pidreams.audio.pocket import PocketVoice

            if not models.pocket_present():
                raise FileNotFoundError(f"A voz ainda não foi baixada (voz '{name}').")
            log.info(f"[TTS] Loading Pocket TTS '{name}'...")
            pocket = PocketVoice(voices.POCKET[name])
            self._pocket, self._kokoro, self._voice_name = pocket, None, name
        else:
            from kokoro_onnx import Kokoro

            if not models.kokoro_present():
                raise FileNotFoundError(f"As vozes Kokoro ainda não foram baixadas (voz '{name}').")
            log.info(f"[TTS] Loading Kokoro '{name}'...")
            folder = paths.models_dir("kokoro")
            engine = Kokoro(str(folder / "kokoro-v1.0.onnx"), str(folder / "voices-v1.0.bin"))
            kokoro_voice = voices.KOKORO[name]
            if isinstance(kokoro_voice, dict):        # a blend: weighted sum of the voices' styles
                kokoro_voice = sum(weight * engine.get_voice_style(voice) for voice, weight in kokoro_voice.items())
            self._kokoro, self._kokoro_voice, self._pocket, self._voice_name = engine, kokoro_voice, None, name
        log.info(f"[TTS] Voice '{name}' ready — {self._sample_rate} Hz.")

    def _switch_voice(self, name: str) -> None:
        # Compare with the requested voice, not just the loaded one: a second save during the
        # load (the microphone selector also saves) would load the same voice again.
        if name == getattr(self, "_requested_voice", getattr(self, "_voice_name", None)):
            return
        self._requested_voice = name
        def load():
            try:
                self._load_voice(name)
            except Exception as e:      # a bad voice must not silence the assistant
                log.warning("[TTS] Could not switch to voice '%s': %s", name, e)
        threading.Thread(target=load, daemon=True, name="tts-voz").start()

    # ─────────────────────────────────────────────────────────────────────────
    #  Stream callback (runs on the sounddevice thread)
    # ─────────────────────────────────────────────────────────────────────────

    def _callback(self, outdata: np.ndarray, frames: int, time, status) -> None:
        out    = np.zeros(frames, dtype=np.float32)
        filled = 0

        with self._buf_lock:
            while filled < frames:
                if self._current is None or self._pos >= len(self._current):
                    if self._play_buf:
                        self._current = self._play_buf.popleft()
                        self._pos     = 0
                        if self._captions and self._captions[0][0] is self._current:
                            SPEAKING_TEXT[0] = self._captions.popleft()[1]
                            if self.first_audio_at is None:
                                self.first_audio_at = perf_counter()
                    else:
                        break
                take = min(frames - filled, len(self._current) - self._pos)
                out[filled:filled + take] = self._current[self._pos:self._pos + take]
                filled    += take
                self._pos += take

        # Level BEFORE the volume: the face's mouth does not close because the user turned the sound down.
        VOICE_LEVEL[0] = float(np.sqrt(np.mean(out * out))) if filled else 0.0
        if not filled:
            SPEAKING_TEXT[0] = ""

        out *= float(self._volume_ref[0])
        outdata[:, 0] = out

    # ─────────────────────────────────────────────────────────────────────────
    #  Synthesis thread
    # ─────────────────────────────────────────────────────────────────────────

    def _synth_loop(self) -> None:
        while True:
            item = self._synth_q.get()
            if item is None:         # shutdown sentinel
                return
            caption, text = item

            self._synth_busy = True
            try:
                if self._interrupted.is_set():
                    continue

                for chunk in self._synthesize(text):
                    if self._interrupted.is_set():
                        break
                    if chunk is not None and len(chunk) > 0:
                        with self._buf_lock:
                            self._play_buf.append(chunk)
                            if caption:
                                self._captions.append((chunk, caption))
                                caption = ""

            except Exception as e:
                log.warning(f"[TTS] Synthesis error: {e}")
            finally:
                self._synth_busy = False

    def _synthesize(self, text: str):
        """float32 chunks of one sentence, from whichever voice is loaded, with the assistant effect
        when it is on (applied chunk by chunk, so a streaming voice still starts at once)."""
        effect = SETTINGS.get("voice.effect")
        if not effect:
            yield from self._voice_chunks(text)
            return
        shaper = effects.AssistantEffect(self._sample_rate, effect)
        for chunk in self._voice_chunks(text):
            yield shaper.process(chunk)
        yield shaper.flush()

    def _voice_chunks(self, text: str):
        pocket, kokoro = self._pocket, self._kokoro
        if pocket is not None:
            # Streams: the first chunk arrives ~0.1-0.2 s after the sentence starts (2026-11-04).
            # The length scale (speed) only applies to the Kokoro voices.
            # Its Portuguese model reads English words with Portuguese rules ("YouTube" came out as "coxo"):
            # they go respelled the way a Brazilian says them.
            yield from pocket.stream(english.respell(text), stop=self._interrupted)
        elif kokoro is not None:
            # Kokoro gives the whole sentence at once (one sentence ~0.8 s on CPU, measured 2026-11-04).
            audio, _rate = kokoro.create(text, voice=self._kokoro_voice, lang="pt-br",
                                         speed=1.0 / CONFIG.voice_length_scale)
            yield np.asarray(audio, dtype=np.float32)

    # ─────────────────────────────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def speak(self, text: str) -> None:
        caption = text.strip()
        text = _normalize(caption)
        if not text:
            return

        self._interrupted.clear()

        desired = self._out_device_ref[0]
        if self._stream is not None and self._stream_device != desired:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if self._stream is None:
            self._stream_device = desired
            kwargs = dict(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.BLOCKSIZE,
                callback=self._callback,
            )
            if desired is not None:
                kwargs["device"] = desired
            self._stream = sd.OutputStream(**kwargs)
            self._stream.start()

        self._synth_q.put((caption, text))

    async def drain(self) -> None:
        """Waits for synthesis + playback to finish."""
        while not self._synth_q.empty() or self._synth_busy:
            await asyncio.sleep(0.02)
        while True:
            with self._buf_lock:
                empty = (
                    not self._play_buf
                    and (self._current is None or self._pos >= len(self._current))
                )
            if empty:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(self.BLOCKSIZE / self._sample_rate * 3)

    def interrupt(self) -> None:
        """Stops immediately and clears every buffer."""
        self._interrupted.set()
        with self._buf_lock:
            self._play_buf.clear()
            self._captions.clear()
            self._current = None
            self._pos     = 0
        SPEAKING_TEXT[0] = ""
        while not self._synth_q.empty():
            try:
                self._synth_q.get_nowait()
            except stdlib_queue.Empty:
                break

    async def shutdown(self) -> None:
        self.interrupt()
        self._synth_q.put(None)
        if self._synth_thread:
            await asyncio.to_thread(self._synth_thread.join, 5.0)
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
