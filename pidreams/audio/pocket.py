"""The default voice: Pocket TTS (Kyutai, CC-BY-4.0 weights) speaking Portuguese with a voice made
for PI dreams.

The voice was designed from a text description with VoxCPM2 (Apache-2.0) — no recording of any
person — and turned into a Pocket TTS voice state once (pidreams/assets/voices). The app only needs
the public weights, which cannot clone voices, plus that state file. Measured on 2026-11-04 on the
CPU: first audio ~0.1 s after the sentence starts, 3.8x faster than real time.
"""

from collections.abc import Iterator
from pathlib import Path
import threading

import numpy as np

from pidreams.core import paths

RATE = 24000                       # Pocket TTS (Mimi) always outputs 24 kHz
VOICES_DIR = Path(__file__).resolve().parent.parent / "assets" / "voices"


def _config_file() -> Path:
    """The packaged Portuguese config, pointing at the files the app downloaded instead of at the
    Hugging Face repositories (so nothing is fetched while the app runs)."""
    from pocket_tts.utils.config import CONFIGS_DIR

    folder = paths.models_dir("pocket")
    lines = []
    for line in (CONFIGS_DIR / "portuguese.yaml").read_text(encoding="utf-8").splitlines():
        key = line.strip().split(":", 1)[0]
        if key == "weights_path_without_voice_cloning":
            continue
        if line.startswith("weights_path:"):
            line = f"weights_path: {(folder / 'model.safetensors').as_posix()}"
        elif key == "tokenizer_path":
            line = line.split("tokenizer_path:")[0] + f"tokenizer_path: {(folder / 'tokenizer.json').as_posix()}"
        lines.append(line)
    target = folder / "portuguese.yaml"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


class PocketVoice:
    def __init__(self, voice_file: str):
        from pocket_tts.models.tts_model import TTSModel   # imports PyTorch: only when this voice is used

        self._model = TTSModel.load_model(config=str(_config_file()))
        self._state = self._model.get_state_for_audio_prompt(str(VOICES_DIR / voice_file))

    def stream(self, text: str, stop: threading.Event | None = None) -> Iterator[np.ndarray]:
        """float32 chunks of the sentence as they are generated (the voice state is copied, so
        every sentence starts from the same voice)."""
        for chunk in self._model.generate_audio_stream(model_state=self._state, text_to_generate=text,
                                                        stop=stop):
            yield chunk.numpy().astype(np.float32)
