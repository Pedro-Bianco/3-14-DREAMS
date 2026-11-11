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


# ── tema Vidro ────────────────────────────────────────────────────────────────

def _mistura(cor: str, fundo: str, alfa: float) -> str:
    a = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(fundo[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x * alfa + y * (1 - alfa)) for x, y in zip(a, b))


def test_texto_sobre_o_vidro_continua_legivel_com_uma_janela_branca_atras():
    # O pior caso: o vidro tinge de BG o que está atrás; atrás, uma janela branca.
    vidro = _mistura(theme.BG, "#FFFFFF", theme.TINT_ALPHA)
    fracos = [(fg, round(contrast(fg, vidro), 2)) for fg in (theme.TEXT, theme.TEXT2, theme.MUTED, theme.CYAN,
                                                            theme.VIOLET, theme.OK, theme.WARN, theme.DANGER)
              if contrast(fg, vidro) < 4.5]
    assert not fracos


def test_vidro_troca_ao_vivo_e_volta_ao_neon(monkeypatch):
    import tkinter as tk

    monkeypatch.setattr(theme, "transparency_enabled", lambda: True)
    monkeypatch.setattr(theme, "_set_acrylic", lambda root, on: True)   # o efeito do Windows fica fora
    monkeypatch.setattr(theme, "_glass_on", [False])
    root = tk.Tk()
    root.configure(bg=theme.BG)
    try:
        fundo = tk.Frame(root, bg=theme.BG)
        painel = tk.Frame(fundo, bg=theme.GLASS)
        rotulo = tk.Label(painel, text="Conversa", bg=theme.GLASS)
        campo = tk.Entry(painel, bg=theme.INPUT)
        lista = theme.keep_solid(tk.Frame(painel, bg=theme.GLASS))
        item = tk.Label(lista, text="Notepad", bg=theme.GLASS)
        outra = tk.Toplevel(root, bg=theme.GLASS)                   # outras janelas ficam sólidas
        for w in (fundo, painel, rotulo, campo, lista, item):
            w.pack()

        assert theme.apply_theme(root, "vidro")
        assert [w["bg"] for w in (root, fundo, painel, rotulo)] == [theme.GLASS_KEY] * 4
        assert campo["bg"] == theme.INPUT
        assert lista["bg"] == item["bg"] == theme.GLASS
        assert outra["bg"] == theme.GLASS
        assert theme.surface() == theme.GLASS_KEY

        novo = tk.Label(painel, text="aparece depois", bg=theme.GLASS)   # ex.: um cartão criado mais tarde
        novo.pack()
        root.update()
        assert novo["bg"] == theme.GLASS_KEY
        filho = tk.Label(painel, text="herda do pai", bg=painel["bg"])
        filho.pack()

        assert not theme.apply_theme(root, "neon")
        assert [w["bg"] for w in (root, fundo, painel, rotulo, novo, filho)] == [
            theme.BG, theme.BG, theme.GLASS, theme.GLASS, theme.GLASS, theme.GLASS]
        assert theme.surface() == theme.GLASS
    finally:
        root.destroy()


def test_sem_transparencia_no_windows_o_vidro_fica_solido(monkeypatch):
    import tkinter as tk

    monkeypatch.setattr(theme, "transparency_enabled", lambda: False)
    monkeypatch.setattr(theme, "_glass_on", [False])
    root = tk.Tk()
    try:
        painel = tk.Frame(root, bg=theme.GLASS)
        assert not theme.apply_theme(root, "vidro")
        assert painel["bg"] == theme.GLASS
    finally:
        root.destroy()
