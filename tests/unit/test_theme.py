"""Tema "vidro neon": contraste legível e medidas proporcionais à escala do Windows."""

from pidreams.ui import theme


def _luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_todo_texto_do_tema_tem_contraste_de_pelo_menos_4_5():
    fracos = [(fg, bg, round(contrast(fg, bg), 2)) for fg, bg in theme.TEXT_PAIRS if contrast(fg, bg) < 4.5]
    assert not fracos


def test_px_segue_a_escala_do_windows(monkeypatch):
    monkeypatch.setattr(theme, "_scale", [1.0])
    assert theme.px(300) == 300
    monkeypatch.setattr(theme, "_scale", [1.5])
    assert theme.px(300) == 450


def test_todo_estado_da_aparencia_tem_cor():
    assert set(theme.STATE_COLORS) == {"idle", "listening", "thinking", "speaking"}


# ── varredura das telas ───────────────────────────────────────────────────────
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "pidreams" / "ui"
_ROTULOS_ANTIGOS = ("INITIALIZING", "SHUTDOWN", "INPUT", "MIC", "TEXT", "SEND", "CHAT", "ADD", "ALL",
                    "SET", "ERR", "OFFLINE", "LINK", "VER", "MEM", "SERV", "KB")


def _arquivos_de_tela():
    return [p for p in UI.rglob("*.py") if "appearances" not in p.parts and p.name != "theme.py"]


def test_nenhum_rotulo_antigo_em_ingles_ou_sigla():
    achados = []
    for arquivo in _arquivos_de_tela():
        texto = arquivo.read_text(encoding="utf-8")
        for rotulo in _ROTULOS_ANTIGOS:
            # só textos de widget: text="...", value="...", StringVar(value="...")
            if re.search(rf'(text|value)=f?"[^"]*\b{rotulo}\b', texto):
                achados.append((arquivo.name, rotulo))
    assert not achados


def test_nenhuma_cor_fixa_fora_do_tema():
    achados = [(p.name, m) for p in _arquivos_de_tela()
               for m in re.findall(r'"#[0-9a-fA-F]{6}"', p.read_text(encoding="utf-8"))]
    assert not achados


def test_textos_de_tela_nao_ficam_em_caixa_alta():
    gritando = []
    for arquivo in _arquivos_de_tela():
        for m in re.finditer(r'text=f?"([^"{]*)"', arquivo.read_text(encoding="utf-8")):
            palavras = re.findall(r"[A-Za-zÀ-ÿ]{4,}", m.group(1))
            if palavras and all(p.isupper() for p in palavras):
                gritando.append((arquivo.name, m.group(1)))
    assert not gritando


def test_janela_principal_se_chama_pi_dreams():
    texto = (UI / "main_window.py").read_text(encoding="utf-8")
    assert 'WINDOW_TITLE = "PI dreams"' in texto
