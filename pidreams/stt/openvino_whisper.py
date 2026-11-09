"""Whisper large-v3-turbo on an Intel GPU (Arc or integrated) through OpenVINO GenAI.

Measured on an Arc B580 (2026-11-09, same audio for both): 0.06-0.17 s per sentence against
1.2-1.6 s for "small" on the CPU, more words right with background talk (88% vs 80%), "PI" heard in
18 of 20 calls with the spellings in agent/wake_name.py, no false call. About 1 GB of GPU memory
next to the 5.4 GB conversation model. On the CPU it took 3.7 s, so CPUs keep "small".

No hotwords here: with the name as a hint it wrote "PI" for 16 of 60 pieces of other people's talk.
Model published by Intel (Apache-2.0), converted from OpenAI's Whisper (MIT)."""

import logging
from pathlib import Path

import numpy as np

from pidreams.core import paths

log = logging.getLogger(__name__)

MODEL_ID = "OpenVINO/whisper-large-v3-turbo-int8-ov"
MODEL_SIZE = 830 * 1024 * 1024


def model_folder() -> Path:
    return paths.models_dir("openvino") / MODEL_ID.split("/")[1]


def present() -> bool:
    folder = model_folder()
    return all((folder / f).is_file() for f in ("openvino_encoder_model.bin", "openvino_decoder_model.bin",
                                                "openvino_tokenizer.xml", "openvino_detokenizer.xml"))


def intel_gpu(gpu_name: str | None) -> bool:
    return "intel" in (gpu_name or "").lower()


class OpenVinoWhisper:
    """Loads on the GPU (~9 s, once). Raises when the GPU or the driver cannot run it: the caller
    falls back to the CPU model."""

    def __init__(self):
        import openvino_genai

        self._pipe = openvino_genai.WhisperPipeline(str(model_folder()), "GPU")
        self._pipe.generate(np.zeros(16000, dtype=np.float32).tolist(), language="<|pt|>", task="transcribe")

    def transcribe(self, speech: np.ndarray) -> str:
        """speech: only the voiced parts (the turbo writes "E aí" or "Obrigado" over silence)."""
        return str(self._pipe.generate(speech.tolist(), language="<|pt|>", task="transcribe")).strip()
