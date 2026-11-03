"""Models that fit the detected hardware.

Measured ranges: qwen2.5:14b takes 9.1 GB of VRAM and generates 38 tok/s on a 12 GB
GPU (Ollama 0.40.6); the vision model runs on the CPU (see config.py). Tool choice at temperature 0, tuning / validation
evaluation: qwen2.5:14b 94.7% / 95.6%;
qwen3:8b 94.0% / 95.6% (qwen2.5:7b sat at 91% and got the camera right 2 times in 5);
qwen3:4b-instruct 92.5% / 95.6% (qwen2.5:3b, 81%). Use the "-instruct": plain qwen3:4b
always reasons, takes ~19 s and writes its reasoning into the reply. Only the chat model can be
chosen by the user — vision and Whisper always follow the hardware.
"""

from dataclasses import dataclass

from pidreams.hardware.detect import HardwareProfile

GB = 1024**3


@dataclass
class Recommendation:
    llm: str
    vision: str
    stt_device: str              # "cuda" | "cpu" (the CUDA layer confirms it works)
    vision_swap: bool            # unload the LLM before the photo (only without a GPU)
    reason: str


def recommend_models(profile: HardwareProfile, chosen_llm: str | None = None) -> Recommendation:
    vram = profile.vram_bytes or 0
    if profile.backend_detected == "cpu" or vram < 6 * GB:
        llm, reason_text = "qwen3:4b-instruct", "sem GPU dedicada: modelo pequeno para responder em CPU"
    elif vram < 12 * GB:
        llm, reason_text = "qwen3:8b", f"GPU com {vram / GB:.0f} GB: modelo médio"
    else:
        llm, reason_text = "qwen2.5:14b", f"GPU com {vram / GB:.0f} GB: modelo grande"
    if chosen_llm:
        llm, reason_text = chosen_llm, "escolhido nas configurações"
    return Recommendation(
        llm=llm,
        vision="qwen3-vl:2b",
        stt_device="cuda" if profile.backend_detected == "nvidia" else "cpu",
        # On CPU, the LLM and the VLM compete for RAM: swap one for the other on each photo.
        vision_swap=profile.backend_detected == "cpu",
        reason=reason_text,
    )
