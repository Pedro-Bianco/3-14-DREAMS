"""Models that fit the detected hardware.

Measured ranges: qwen2.5:14b takes ~9 GB of VRAM. On a 12 GB card it generated 38 tok/s on
2026-10-16, but on 2026-11-04 (driver 32.0.101.9033, with Windows and the usual apps holding
~2.5 GB of the card) only 5.1 GB fit and the rest spilled to shared system memory: 2.6 tok/s and
~25 s before the first word; after a reboot it was back to 34 tok/s whole on the card (the driver
had stopped giving one process more than ~6 GB, even an 8 GB PyTorch test). qwen3:8b (5.7 GB) fits
whole either way: 46-58 tok/s, and the first spoken word comes sooner. So for chat the 14b is only
recommended from 16 GB. The vision model runs on the CPU (see config.py). Tool choice at
temperature 0, tuning / validation
evaluation: qwen2.5:14b 94.7% / 95.6%;
qwen3:8b 94.0% / 95.6% (qwen2.5:7b sat at 91% and got the camera right 2 times in 5);
qwen3:4b-instruct 92.5% / 95.6% (qwen2.5:3b, 81%). Use the "-instruct": plain qwen3:4b
always reasons, takes ~19 s and writes its reasoning into the reply. Only the chat model can be
chosen by the user — vision and Whisper always follow the hardware.

Deep research is the one place where a stronger model is worth the wait (it runs for minutes in
the background, nobody is waiting on a spoken reply): qwen2.5:14b with any GPU, even where it
spills out of the card, and qwen3:8b on CPU.
"""

from dataclasses import dataclass

from pidreams.hardware.detect import HardwareProfile

GB = 1024**3


@dataclass
class Recommendation:
    llm: str
    research_llm: str            # deep research only: stronger, slower
    vision: str
    stt_device: str              # "cuda" | "cpu" (the CUDA layer confirms it works)
    vision_swap: bool            # unload the LLM before the photo (only without a GPU)
    reason: str


def recommend_models(profile: HardwareProfile, chosen_llm: str | None = None) -> Recommendation:
    vram = profile.vram_bytes or 0
    if profile.backend_detected == "cpu" or vram < 6 * GB:
        llm, reason_text = "qwen3:4b-instruct", "sem GPU dedicada: modelo pequeno para responder em CPU"
    elif vram < 16 * GB:
        llm, reason_text = "qwen3:8b", f"GPU com {vram / GB:.0f} GB: modelo médio (cabe inteiro na placa)"
    else:
        llm, reason_text = "qwen2.5:14b", f"GPU com {vram / GB:.0f} GB: modelo grande"
    if chosen_llm:
        llm, reason_text = chosen_llm, "escolhido nas configurações"
    research_llm = "qwen3:8b" if profile.backend_detected == "cpu" or vram < 6 * GB else "qwen2.5:14b"
    return Recommendation(
        llm=llm,
        research_llm=research_llm,
        vision="qwen3-vl:2b",
        stt_device="cuda" if profile.backend_detected == "nvidia" else "cpu",
        # On CPU, the LLM and the VLM compete for RAM: swap one for the other on each photo.
        vision_swap=profile.backend_detected == "cpu",
        reason=reason_text,
    )
