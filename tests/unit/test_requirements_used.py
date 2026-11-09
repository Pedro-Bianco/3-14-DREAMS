"""Toda dependência do núcleo é usada pelo código.

Em 2026-10-16 havia ~20 pacotes instalados sem nenhum import (PyTorch incluído).
"""

import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

# nome no requirements -> nome do import
IMPORTS_AS = {
    "faster-whisper": "faster_whisper", "kokoro-onnx": "kokoro_onnx", "pocket-tts": "pocket_tts", "pyopengl": "OpenGL", "espeakng-loader": "espeakng_loader", "qdrant-client": "qdrant_client",
    "opencv-python": "cv2", "pillow": "PIL", "langchain-text-splitters": "langchain_text_splitters",
    "langchain-experimental": "langchain_experimental",
}
# Fixados de propósito sem import direto — cada um com o motivo.
INDIRECT = {
    "ctranslate2": "motor do faster-whisper; versão fixada pela compatibilidade CUDA",
    "onnxruntime": "motor do Kokoro e do fastembed; fixado para builds reprodutíveis",
    "torch": "motor do pocket-tts (voz padrão); fixado na versão para CPU testada",
    "tiktoken": "usado pelo TokenTextSplitter do langchain (modo 'token' da aba KB)",
    "tzdata": "dados de fuso que o zoneinfo lê no Windows (agenda); não tem import",
    "openvino": "motor do openvino-genai (reconhecimento na placa Intel); fixado na versão medida",
    "openvino-tokenizers": "extensão que o openvino-genai carrega para o texto do Whisper; mesma versão",
}


def _packages(file: Path) -> list[str]:
    names = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-r"):
            names.append(re.split(r"[=<>~!]", line)[0].strip().lower())
    return names


def test_cada_pacote_do_nucleo_e_importado():
    code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT_DIR / "pidreams").rglob("*.py"))
    unused = []
    for package in _packages(ROOT_DIR / "requirements" / "core.txt"):
        if package in INDIRECT:
            continue
        module = IMPORTS_AS.get(package, package.replace("-", "_"))
        if not re.search(rf"^\s*(import|from)\s+{re.escape(module)}\b", code, re.M):
            unused.append(package)
    assert not unused, f"pacotes sem import no núcleo: {unused}"
