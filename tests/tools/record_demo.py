"""Records docs/demo.mp4: the app used from start to finish, with its own sound, on a FICTITIOUS profile.

    python -m tests.tools.record_demo [--out docs/demo.mp4]

- Data: a separate folder (LOCALAPPDATA redirected) with an invented user, memories, a reminder, a
  routine and a document; the downloaded models are reused through a folder junction. The real
  profile is never read.
- Requests are typed in voice mode, so the app answers out loud (no microphone needed).
- Picture: only the app's window. Sound: only what the app itself plays (voice and startup sound),
  tapped from its audio output — nothing else from the PC.
Close the real app first (the data folders differ, but the models and the GPU are shared).
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REAL_MODELS = Path(os.environ["LOCALAPPDATA"]) / "PIDreams" / "models"
DEMO_BASE = Path(tempfile.gettempdir()) / "pidreams-demo"
os.environ["LOCALAPPDATA"] = str(DEMO_BASE)          # before anything from pidreams is imported
sys.path.insert(0, str(ROOT))

FPS = 30
TODAY = time.strftime("%Y-%m-%d")

SETTINGS = {
    "first_run_done": True, "assistant_name": "PI dreams", "treatment": "Lucas", "appearance": "rosto",
    "weather": {"city": "Curitiba"},
    "resumo": {"ligado": True, "toda_vez": True, "clima": True, "agenda": False, "emails": False, "lembretes": True},
    # A common 1080p monitor, not the ultrawide: the video looks like the app in full screen.
    "window": {"geometry": "1920x1080+300+120", "zoomed": False},
    "voice": {"model": "kokoro-alex", "length_scale": 1.0, "effect": "forte", "wake_name": False},
    "privacy": {"log_speech": True},          # fictitious profile: the full log helps check the take
    "routines": [{"name": "apresentação", "steps": [
        {"type": "musica", "value": "pausar"},
        {"type": "falar", "value": "Modo apresentação ligado. Pausei a música e o palco é seu."}]}],
}
MEMORIES = [("O usuário se chama Lucas.", "perfil"), ("O usuário trabalha como designer de produto.", "perfil"),
            ("O usuário mora em Curitiba.", "perfil"), ("O cachorro do usuário se chama Biscoito.", "fato"),
            ("O usuário está aprendendo a tocar violão.", "fato"), ("O usuário prefere café sem açúcar.", "fato")]
DOCUMENT = """Roteiro da viagem a Lisboa — dezembro

Voos
O voo de ida sai de Guarulhos no dia 12 de dezembro, às 21h40, e chega a Lisboa no dia 13, às 11h20.
A volta é no dia 19 de dezembro, saindo de Lisboa às 13h05. Levar o passaporte e o seguro-viagem impresso.

Hospedagem
O hotel é a Casa do Largo, em Alfama, perto do Miradouro de Santa Luzia. O check-in é a partir das 15h e o
check-out até as 11h. Café da manhã incluso das 7h às 10h30. A reserva está no nome do Lucas.

Passeios
Dia 14: Torre de Belém e Mosteiro dos Jerónimos; provar o pastel de Belém.
Dia 15: Sintra, com o Palácio da Pena; trem saindo do Rossio às 9h.
Dia 16: Bairro Alto e LX Factory. Dia 17: Cascais, de trem pela linha da costa.

