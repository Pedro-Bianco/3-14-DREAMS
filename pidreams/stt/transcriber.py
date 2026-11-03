import logging
import unicodedata

import numpy as np
from faster_whisper import WhisperModel
from pidreams.core import paths
from pidreams.core.config import CONFIG

log = logging.getLogger(__name__)


# Whisper was trained on a lot of YouTube video: faced with noise or silence it
# "hears" video outros. Each one became a request to the LLM and held the CPU for
# up to 1 min (seen on 2026-10-16: "se inscreva no canal e se inscreva no canal
# para ver mais vídeos"). Compared without accents and in lowercase.
_GHOST_PHRASES = (
    "inscreva no canal",
    "inscrevam no canal",
    "inscreva-se no canal",
    "inscrevam-se no canal",
    "se inscreva",
    "ative o sininho",
    "ativem o sininho",
    "deixe seu like",
    "deixe o seu like",
    "deixa o like",
    "obrigado por assistir",
    "obrigada por assistir",
    "ate o proximo video",
    "ate a proxima",
    "legendas pela comunidade",
    "amara.org",
    "legenda por",
    "legendado por",
    "transcricao por",
    "e isso ai pessoal",
    "tchau tchau",
)


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _ghost(text: str) -> bool:
    t = _strip_accents(text)
    return any(f in t for f in _GHOST_PHRASES)


def _device() -> tuple[str, str]:
    """NVIDIA GPU when the profile and the CUDA DLLs allow it; otherwise CPU int8."""
    from pidreams.hardware import cuda
    from pidreams.hardware.detect import current_profile

    if current_profile().backend_detected == "nvidia" and cuda.prepare_runtime():
        return "cuda", "float16"
    return CONFIG.whisper_device, CONFIG.whisper_compute_type


class Transcriber:
    """
    Transcribes audio with faster-whisper (CTranslate2).
    Supports int8/float16 quantization, much faster than openai-whisper.
    """

    def __init__(self):
        device, compute = _device()
        log.info(f"[STT] Loading Whisper '{CONFIG.whisper_model_size}' "
                 f"(device={device}, compute={compute})...")
        self.model = WhisperModel(
            CONFIG.whisper_model_size,
            device=device,
            compute_type=compute,
            download_root=str(paths.models_dir("whisper")),
        )
        log.info("[STT] Model loaded.")

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribes a float32 16 kHz mono audio array.
        Returns the transcribed text, or an empty string if nothing was detected.
        """
        segments, info = self.model.transcribe(
            audio,
            language=CONFIG.whisper_language,
            beam_size=5,
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
            temperature=0,
            # Silero VAD: cuts what is not voice BEFORE Whisper. Fan noise,
            # keyboard or breathing no longer reach it.
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
        )

        parts = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            # Whisper's own heuristics for "this was not speech":
            # probably silence AND low confidence, or text that repeats itself.
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.7:
                log.warning(f"[STT] dropped (no speech): {text!r}")
                continue
            if seg.compression_ratio > 2.4:
                log.warning(f"[STT] dropped (repetitive): {text!r}")
                continue
            if _ghost(text):
                log.warning(f"[STT] dropped (ghost phrase): {text!r}")
                continue
            parts.append(text)
        result = " ".join(parts).strip()
        # Numbers only, never the audio: enough to tell whether the drop was
        # silence, a quiet voice or the agent's own voice from the speaker.
        log.info("[STT] audio %.1fs, rms %.4f, peak %.3f, speech detected %.1fs → %s",
                 info.duration, float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0,
                 float(np.abs(audio).max()) if len(audio) else 0.0,
                 info.duration_after_vad, repr(result[:60]) if result else "(empty)")
        return result
