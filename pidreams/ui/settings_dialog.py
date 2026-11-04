"""Settings screen: everything the user chooses, without
editing files, applied without restarting (each part of the app uses settings.subscribe).

Allowed apps, memory and plugins stay in their own panel tabs — what already has
a place is not repeated here.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk

from pidreams.agent.personas import conduct
from pidreams.audio import devices, voices
from pidreams.core import paths
from pidreams.ui import appearances
from pidreams.ui import theme


class SettingsDialog:
    def __init__(self, master, settings):
        self.st = settings
        self.window = tk.Toplevel(master)
        self.window.title("PI dreams — Configurações")
        self.window.configure(bg=theme.BG)
        self.window.geometry(f"{theme.px(640)}x{theme.px(600)}")
        tabs = ttk.Notebook(self.window)          # styled by theme.init
        tabs.pack(fill=tk.BOTH, expand=True, padx=theme.px(12), pady=theme.px(12))

        self.v = {
            "assistant_name": tk.StringVar(value=settings.get("assistant_name")),
            "treatment": tk.StringVar(value=settings.get("treatment")),
            "persona_id": tk.StringVar(value=conduct.load(settings.get("persona_id"))["id"]),
            "appearance": tk.StringVar(value=settings.get("appearance")),
            **{f"resumo.{part}": tk.BooleanVar(value=settings.get(f"resumo.{part}"))
               for part in ("ligado", "toda_vez", "clima", "agenda", "emails", "lembretes")},
            "audio.input_device": tk.StringVar(value=settings.get("audio.input_device") or _DEFAULT_DEVICE),
            "audio.output_device": tk.StringVar(value=settings.get("audio.output_device") or _DEFAULT_DEVICE),
            "voice.model": tk.StringVar(value=voices.resolve(settings.get("voice.model"))),
            "voice.length_scale": tk.DoubleVar(value=settings.get("voice.length_scale")),
            "voice.effect": tk.StringVar(value=_EFFECTS_LABEL[settings.get("voice.effect")]),
            "weather.city": tk.StringVar(value=settings.get("weather.city")),
            "llm.model": tk.StringVar(value=settings.get("llm.model") or _RECOMMENDED),
            "ollama.host": tk.StringVar(value=settings.get("ollama.host")),
            "ollama.timeout_s": tk.DoubleVar(value=settings.get("ollama.timeout_s")),
        }
        for title, build in (("Geral", self._general), ("Áudio e voz", self._audio),
                               ("Hardware e modelo", self._hardware), ("Avançado", self._advanced)):
            tab = tk.Frame(tabs, bg=theme.GLASS, padx=theme.px(18), pady=theme.px(12))
            tabs.add(tab, text=title)
            build(tab)

        footer = tk.Frame(self.window, bg=theme.BG)
        footer.pack(fill=tk.X, padx=theme.px(12), pady=(0, theme.px(12)))
        theme.button(footer, "Salvar", self.save, kind="primary").pack(side=tk.RIGHT)
        theme.button(footer, "Cancelar", self.window.destroy).pack(side=tk.RIGHT, padx=theme.px(8))
        self._status = tk.Label(footer, text="", bg=theme.BG, fg=theme.MUTED, font=theme.FONT_SMALL)
        self._status.pack(side=tk.LEFT)

    # ── pieces ───────────────────────────────────────────────────────────────

    def _label(self, parent, text, dim=False):
        tk.Label(parent, text=text, bg=theme.GLASS, fg=theme.MUTED if dim else theme.TEXT, anchor="w", justify="left",
                 font=theme.FONT_SMALL if dim else theme.FONT, wraplength=theme.px(560)).pack(
                     fill=tk.X, pady=(theme.px(10), theme.px(3)))

    def _field(self, parent, var):
        theme.entry(parent, textvariable=var).pack(fill=tk.X, ipady=theme.px(4))

    def _items(self, parent, var, options):
        ttk.Combobox(parent, textvariable=var, values=options, state="readonly").pack(fill=tk.X)

    def _radio(self, parent, text, value, var):
        return tk.Radiobutton(parent, text=text, value=value, variable=var, bg=theme.GLASS, fg=theme.TEXT2,
                              selectcolor=theme.INPUT, activebackground=theme.GLASS, activeforeground=theme.TEXT,
                              font=theme.FONT_SMALL, anchor="w", bd=0, highlightthickness=0, cursor="hand2")

    # ── tabs ─────────────────────────────────────────────────────────────────

    def _general(self, tab):
        self._label(tab, "Nome do assistente")
        self._field(tab, self.v["assistant_name"])
        self._label(tab, "Como ele chama você (em branco = sem vocativo fixo)")
        self._field(tab, self.v["treatment"])
        self._label(tab, "Personalidade")
        for p in conduct.list_items():
            self._radio(tab, f"{p['name']} — {p['description']}", p["id"], self.v["persona_id"]).pack(fill=tk.X)
        self._label(tab, "Aparência")
        line = tk.Frame(tab, bg=theme.GLASS)
        line.pack(fill=tk.X)
        for id_, name in appearances.names().items():
            self._radio(line, name, id_, self.v["appearance"]).pack(side=tk.LEFT, padx=(0, theme.px(10)))
        self._label(tab, "Resumo ao abrir")
        # One choice on screen, two saved flags (ligado, toda_vez): settings saved before stay valid.
        when = tk.StringVar(value=_BRIEFING_WHEN_LABEL[(self.v["resumo.ligado"].get(), self.v["resumo.toda_vez"].get())]
                            if self.v["resumo.ligado"].get() else _BRIEFING_WHEN_LABEL[(False, False)])

        def set_flags(*_):
            ligado, toda_vez = {v: k for k, v in _BRIEFING_WHEN_LABEL.items()}[when.get()]
            self.v["resumo.ligado"].set(ligado)
            self.v["resumo.toda_vez"].set(toda_vez)
        when.trace_add("write", set_flags)
        self._briefing_when = when             # keeps the variable alive while the dialog is open
        self._items(tab, when, list(_BRIEFING_WHEN_LABEL.values()))
        line = tk.Frame(tab, bg=theme.GLASS)
        line.pack(fill=tk.X)
        for part, label_text in (("clima", "Clima"), ("agenda", "Agenda"),
                              ("emails", "E-mails"), ("lembretes", "Lembretes")):
            theme.check(line, label_text, self.v[f"resumo.{part}"]).pack(side=tk.LEFT, padx=(0, theme.px(10)))
        self._label(tab, "Cidade do clima (em branco = sem clima)")
        self._field(tab, self.v["weather.city"])

    def _audio(self, tab):
        self._label(tab, "Microfone")
        self._items(tab, self.v["audio.input_device"], [_DEFAULT_DEVICE, *devices.list_items("input")])
        self._label(tab, "Saída de som")
        self._items(tab, self.v["audio.output_device"], [_DEFAULT_DEVICE, *devices.list_items("output")])
        self._label(tab, "Voz")
        self._items(tab, self.v["voice.model"], voices.choices())
        self._label(tab, "Efeito de assistente (presença, brilho metálico e eco curto)")
        self._items(tab, self.v["voice.effect"], list(_EFFECTS_LABEL.values()))
        self._label(tab, "Velocidade da fala (maior = mais devagar)")
        theme.Slider(tab, self.v["voice.length_scale"], 0.5, 2.0).pack(fill=tk.X)

    def _hardware(self, tab):
        from pidreams.hardware import detect
        from pidreams.hardware.recommend import recommend_models

        profile = detect.current_profile()
        rec = recommend_models(profile)
        gpu = f"{profile.gpu_name} ({profile.vram_gb:.0f} GB)" if profile.gpu_name else "nenhuma GPU dedicada"
        self._label(tab, f"Placa de vídeo: {gpu}")
        self._label(tab, f"Memória RAM: {profile.ram_bytes / 1024**3:.0f} GB")
        self._label(tab, f"Recomendado para este PC: {rec.llm} — {rec.reason}", dim=True)
        self._label(tab, "Modelo de conversa")
        self._items(tab, self.v["llm.model"], [_RECOMMENDED, *_installed_models()])
        theme.button(tab, "Refazer a detecção", lambda: threading.Thread(target=detect.redetect, daemon=True).start(),
                     icon="refresh").pack(anchor="w", pady=theme.px(10))
        self._research_model(tab, rec.research_llm)

    def _research_model(self, tab, name: str):
        """The deep research writes its report with a stronger model, downloaded only on request;
        without it, the research uses the chat model."""
        from pidreams.hardware import models
        from pidreams.ui.download_dialog import DownloadDialog

        try:
            present = models.ollama_model_present(name)
        except Exception:          # Ollama down: nothing to offer now
            return
        if present:
            self._label(tab, f"Modelo da pesquisa profunda: {name} (instalado)", dim=True)
            return
        self._label(tab, f"Pesquisa profunda: o relatório sai melhor com o {name} (~9 GB, opcional). "
                         "Sem ele, a pesquisa usa o modelo de conversa.", dim=True)
        theme.button(tab, f"Baixar {name}", lambda: DownloadDialog(
            self.window, "Pesquisa profunda — baixando o modelo",
            [(f"Modelo da pesquisa profunda ({name})", lambda p, c: models.download_ollama(name, p, c))]),
            icon="download").pack(anchor="w")

    def _advanced(self, tab):
        self._label(tab, "Endereço do Ollama")
        self._field(tab, self.v["ollama.host"])
        self._label(tab, "Tempo máximo de espera por resposta (segundos)")
        self._field(tab, self.v["ollama.timeout_s"])
        line = tk.Frame(tab, bg=theme.GLASS)
        line.pack(anchor="w", pady=theme.px(12))
        theme.button(line, "Abrir o log", lambda: os.startfile(paths.logs_dir()), icon="log").pack(side=tk.LEFT)
        theme.button(line, "Abrir a pasta de dados", lambda: os.startfile(paths.user_data_dir()),
                     icon="folder").pack(side=tk.LEFT, padx=theme.px(8))

    # ── save ───────────────────────────────────────────────────────────────

    _LABELS = {"assistant_name": "nome do assistente (1 a 40 letras)", "treatment": "tratamento (até 40 letras)",
                "ollama.timeout_s": "tempo de espera (10 a 1800 s)", "voice.length_scale": "velocidade"}

    def save(self):
        if self._needs_voice_download():
            return                       # saved by the download dialog when it finishes
        new_items, errors = {}, []
        for key, var in self.v.items():
            try:
                value = var.get()
            except tk.TclError:
                errors.append(self._LABELS.get(key, key))
                continue
            if isinstance(value, str):
                value = value.strip()
            if key == "voice.length_scale":
                value = round(value * 20) / 20         # steps of 0.05, like the old slider
            if key == "voice.effect":
                value = {label: code for code, label in _EFFECTS_LABEL.items()}.get(value, "")
            if (key in ("audio.input_device", "audio.output_device") and value == _DEFAULT_DEVICE) or                (key == "llm.model" and value == _RECOMMENDED):
                value = None
            new_items[key] = value
        previous_items = {c: self.st.get(c) for c in new_items}
        for key, value in new_items.items():
            try:
                self.st.set(key, value)
            except ValueError:
                errors.append(self._LABELS.get(key, key))
        if errors:
            for key, value in previous_items.items():      # nothing is saved halfway
                self.st.set(key, value)
            self._status.config(text="corrija: " + ", ".join(errors), fg=theme.DANGER)
            return
        self.st.save()                   # notifies the subscribers: prompt, voice, audio...
        self._status.config(text="salvo — vale a partir da próxima interação", fg=theme.MUTED)


    def _needs_voice_download(self) -> bool:
        """The chosen voice's files are missing (the default comes with the install; the Kokoro voices
        only when one is chosen): download them, then save."""
        from pidreams.hardware import models
        from pidreams.ui.download_dialog import DownloadDialog

        if voices.is_kokoro(self.v["voice.model"].get()):
            present, label, download = models.kokoro_present(), "Vozes Kokoro (~340 MB, uma vez só)", models.download_kokoro
        else:
            present, label, download = models.pocket_present(), "Voz (~210 MB, uma vez só)", models.download_pocket
        if present:
            return False

        def finished(ok: bool, failures: list[str]):
            if ok:
                self.save()
            else:
                self._status.config(text="voz não baixada: " + "; ".join(failures), fg=theme.DANGER)

        DownloadDialog(self.window, "Voz — baixando as vozes",
                       [(label, download)], on_finish=finished)
        return True


_RECOMMENDED = "Recomendado para este PC"
_EFFECTS_LABEL = {"": "Desligado", "leve": "Leve", "medio": "Médio", "forte": "Forte"}
# (resumo.ligado, resumo.toda_vez) → what the user sees.
_BRIEFING_WHEN_LABEL = {(True, False): "Uma vez por dia", (True, True): "Toda vez que abrir",
                        (False, False): "Desligado"}
_DEFAULT_DEVICE = "Padrão do Windows"


def _installed_models() -> list[str]:
    try:
        from pidreams.hardware import models
        return sorted(m.model for m in models._client_of().list().models if "vl" not in m.model)
    except Exception:
        return []
