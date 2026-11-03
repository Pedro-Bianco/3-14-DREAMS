"""Grabs a webcam frame and asks a vision model (VLM) about it.

The main model (qwen2.5:14b) cannot see. Instead of replacing it, vision becomes a
tool: the VLM looks at the photo and returns TEXT, and that text is what the 14b reads.

Memory: the 14b and the VLM do not fit together (neither in the Arc B580's VRAM nor in
the free RAM when Ollama runs on CPU), and letting Ollama decide risks a failed load
or spilling over. So the swap is explicit: unload the 14b, run the VLM with
keep_alive=0, and the 14b comes back on the agent's next call.
"""

import time

import cv2
import ollama

from pidreams.core.config import CONFIG

# Instruction in the system message and the PLAIN question in the user one. With
# everything in the user message ("...instructions... Pergunta: X") the first vision model just echoed the question.
_VISION_SYSTEM = (
    "Você descreve fotos tiradas agora pela webcam do usuário, em português do "
    "Brasil, de forma objetiva. Diga só o que realmente aparece na imagem; se algo "
    "estiver borrado, escuro ou fora de quadro, diga isso em vez de adivinhar."
)

# Sent along with the result: in testing, faced with a useless description, the 14b
# made up the text of a paper it never saw.
_AGENT_NOTICE = (
    "Repasse ao usuário SOMENTE o que está descrito acima. Não acrescente objetos, "
    "textos ou detalhes que não estejam aí."
)


def _normalized(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def capture_jpeg() -> bytes:
    """Uses the live-video frame (the same one the panel shows). Without the video
    running, opens the camera, grabs one frame and releases it right away."""
    from pidreams.camera.stream import STREAM

    frame = STREAM.snapshot() if STREAM.running else None
    if frame is None:
        frame = _capture_once()
    return _encode(frame)


def _capture_once():
    # CAP_DSHOW opens much faster on Windows than the default backend (MSMF).
    cap = cv2.VideoCapture(CONFIG.camera_index, cv2.CAP_DSHOW)
    try:
        if not cap.isOpened():
            raise RuntimeError(
                f"não consegui abrir a câmera {CONFIG.camera_index} "
                "(outro programa usando, ou permissão de câmera negada no Windows)"
            )
        # The first frames come out dark while auto exposure settles.
        frame = None
        for _ in range(max(1, CONFIG.camera_warmup_frames)):
            ok, f = cap.read()
            if ok:
                frame = f
        if frame is None:
            raise RuntimeError("a câmera abriu mas não entregou nenhuma imagem")
    finally:
        cap.release()
    return frame


def _encode(frame) -> bytes:
    h, w = frame.shape[:2]
    scale = CONFIG.camera_max_side / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("falha ao codificar a imagem")
    return jpg.tobytes()


def _loaded(client: ollama.Client) -> set[str]:
    try:
        return {m.model for m in client.ps().models}
    except Exception:
        return set()


def _wait_exit(client: ollama.Client, model: str, limit_s: float = 30.0) -> None:
    """keep_alive=0 answers BEFORE the memory is given back. Without this wait the next
    model tried to load while the previous one still held RAM/VRAM and Ollama refused
    ('memory layout cannot be allocated') — measured both ways: the VLM going in and
    the 14b coming back."""
    target = model if ":" in model else f"{model}:latest"
    end = time.monotonic() + limit_s
    while target in _loaded(client) and time.monotonic() < end:
        time.sleep(0.3)
    time.sleep(0.5)   # the runner process leaves `ps` a moment before freeing everything


def _free_main_model(client: ollama.Client) -> None:
    try:
        client.generate(model=CONFIG.ollama_model, keep_alive=0)
    except Exception:
        pass   # if it was not loaded, great
    _wait_exit(client, CONFIG.ollama_model)


def look_camera(question: str) -> str:
    try:
        jpg = capture_jpeg()
    except Exception as e:
        return f"[Erro na câmera] {e}"

    client = ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s)
    if CONFIG.vision_swap:
        _free_main_model(client)
        options = {"num_ctx": CONFIG.vision_num_ctx}
        keep_alive = 0        # leaves as soon as it answers, giving room back to the 14b
    else:
        # The VLM stays in RAM (CPU) next to the 14b in VRAM. num_gpu=0 keeps Ollama
        # from trying the GPU and, short on room, evicting the 14b.
        options = {"num_ctx": CONFIG.vision_num_ctx, "num_gpu": 0}
        keep_alive = CONFIG.vision_keep_alive
    try:
        resp = client.chat(
            model=CONFIG.vision_model,
            think=False,          # Qwen3 models may reason first: slower, and the reasoning is not wanted
            messages=[
                {"role": "system", "content": _VISION_SYSTEM},
                {"role": "user", "content": question, "images": [jpg]},
            ],
            options=options,
            keep_alive=keep_alive,
        )
    except ollama.ResponseError as e:
        if "not found" in str(e).lower():
            return (f"[Erro] O modelo de visão '{CONFIG.vision_model}' não está instalado. "
                    f"Rode: ollama pull {CONFIG.vision_model}")
        return f"[Erro no modelo de visão] {e}"
    except Exception as e:
        return f"[Erro no modelo de visão] {e}"
    finally:
        if CONFIG.vision_swap:
            # The 14b reloads right after to read this result.
            _wait_exit(client, CONFIG.vision_model)

    text = (resp.message.content or "").strip()
    if not text or _normalized(text) == _normalized(question):
        return ("[Câmera] O modelo de visão não conseguiu analisar a imagem. "
                "Diga ao usuário que não conseguiu ver — NÃO invente o que haveria nela.")
    return f"[O que a câmera mostra agora]\n{text}\n\n{_AGENT_NOTICE}"