Orçamento
Hospedagem: 6 noites. Transporte: cartão Viva Viagem para metrô, elétrico 28 e trens.
Reservar o jantar de fado no dia 16, às 20h, em Alfama.
"""
# Each step: what is typed (None = nothing), the caption on screen, extra seconds to show the result,
# and an appearance to switch to before it.
SCRIPT = [
    dict(say="Qual é a capital da Austrália?", caption="Conversa por voz, com resposta em cerca de 1 segundo"),
    dict(say="Qual é o nome do meu cachorro?", caption="Memória: ele lembra de você entre as conversas"),
    dict(say="Me lembra de levar o Biscoito ao veterinário amanhã às 10h.", caption="Lembretes por voz"),
    dict(say="Que horas é o check-in do hotel em Lisboa?",
         caption="Responde com base nos seus documentos"),
    dict(say=None, caption="Quatro aparências, trocadas na hora", appearance="cerebro", linger=3.0),
    dict(say="Modo apresentação", caption="Rotinas: várias ações com uma frase", appearance="nucleo"),
    dict(say="Abre o monitoramento", caption="Monitoramento: globo 3D com satélites e terremotos", linger=7.0),
    dict(say="Mostra os aviões sobre São Paulo", caption="Aviões em tempo real", linger=6.0),
    dict(say="Fecha o monitoramento", caption="Tudo roda no seu PC: sem conta, sem nuvem, sem custo"),
]
INTRO_CAPTION = "PI dreams · assistente de voz que roda 100% no seu PC"
END_CARD = ("PI dreams", "Assistente de voz 100% local · grátis · código aberto",
            "github.com/Pedro-Bianco/3-14-DREAMS")
FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def prepare_profile() -> Path:
    data = DEMO_BASE / "PIDreams"
    if DEMO_BASE.exists():
        for junction in (data / "models", data / "cache" / "monitor"):                    # the junctions only
            subprocess.run(["cmd", "/c", "rmdir", str(junction)], capture_output=True)
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(DEMO_BASE)], capture_output=True)
    data.mkdir(parents=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(data / "models"), str(REAL_MODELS)], check=True,
                   capture_output=True)
    # Public data the Monitoramento downloads (orbits, quakes, radio list): reused so the globe is ready.
    (data / "cache").mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(data / "cache" / "monitor"),
                    str(REAL_MODELS.parent / "cache" / "monitor")], check=True, capture_output=True)
    (data / "settings.json").write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")
    (data / "lembretes.json").write_text(json.dumps({"lembretes": [
        {"id": 1, "texto": "regar as plantas", "data": TODAY, "hora": None, "criado": TODAY + "T08:00:00",
         "estado": "pendente"}]}, ensure_ascii=False), encoding="utf-8")
    doc = DEMO_BASE / "Viagem a Lisboa.txt"
    doc.write_text(DOCUMENT, encoding="utf-8")
    return doc


class AudioTap:
    """Copies every block the app plays (voice, startup sound) with the time it was played."""

    def __init__(self):
        self.blocks: list[tuple[float, int, "np.ndarray"]] = []

    def install(self):
        import sounddevice as sd

        tap = self

        class TeeStream(sd.OutputStream):
            def __init__(self, *args, callback=None, **kwargs):
                rate = kwargs.get("samplerate")

                def tee(outdata, frames, time_info, status):
                    callback(outdata, frames, time_info, status)
                    tap.blocks.append((time.perf_counter(), rate, id(self), outdata.copy()))
                super().__init__(*args, callback=tee, **kwargs)

        # The microphone hears only silence: in voice mode the PI keeps listening between requests, and a
        # take answered room sound ("aqui do mercado pago") picked up by the real mic (2026-11-09).
        class SilentInput(sd.InputStream):
            def __init__(self, *args, callback=None, **kwargs):
                def mute(indata, frames, time_info, status):
                    callback(indata * 0, frames, time_info, status)
                super().__init__(*args, callback=mute if callback else None, **kwargs)

        sd.OutputStream = TeeStream
        sd.InputStream = SilentInput

    def render(self, t0: float, seconds: float, rate: int = 48000):
        import numpy as np
        from scipy.signal import resample_poly

        # Consecutive blocks of one stream are laid back to back and resampled as one run: placing each block
        # by its callback time (which jitters) and resampling it alone made clicks at every block edge, and
        # the voice sounded distorted (2026-11-09). A new run starts only after a real pause.
        # The voice stream stays open and plays silence between replies, so it is normally one run.
        runs: list[list] = []
        open_runs: dict[int, list] = {}                     # stream → [start, rate, blocks, samples laid]
        for at, src_rate, stream, block in self.blocks:
            run = open_runs.get(stream)
            if run is None or at - (run[0] + run[3] / src_rate) > 0.25:
                run = open_runs[stream] = [at, src_rate, [], 0]
                runs.append(run)
            run[2].append(block)
            run[3] += len(block)
        print(f"audio: {len(self.blocks)} blocks in {len(runs)} run(s)")
        out = np.zeros((int(seconds * rate) + rate, 2), dtype=np.float32)
        for at, src_rate, blocks, _ in runs:
            data = np.concatenate(blocks)
            stereo = data if data.shape[1] == 2 else np.repeat(data, 2, axis=1)
            f = Fraction(rate, int(src_rate))
            data = resample_poly(stereo, f.numerator, f.denominator, axis=0).astype(np.float32)
            i = int((at - t0) * rate)
            if i < 0:                                      # started before the recording: keep the rest
                data, i = data[-i:], 0
            if i < len(out):
                end = min(len(out), i + len(data))
                out[i:end] += data[:end - i]
        return np.clip(out[:int(seconds * rate)], -1, 1)


class ScreenRecorder:
    """Grabs only the window's rectangle at a steady FPS into an H.264 file (no sound yet). Grabbing (GDI)
    and encoding run on separate threads: together on one, a take had ~4 real frames per second."""

    def __init__(self, path: Path):
        self.path, self.bbox, self.frames = path, None, 0
        self.caption = INTRO_CAPTION
        self._stop = threading.Event()
        self._queue: "queue.Queue" = queue.Queue(maxsize=90)

    def start(self, bbox):
        self.bbox = bbox
        self.t0 = time.perf_counter()
        self._grab_thread = threading.Thread(target=self._grab_loop, daemon=True)
        self._encode_thread = threading.Thread(target=self._encode_loop, daemon=True)
        self._grab_thread.start()
        self._encode_thread.start()

    def _grab_loop(self):
        from tests.tools.screen_grab import Grabber

        x0, y0, x1, y1 = self.bbox
        self.w, self.h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
        grabber = Grabber(x0, y0, self.w, self.h)
        overlay_for, overlay = None, None
        n = 0
        while not self._stop.is_set():
            if self.caption != overlay_for:
                overlay_for, overlay = self.caption, caption_overlay(self.w, self.h, self.caption)
            frame = grabber.grab()
            if overlay is not None:
                (ya, yb, xa, xb), rgb, alpha = overlay
                frame[ya:yb, xa:xb] = (frame[ya:yb, xa:xb] * (1 - alpha) + rgb * alpha).astype("uint8")
            self._queue.put((int((time.perf_counter() - self.t0) * FPS), frame))
            n += 1
            time.sleep(max(0.0, n / FPS - (time.perf_counter() - self.t0)))
        grabber.close()
        self._queue.put(None)

    def _encode_loop(self):
        import av
        import numpy as np

        out, stream, last = None, None, None
        while True:
            item = self._queue.get()
            if item is None:
                break
            index, frame = item
            if out is None:
                out = av.open(str(self.path), "w")
                stream = out.add_stream("libx264", rate=FPS)
                stream.width, stream.height, stream.pix_fmt = frame.shape[1], frame.shape[0], "yuv420p"
                stream.options = {"crf": "19", "preset": "fast"}
            last = av.VideoFrame.from_ndarray(frame, format="rgb24")
            while self.frames <= index:                       # a late grab repeats the frame: steady clock
                for packet in stream.encode(last):
                    out.mux(packet)
                self.frames += 1
        card = av.VideoFrame.from_ndarray(np.asarray(end_card(stream.width, stream.height)), format="rgb24")
        for _ in range(int(FPS * 4)):                             # closing card, 4 s
            for packet in stream.encode(card):
                out.mux(packet)
            self.frames += 1
        for packet in stream.encode():
            out.mux(packet)
        out.close()

    def stop(self) -> float:
        self._stop.set()
        self._grab_thread.join()
        self._encode_thread.join()
        return self.frames / FPS


def _font(name: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(FONTS / name), size)


def caption_overlay(w: int, h: int, text: str):
    """The HUD lower third (dark glass box, cyan bar, white text), drawn once per caption: returns the box
    (rows, cols), its RGB and its alpha, blended onto every frame by the grabber."""
    import numpy as np
    from PIL import Image, ImageDraw

    if not text:
        return None
    font = _font("seguisb.ttf", max(18, h // 34))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = probe.textlength(text, font=font)
    pad, bar = h // 60, max(4, h // 180)
    box_w, box_h = int(tw + 3 * pad + bar), int(font.size * 1.9)
    layer = Image.new("RGBA", (box_w + 2, box_h + 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle((0, 0, box_w, box_h), radius=pad, fill=(7, 11, 31, 225), outline=(42, 58, 122, 255), width=1)
    draw.rectangle((pad, pad, pad + bar, box_h - pad), fill=(34, 211, 238, 255))
    draw.text((2 * pad + bar, box_h / 2), text, font=font, fill=(232, 238, 255, 255), anchor="lm")
    rgba = np.asarray(layer).astype(np.float32)
    x, y = (w - layer.width) // 2, h - h // 18 - layer.height                # centered, above the footer
    return (y, y + layer.height, x, x + layer.width), rgba[:, :, :3], rgba[:, :, 3:] / 255


def end_card(w: int, h: int):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), (7, 11, 31))
    draw = ImageDraw.Draw(img)
    for r, color in ((h * 0.36, (15, 23, 56)), (h * 0.30, (22, 32, 74))):         # soft rings behind
        draw.ellipse((w / 2 - r, h * 0.42 - r, w / 2 + r, h * 0.42 + r), outline=color, width=max(2, h // 200))
    title, subtitle, link = END_CARD
    draw.text((w / 2, h * 0.38), title, font=_font("bahnschrift.ttf", h // 8), fill=(34, 211, 238), anchor="mm")
    draw.text((w / 2, h * 0.52), subtitle, font=_font("segoeui.ttf", h // 26), fill=(232, 238, 255), anchor="mm")
    draw.text((w / 2, h * 0.62), link, font=_font("seguisb.ttf", h // 30), fill=(167, 139, 250), anchor="mm")
    return img


def mux(video: Path, audio, out_path: Path, rate: int = 48000):
    import av

    src = av.open(str(video))
    out = av.open(str(out_path), "w")
    vin = src.streams.video[0]
    vout = out.add_stream_from_template(vin)
    aout = out.add_stream("aac", rate=rate, layout="stereo")
    for packet in src.demux(vin):
        if packet.dts is None:
            continue
        packet.stream = vout
        out.mux(packet)
    pcm = (audio * 32767).astype("int16")
    for i in range(0, len(pcm), 1024):
        # s16 is packed: one row of interleaved L R L R. Passing the transposed block (all L, then all R)
        # garbled every 1024 samples, which made the voice sound distorted (2026-11-09).
        frame = av.AudioFrame.from_ndarray(pcm[i:i + 1024].reshape(1, -1), format="s16", layout="stereo")
        frame.sample_rate = rate
        for packet in aout.encode(frame):
            out.mux(packet)
    for packet in aout.encode():
        out.mux(packet)
    out.close()
    src.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "demo.mp4"))
    out_path = Path(parser.parse_args().out)

    doc = prepare_profile()
    tap = AudioTap()
    tap.install()

    from pidreams.audio import tts as tts_module
    from pidreams.core import paths
    from pidreams.ui import theme

    theme.enable_dpi_awareness()
    paths.ensure_dirs()
    from pidreams.core import logging_setup
    logging_setup.setup()
    from pidreams.ui.main_window import AgentApp

    app = AgentApp()
    app.root.attributes("-topmost", True)
    # The Monitoramento opening draws into its own borderless window over the app: with the app topmost it
    # opened behind it and the take showed a black globe for 1.8 s (2026-11-09).
    cover_for_intro = app._cover_for_intro

    def cover_on_top():
        cover_for_intro()
        app._cover.attributes("-topmost", True)
    app._cover_for_intro = cover_on_top
    raw = Path(tempfile.gettempdir()) / "pidreams-demo-video.mp4"
    recorder = ScreenRecorder(raw)

    def idle_for(seconds: float) -> None:
        quiet_since = None
        while True:
            # Idle = listening again: a tool call (saving a reminder) leaves a gap with no words yet, and
            # typing the next request there cut the reply short in a take.
            busy = (app._agent_working or bool(tts_module.SPEAKING_TEXT[0]) or not app._text_input.empty()
                    or app._appearance_state != "listening")
            now = time.time()
            quiet_since = None if busy else (quiet_since or now)
            if quiet_since and now - quiet_since >= seconds:
                return
            time.sleep(0.2)

    def drive():
        app._stores_ready.wait()
        for text, kind in MEMORIES:
            app._ltm_store.upsert(text, kind=kind)
        app._kb_store.ingest_document(doc)
        app.root.after(0, app._mem_show_all)
        app.root.after(0, app._kb_refresh)
        while app._boot is not None:
            time.sleep(0.2)
        recorder.caption = "Resumo do dia ao abrir: clima e lembretes"
        time.sleep(1.0)
        idle_for(2.5)                                  # the briefing
        for step in SCRIPT:
            recorder.caption = step["caption"]
            if step.get("appearance"):
                app.root.after(0, lambda a=step["appearance"]: (app._switch_appearance(a)))
                time.sleep(1.2)
            if step["say"]:
                app._text_input.put(step["say"])
                time.sleep(1.0)
                idle_for(1.2)
            time.sleep(step.get("linger", 0.0))
        recorder.caption = ""
        time.sleep(1.5)
        seconds = recorder.stop()
        print(f"video: {seconds:.1f} s, {recorder.frames} frames")
        audio = tap.render(recorder.t0, seconds)
        mux(raw, audio, out_path)
        print("saved", out_path, f"{out_path.stat().st_size / 1e6:.1f} MB")
        app.root.after(0, app._quit)

    def begin():
        app.root.update()
        x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
        recorder.start((x, y, x + app.root.winfo_width(), y + app.root.winfo_height()))
        threading.Thread(target=drive, daemon=True).start()

    # The recording starts with the window, so the startup animation and sound are in it.
    app.root.after(0, begin)
    app.run()


if __name__ == "__main__":
    main()
