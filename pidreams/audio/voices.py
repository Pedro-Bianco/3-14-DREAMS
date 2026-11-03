"""Available Piper voices: the ones downloaded by the user and the ones shipped with the app."""

from pathlib import Path

from pidreams.core import paths


def folders() -> list[Path]:
    return [paths.models_dir("piper"), paths.install_dir() / "models" / "piper"]


def list_items() -> dict[str, Path]:
    """voice name -> .onnx file (the first folder found wins)."""
    voices: dict[str, Path] = {}
    for folder in folders():
        for onnx in sorted(folder.glob("*.onnx")):
            if onnx.with_suffix(".onnx.json").is_file():
                voices.setdefault(onnx.stem, onnx)
    return voices
