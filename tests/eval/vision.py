"""Avaliação do modelo de visão (câmera) com imagens geradas por código, conteúdo fictício.

Pergunta como o PI pergunta (mesmo system prompt e opções de vision.py) e confere palavras-chave,
o tempo de cada foto e se a resposta saiu em português. A primeira foto inclui a carga do modelo.
Uso: python -m tests.eval.vision [modelo1,modelo2,...]
"""

import io
import statistics
import sys
import time

import ollama
from PIL import Image, ImageDraw, ImageFont

from pidreams.camera import vision
from pidreams.core.config import CONFIG

W, H = 768, 576


def _font(size):
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _canvas(bg=(205, 200, 190)):
    img = Image.new("RGB", (W, H), bg)
    return img, ImageDraw.Draw(img)


def _jpeg(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def note():
    img, d = _canvas()
    d.rectangle((140, 110, 630, 470), fill=(250, 248, 240))
    d.text((180, 200), "Reunião com Fulano", fill=(20, 20, 60), font=_font(40))
    d.text((180, 280), "às 15h30", fill=(20, 20, 60), font=_font(48))
    return img


def price():
    img, d = _canvas((60, 60, 70))
    d.rectangle((180, 150, 590, 420), fill=(250, 220, 40))
    d.text((230, 190), "PROMOÇÃO", fill=(200, 20, 20), font=_font(52))
    d.text((240, 290), "R$ 42,90", fill=(20, 20, 20), font=_font(70))
    return img


def shapes():
    img, d = _canvas((245, 245, 245))
    for x in (120, 330, 540):
        d.ellipse((x, 120, x + 120, 240), fill=(220, 30, 30))
    d.rectangle((320, 340, 450, 470), fill=(30, 70, 220))
    return img


def ball():
    img, d = _canvas((235, 230, 220))
    d.ellipse((260, 150, 510, 400), fill=(40, 170, 60))
    return img


def sign():
    img, d = _canvas((90, 100, 110))
    d.rectangle((200, 200, 570, 360), fill=(20, 140, 60))
    d.text((290, 235), "EXIT", fill=(255, 255, 255), font=_font(90))
    return img


def shopping_list():
    img, d = _canvas((150, 120, 90))
    d.rectangle((250, 60, 520, 520), fill=(252, 252, 245))
    for i, item in enumerate(("Lista:", "- leite", "- pão", "- café", "- banana")):
        d.text((275, 90 + i * 42), item, fill=(30, 30, 120), font=_font(24))
    return img


def mixed():
    img, d = _canvas((245, 245, 245))
    for x, y in ((80, 80), (300, 60), (560, 120), (150, 330), (420, 360)):
        d.ellipse((x, y, x + 90, y + 90), fill=(30, 70, 220))
    for x, y in ((450, 220), (90, 220)):
        d.rectangle((x, y, x + 80, y + 80), fill=(220, 30, 30))
    return img


def dark():
    img, d = _canvas((12, 12, 14))
    d.ellipse((330, 250, 420, 330), fill=(26, 26, 30))
    return img


def tilted():
    card = Image.new("RGB", (420, 160), (255, 255, 255))
    ImageDraw.Draw(card).text((30, 45), "Senha: 7Q4-912", fill=(0, 0, 0), font=_font(50))
    img, _ = _canvas((70, 90, 80))
    rotated = card.rotate(14, expand=True, fillcolor=(70, 90, 80))
    img.paste(rotated, (150, 160))
    return img


CASES = [
    ("Quais itens estão na lista?", shopping_list, [["leite"], ["pão", "pao"], ["café", "cafe"], ["banana"]]),
    ("Quantos círculos azuis tem na imagem?", mixed, [["5", "cinco"]]),
    ("O que você está vendo?", dark, [["escur", "pret", "pouca luz", "sem luz"]]),
    ("O que está escrito no cartão?", tilted, [["7q4"], ["912"]]),
    ("O que está escrito no papel?", note, [["15"], ["reuni"]]),
    ("Qual é o preço que aparece?", price, [["42"]]),
    ("Quantos círculos vermelhos tem na imagem?", shapes, [["3", "três"]]),
    ("Qual é a cor da bola?", ball, [["verde"]]),
    ("O que diz a placa?", sign, [["exit", "saída"]]),
]


def _foreign(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(ord(c) > 0x24F for c in letters) / len(letters) > 0.3


def run(model: str) -> None:
    client = ollama.Client(host=CONFIG.ollama_host, timeout=600)
    try:
        client.generate(model=CONFIG.ollama_model, keep_alive=0)     # same room as the swap profile
    except Exception:
        pass
    ok, times = 0, []
    for question, make, groups in CASES:
        start = time.perf_counter()
        resp = client.chat(model=model, think=False, keep_alive="5m",
                           options={"num_ctx": CONFIG.vision_num_ctx, "num_gpu": 0},
                           messages=[{"role": "system", "content": vision._VISION_SYSTEM},
                                     {"role": "user", "content": question, "images": [_jpeg(make())]}])
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        text = (resp.message.content or "").strip()
        low = text.lower()
        hit = all(any(k in low for k in group) for group in groups) and not _foreign(text)
        ok += hit
        print(f"  {'✓' if hit else '✗'} {elapsed:5.1f}s  {question}  →  {text[:110]!r}")
    loaded = [m for m in client.ps().models if m.model.startswith(model.split(':')[0])]
    size = f"{loaded[0].size / 1e9:.1f} GB" if loaded else "?"
    client.generate(model=model, keep_alive=0)
    print(f"{model}: {ok}/{len(CASES)} certas, 1ª foto {times[0]:.1f}s, demais mediana "
          f"{statistics.median(times[1:]):.1f}s, ocupa {size} (CPU)\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    models = sys.argv[1].split(",") if len(sys.argv) > 1 else [CONFIG.vision_model]
    for model in models:
        print(model)
        run(model)


if __name__ == "__main__":
    main()
