"""PI dreams tuning constants + access to the user's preferences.

Two kinds, kept apart on purpose:
- tuning constants: the same for everyone, kept here next to the measurement that
  justifies them;
- user preferences (model, voice, city, Ollama...): come from settings.json and show
  up here as properties, so the rest of the code keeps reading CONFIG.<name>.
  Nothing here depends on who is using the computer.
"""

from pidreams.core import paths
from pidreams.core.settings import SETTINGS


def _recommendation():
    """Models for this machine's hardware (hardware/recommend.py)."""
    from pidreams.hardware.detect import current_profile
    from pidreams.hardware.recommend import recommend_models

    return recommend_models(current_profile(), SETTINGS.get("llm.model"))


class Config:
    # ── LLM ──────────────────────────────────────────────────────────────────
    # Model per hardware profile: pidreams/hardware/recommend.py.
    @property
    def ollama_model(self) -> str:
        return _recommendation().llm

    @property
    def ollama_host(self) -> str:
        return SETTINGS.get("ollama.host")

    # Context window. Whatever overflows is dropped from the START of the conversation.
    # VRAM cost: ~768 MiB of KV cache per 4096 tokens on this model.
    # Measured on an Arc B580 (12.2 GB):
    #   4096 -> 9.9 GB | 5120 -> 11 GB | 6144 -> 12 GB | 8192 -> 13 GB (spills over)
    # 2026-11-01: 8192. The tool schemas alone take ~1700 of the prompt's 2288 tokens (20 tools);
    # at 4096 a few turns overflowed, Ollama cut the start of the conversation (instructions
    # included) and the model answered in Chinese and stopped calling tools. Measured on the Arc
    # B580, Ollama 0.40.6, use_mmap=False: 9.5 GB, fully on the GPU, 34.8 tok/s (34.6 at 4096);
    # a 6191-token prompt also stayed on the GPU. (An older 5120 test spilled to the CPU, with an
    # older Ollama and mmap on.) Context is still saved elsewhere: smaller scrapes (3500 chars)
    # and a trimmed history (ollama_history_turns).
    ollama_num_ctx = 8192
    ollama_history_turns = 8   # turns kept in the panel conversation
    # ...and at most this many characters of them (~3.9 chars per token). Measured: system prompt +
    # tools ~2600 tokens, a turn with 5 document pieces and the profile ~1700, answer up to 512;
    # 8 long answers plus a web result reached 8418 of 8192 with the turn limit alone; with this
    # limit the same worst case is 6562 + 512 (86%).
    ollama_history_chars = 10000
    # How long the model stays resident on the GPU while idle. Ollama's default unloads
    # it within minutes, and reloading 10 GB is slow.
    ollama_keep_alive = "60m"
    # Temperature 0: the 14b went from 79.6% to 92.6% of explicit requests carried out,
    # and the evaluation became reproducible.
    ollama_temperature = 0
    # Reply cap: at temperature 0 qwen3:8b looped endlessly until the 600 s timeout.
    # 512 tokens fit a short e-mail or poem.
    ollama_num_predict = 512

    @property
    def ollama_options(self) -> dict:
        """Options for EVERY call to the chat model (agent and memory). Sent with
        think=False: qwen3:8b reasons by default, which is slow and leaks into speech.

        use_mmap=False: with the model fully on the GPU (Vulkan, Arc B580) the default mmap kept a
        resident 8.1 GB copy in RAM and loaded in 34 s; without it, 0.6 GB of RAM and 3.3 s, same
        answer (measured twice on 2026-11-01, qwen2.5:14b, Ollama 0.40.6)."""
        return {"num_ctx": self.ollama_num_ctx, "temperature": self.ollama_temperature,
                "num_predict": self.ollama_num_predict, "use_mmap": False}

    # Maximum wait for ONE Ollama call. Without a limit, a stuck server (accepts the
    # connection and never answers — happened on 2026-10-16) left the panel at
    # "Carregando modelo..." forever. On CPU the warmup 'oi' once took 2m08s, so the
    # default (600 s, settings.json) is generous.
    @property
    def ollama_timeout_s(self) -> float:
        return SETTINGS.get("ollama.timeout_s")

    # ── STT ──────────────────────────────────────────────────────────────────
    # tiny = faster (~0.3s), small = more accurate (~1s)
    whisper_model_size = "small"
    whisper_language = "pt"
    whisper_device = "cpu"
    whisper_compute_type = "int8"

    # ── Audio capture ────────────────────────────────────────────────────────
    sample_rate = 16000
    channels = 1
    # Windows default device. The user's choice (by name) comes from the settings.
    mic_device_index = None
    chunk_size = 1024
    silence_threshold = 0.01
    silence_duration_sec = 1.8
    max_recording_sec = 30.0
    # Interruption: threshold = N× the normal one; needs M consecutive chunks (~M*64ms)
    interrupt_threshold_factor = 2.5
    interrupt_min_chunks = 8  # ~512ms of sustained speech to interrupt

    # ── Weather ──────────────────────────────────────────────────────────────
    @property
    def weather_city(self) -> str:
        return SETTINGS.get("weather.city")   # empty = no weather

    # ── TTS (Piper — local, offline, PT-BR nativo) ───────────────────────────
    # Available voices: pt_BR-cadu-medium | pt_BR-faber-medium | pt_BR-jeff-medium
    @property
    def piper_model(self) -> str:
        return SETTINGS.get("voice.model")

    @property
    def piper_models_dir(self) -> str:
        """Voices downloaded by the user first; otherwise the voice shipped with the app."""
        downloaded = paths.models_dir("piper")
        if (downloaded / f"{self.piper_model}.onnx").is_file():
            return str(downloaded)
        return str(paths.install_dir() / "models" / "piper")

    @property
    def piper_length_scale(self) -> float:
        return SETTINGS.get("voice.length_scale")   # >1 = slower, <1 = faster

    piper_noise_scale = 0.667  # pitch variation (0 = robotic, 1 = expressive)
    piper_noise_w = 0.8        # phoneme duration variation

    # ── LTM — long-term memory (embedded Qdrant + FastEmbed) ─────────────────
    @property
    def qdrant_path(self) -> str:
        return str(paths.qdrant_dir())

    ltm_embedding_model = "intfloat/multilingual-e5-large"
    ltm_top_k = 3
    # e5 scores sit in a narrow band: measured 2026-10-31, the right memory 0.80-0.84 and the best
    # unrelated one up to 0.83, so no threshold separates them. Recall is in practice "the 3 closest";
    # the floor only drops junk.
    ltm_score_min = 0.55
    ltm_smart_update = True       # updates contradicted memories through the LLM
    ltm_update_threshold = 0.72   # floor of the update zone (0.72–0.89)
    # LTM reflection: instead of looking only at the last question/answer pair, the
    # extractor gets a window of the conversation every N turns. Two isolated turns say
    # nothing ('sim, é isso') and would still run the LLM every time, competing for the
    # GPU with the reply to the user.
    ltm_reflect_every = 4         # reflects every N turns
    ltm_reflect_window = 16       # messages sent to the extractor
    ltm_exit_wait_s = 30          # on closing, waits this long for the last reflection to be stored

    # ── KB — knowledge base (a collection separate from the LTM) ─────────────
    kb_top_k = 5
    # Gate on the best piece, DBSF scale (meaning + exact word). Measured 2026-10-31 on two bases:
    # questions about the documents had a best piece of 1.18-2.01 and the right piece always in the
    # top 3; unrelated questions 0.67-1.37. No value separates both bases, so the gate only keeps out
    # most unrelated questions and the prompt tells the model to ignore pieces that do not fit.
    kb_score_min = 1.25
    kb_chunk_size = 8      # sentences (sentence mode) or characters (other modes)
    # 1 sentence shared between pieces. With 2, the text was embedded 1.33x and a 100-page PDF took
    # 129 s; with 1, 105 s (2026-10-31), search and citation unchanged (12/13, codes 3/3, 13/13).
    kb_chunk_overlap = 1

    # ── Camera — ver_camera tool (CÂMERA button, off by default) ─────────────
    # The model's license must allow everyday use: Qwen3-VL is Apache-2.0. Measured on 2026-11-03 on
    # CPU (9 photos: text, price, list, tilted card, counting, colors, a dark frame):
    #   qwen3-vl:2b -> 9/9, ~24 s per photo, 1.8 GB   ← chosen
    #   qwen3-vl:4b -> 9/9, ~37 s per photo, 3.3 GB
    @property
    def vision_model(self) -> str:
        return _recommendation().vision

    # With the LLM in VRAM and the VLM in RAM both fit at once: without swapping, the
    # first photo dropped from ~79 s (+5 s reloading the LLM) to ~22 s, and later ones
    # within vision_keep_alive skip the load. Without a GPU the RAM can't hold both, and
    # the recommendation turns swapping on by itself (hardware/recommend.py).
    @property
    def vision_swap(self) -> bool:
        return _recommendation().vision_swap

    vision_keep_alive = "15m"
    vision_num_ctx = 4096
    camera_index = 0           # 0 = first Windows webcam
    camera_max_side = 768      # longest side of the frame sent (px); more = more tokens
    camera_warmup_frames = 8   # frames dropped while the exposure settles


CONFIG = Config()
