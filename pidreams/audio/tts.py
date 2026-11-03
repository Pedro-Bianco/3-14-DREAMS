import logging
import re
import asyncio
import threading
import queue as stdlib_queue
import collections
import numpy as np
import sounddevice as sd
from num2words import num2words
from piper import PiperVoice
from piper.config import SynthesisConfig
from pidreams.audio import voices
from pidreams.core.config import CONFIG
from pidreams.core.settings import SETTINGS
from pidreams.core.text import remove_emojis

log = logging.getLogger(__name__)

_BLOCKSIZE = 2048

# RMS of the block playing right now (0 = silence). Written by the audio callback,
# read by the panel's face to open the mouth in time with the syllables.
VOICE_LEVEL: list[float] = [0.0]
# Sentence whose audio is playing right now ("" = silence). Set by the audio callback the
# moment the sentence starts sounding, so the window's caption follows the voice, not the text.
SPEAKING_TEXT: list[str] = [""]

# Normalization — compiled patterns
_MARKDOWN_RE = re.compile(r'(\*{1,3}|_{1,3}|~~|`+|#{1,6})\s*')
_NUM_RE = re.compile(r'\b\d+(?:[.,]\d+)?\b')


def _num_to_words(m: re.Match) -> str:
    raw = m.group(0)
    try:
        if ',' in raw or '.' in raw:
            return num2words(float(raw.replace(',', '.')), lang='pt_BR')
        return num2words(int(raw), lang='pt_BR')
    except Exception:
        return raw


def _normalize(text: str) -> str:
    text = _MARKDOWN_RE.sub(' ', text)
    text = remove_emojis(text)
    text = _NUM_RE.sub(_num_to_words, text)
    return re.sub(r'\s+', ' ', text).strip()


class TTSEngine:
    """
    TTS local usando Piper PT-BR (ONNX, CPU).

    Arquitetura de dupla thread:
      - synth thread: converte texto → PCM via Piper (bloqueante)
      - stream callback: consome o deque em tempo real (zero gap entre frases)
    """

    BLOCKSIZE = _BLOCKSIZE

    def __init__(self, out_device_ref=None, volume_ref=None):
        self._out_device_ref = out_device_ref if out_device_ref is not None else [None]
        self._volume_ref     = volume_ref if volume_ref is not None else [1.0]

        self._voice:       PiperVoice | None = None
        self._sample_rate: int               = 22050

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
        self._load_voice(CONFIG.piper_model)
        # Changing the voice in the settings applies to the next sentence, without restarting.
        SETTINGS.subscribe(lambda st: self._switch_voice(st.get("voice.model")))

        self._synth_thread = threading.Thread(
            target=self._synth_loop, daemon=True, name="tts-synth")
        self._synth_thread.start()

    def _load_voice(self, name: str) -> None:
        onnx = voices.list_items().get(name)
        if onnx is None:
            raise FileNotFoundError(f"Voz Piper '{name}' não encontrada em {voices.folders()}")
        log.info(f"[TTS] Loading Piper '{name}'...")
        voice = PiperVoice.load(str(onnx), use_cuda=False)
        if self._voice is not None and voice.config.sample_rate != self._sample_rate:
            self._stream_device = object()      # forces the stream to be recreated on the next speech
        self._voice, self._voice_name = voice, name
        self._sample_rate = voice.config.sample_rate
        log.info(f"[TTS] Piper ready — {self._sample_rate} Hz.")

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

                syn_cfg = SynthesisConfig(
                    length_scale=CONFIG.piper_length_scale,
                    noise_scale=CONFIG.piper_noise_scale,
                    noise_w_scale=CONFIG.piper_noise_w,
                )
                for audio_chunk in self._voice.synthesize(text, syn_config=syn_cfg):
                    if self._interrupted.is_set():
                        break
                    chunk = audio_chunk.audio_float_array
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
