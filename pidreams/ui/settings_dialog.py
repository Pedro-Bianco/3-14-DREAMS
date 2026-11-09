"""Settings screen: everything the user chooses, without
editing files, applied without restarting (each part of the app uses settings.subscribe).

Allowed apps, memory and plugins stay in their own panel tabs — what already has
a place is not repeated here.
"""

import copy
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from pidreams.agent.personas import conduct
from pidreams import routines
from pidreams.audio import claps, devices, voices
from pidreams.core import paths
from pidreams.pc import startup
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
            # The Run key is the truth (the user may have turned it off in Task Manager).
            "tray.start_with_windows": tk.BooleanVar(value=startup.is_enabled()),
            "tray.close_to_tray": tk.BooleanVar(value=settings.get("tray.close_to_tray")),
            "tray.idle_minutes": tk.IntVar(value=settings.get("tray.idle_minutes")),
            "tray.claps": tk.BooleanVar(value=settings.get("tray.claps")),
            "tray.clap_level": tk.DoubleVar(value=settings.get("tray.clap_level")),
            "tray.speak_reminders": tk.BooleanVar(value=settings.get("tray.speak_reminders")),
            "voice.wake_name": tk.BooleanVar(value=settings.get("voice.wake_name")),
            "stt.engine": tk.StringVar(value=_STT_LABEL[settings.get("stt.engine")]),
            "audio.startup_sound": tk.BooleanVar(value=settings.get("audio.startup_sound")),
            "privacy.log_speech": tk.BooleanVar(value=settings.get("privacy.log_speech")),
        }
        for title, build in (("Geral", self._general), ("Áudio e voz", self._audio), ("Bandeja", self._tray),
                               ("Rotinas", self._routines_tab), ("Hardware e modelo", self._hardware),
                               ("Avançado", self._advanced)):
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
        self._label(tab, "Reconhecimento de voz")
        self._items(tab, self.v["stt.engine"], list(_STT_LABEL.values()))
        self._label(tab, "Voz")
        self._items(tab, self.v["voice.model"], voices.choices())
        self._label(tab, "Efeito de assistente (presença, brilho metálico e eco curto)")
        self._items(tab, self.v["voice.effect"], list(_EFFECTS_LABEL.values()))
        self._label(tab, "Velocidade da fala (maior = mais devagar)")
        theme.Slider(tab, self.v["voice.length_scale"], 0.5, 2.0).pack(fill=tk.X)
        theme.check(tab, "Tocar o som de abertura quando o PI abrir", self.v["audio.startup_sound"]).pack(
            anchor="w", pady=(theme.px(10), 0))
        theme.check(tab, "Só responder quando eu chamar pelo nome (ex.: \"PI, que horas são?\") — "
                         "conversas com outras pessoas, TV e ligações ficam sem resposta",
                    self.v["voice.wake_name"]).pack(anchor="w", pady=(theme.px(10), 0))
        self._label(tab, "Também liga e desliga pelo botão \"Só com PI\" na janela. Medido: o reconhecimento "
                         "entende o \"PI\" em cerca de 85% das vezes; um nome de duas sílabas (Geral → Nome do "
                         "assistente) costuma ser entendido melhor, e os dois passam a chamar.", dim=True)

    def _routines_tab(self, tab):
        """Routines edited as text, one step per line ("abrir: code"): simpler than a widget per
        step and easy to copy between routines."""
        self._routines = copy.deepcopy(self.st.get("routines"))
        self._routine_shown: int | None = None
        self._label(tab, "Diga \"modo <nome>\", \"protocolo <nome>\" ou \"rotina <nome>\" para rodar. Um passo por "
                         "linha, como \"tipo: valor\". Tipos: abrir (programa, arquivo ou site), fechar (pede "
                         "confirmação), volume (0 a 100), silenciar (sim/nao), musica (pausar, continuar, proxima, "
                         "anterior), falar (uma frase).", dim=True)
        body = tk.Frame(tab, bg=theme.GLASS)
        body.pack(fill=tk.BOTH, expand=True, pady=(theme.px(6), 0))
        left = tk.Frame(body, bg=theme.GLASS)
        left.pack(side=tk.LEFT, fill=tk.Y)
        self._routine_list = tk.Listbox(left, width=18, height=10, bg=theme.INPUT, fg=theme.TEXT, relief=tk.FLAT,
                                        highlightthickness=0, font=theme.FONT_SMALL, exportselection=False,
                                        selectbackground=theme.HOVER, selectforeground=theme.TEXT)
        self._routine_list.pack(fill=tk.Y, expand=True)
        self._routine_list.bind("<<ListboxSelect>>", lambda _e: self._show_routine())
        buttons = tk.Frame(left, bg=theme.GLASS)
        buttons.pack(fill=tk.X, pady=(theme.px(6), 0))
        theme.button(buttons, "Nova", self._new_routine).pack(side=tk.LEFT)
        theme.button(buttons, "Apagar", self._delete_routine).pack(side=tk.LEFT, padx=theme.px(6))
        right = tk.Frame(body, bg=theme.GLASS)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(theme.px(12), 0))
        tk.Label(right, text="Nome", bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT, anchor="w").pack(fill=tk.X)
        self._routine_name = tk.StringVar()
        theme.entry(right, textvariable=self._routine_name).pack(fill=tk.X, ipady=theme.px(4))
        tk.Label(right, text="Passos", bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT, anchor="w").pack(
            fill=tk.X, pady=(theme.px(8), 0))
        self._routine_steps = tk.Text(right, height=10, bg=theme.INPUT, fg=theme.TEXT, insertbackground=theme.TEXT,
                                      relief=tk.FLAT, font=theme.FONT_SMALL, highlightthickness=0)
        self._routine_steps.pack(fill=tk.BOTH, expand=True)
        self._refresh_routine_list(0 if self._routines else None)

    def _refresh_routine_list(self, select: int | None):
        self._routine_list.delete(0, tk.END)
        for routine in self._routines:
            self._routine_list.insert(tk.END, routine["name"] or "(sem nome)")
        self._routine_shown = None
        if select is not None:
            self._routine_list.selection_set(select)
        self._show_routine()

    def _keep_routine_edits(self):
        """Writes the name and steps on screen back into the routine being shown."""
        i = self._routine_shown
        if i is None or i >= len(self._routines):
            return
        steps = []
        for line in self._routine_steps.get("1.0", tk.END).splitlines():
            if line.strip():
                kind, _, value = line.partition(":")
                steps.append({"type": kind.strip().lower(), "value": value.strip()})
        self._routines[i] = {"name": self._routine_name.get().strip(), "steps": steps}

    def _show_routine(self):
        self._keep_routine_edits()
        picked = self._routine_list.curselection()
        self._routine_shown = picked[0] if picked else None
        routine = self._routines[self._routine_shown] if self._routine_shown is not None else {"name": "", "steps": []}
        self._routine_name.set(routine["name"])
        self._routine_steps.delete("1.0", tk.END)
        self._routine_steps.insert("1.0", "\n".join(f"{s['type']}: {s['value']}" for s in routine["steps"]))

    def _new_routine(self):
        self._keep_routine_edits()
        self._routines.append({"name": f"nova {len(self._routines) + 1}", "steps": [{"type": "falar", "value": "Pronto."}]})
        self._refresh_routine_list(len(self._routines) - 1)

    def _delete_routine(self):
        if self._routine_shown is None:
            return
        del self._routines[self._routine_shown]
        self._routine_shown = None
        self._refresh_routine_list(0 if self._routines else None)

    def _tray(self, tab):
        self._label(tab, "Dormindo na bandeja (ao lado do relógio), o PI fica sem janela e sem o modelo de "
                         "conversa na placa de vídeo; acorda com um clique no ícone ou com duas palmas.", dim=True)
        for key, text in (("tray.start_with_windows", "Iniciar junto com o Windows (já na bandeja)"),
                          ("tray.close_to_tray", "Ao fechar a janela, ir para a bandeja em vez de sair"),
                          ("tray.claps", "Ouvir duas palmas para acordar (só o volume do som: nada é gravado "
                                         "nem transcrito)"),
                          ("tray.speak_reminders", "Falar os lembretes quando estiver dormindo (desligado: só "
                                                   "a notificação do Windows)")):
            theme.check(tab, text, self.v[key]).pack(anchor="w", pady=(theme.px(6), 0))
        line = tk.Frame(tab, bg=theme.GLASS)
        line.pack(fill=tk.X, pady=(theme.px(8), 0))
        theme.button(line, "Calibrar palmas", self._calibrate_claps).pack(side=tk.LEFT)
        self._clap_info = tk.Label(line, text="", bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                                   anchor="w", justify="left", wraplength=theme.px(420))
        self._clap_info.pack(side=tk.LEFT, fill=tk.X, padx=theme.px(10))
        self._show_clap_level()
        self._label(tab, "Voltar à bandeja depois de quantos minutos sem uso (com a opção de fechar para a bandeja)")
        self._field(tab, self.v["tray.idle_minutes"])
        self._label(tab, "Jogos que fecham o PI por completo (um executável por linha, ex.: jogo.exe). "
                         "Jogos em tela cheia exclusiva já são reconhecidos sozinhos.", dim=True)
        self._games = tk.Text(tab, height=4, bg=theme.INPUT, fg=theme.TEXT, insertbackground=theme.TEXT,
                              relief=tk.FLAT, font=theme.FONT_SMALL, highlightthickness=0)
        self._games.insert("1.0", "\n".join(self.st.get("tray.games")))
        self._games.pack(fill=tk.X)

    def _show_clap_level(self, text: str = ""):
        self._clap_info.config(text=text or f"Sensibilidade atual: palmas acima de "
                               f"{self.v['tray.clap_level'].get():.2f}. Calibre se trocar de microfone.")

    def _calibrate_claps(self):
        """Three pairs of claps set the floor for this microphone (half of the weakest). Only loudness
        numbers are kept; the detector runs with the lowest floor so weak microphones are heard too."""
        if getattr(self, "_calibration", None) is not None:
            return
        name = self.v["audio.input_device"].get()
        device = devices.index(None if name == _DEFAULT_DEVICE else name, "input")
        heard: queue.Queue = queue.Queue()          # the audio thread never touches Tk
        listener = claps.ClapListener(device, on_claps=lambda: heard.put(listener.detector.last_peaks),
                                      ignore=lambda: False, min_level=claps.CALIBRATION_RANGE[0])
        try:
            listener.start()
        except Exception as e:
            self._show_clap_level(f"Microfone indisponível: {e}")
            return
        self._calibration = {"listener": listener, "peaks": [], "end": time.monotonic() + _CALIBRATION_S}
        self._show_clap_level(f"Bata duas palmas, {_CALIBRATION_PAIRS} vezes, com uma pausa entre elas…")

        def poll():
            state = self._calibration
            while not heard.empty():
                state["peaks"].extend(heard.get())
            pairs = len(state["peaks"]) // 2
            if pairs < _CALIBRATION_PAIRS and time.monotonic() < state["end"] and self.window.winfo_exists():
                if pairs:
                    self._show_clap_level(f"Ouvi {pairs} de {_CALIBRATION_PAIRS}…")
                self.window.after(100, poll)
                return
            listener.stop()
            self._calibration = None
            if not self.window.winfo_exists():
                return
            if pairs < _CALIBRATION_PAIRS:
                self._show_clap_level(f"Ouvi só {pairs} de {_CALIBRATION_PAIRS} pares. Bata mais perto do "
                                      "microfone e tente de novo.")
                return
            self.v["tray.clap_level"].set(claps.calibrated_level(state["peaks"]))
            self._show_clap_level(f"Pronto: palmas acima de {self.v['tray.clap_level'].get():.2f}. "
                                  "Clique em Salvar para usar.")
        poll()

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
        theme.check(tab, "Registrar no log o texto do que é dito e respondido (só para investigar um problema)",
                    self.v["privacy.log_speech"]).pack(anchor="w")
        self._label(tab, "Desligado, o log guarda só dados técnicos (duração, volume, tempos). O áudio nunca é "
                         "gravado.", dim=True)

    # ── save ───────────────────────────────────────────────────────────────

    _LABELS = {"assistant_name": "nome do assistente (1 a 40 letras)", "treatment": "tratamento (até 40 letras)",
                "ollama.timeout_s": "tempo de espera (10 a 1800 s)", "voice.length_scale": "velocidade",
                "tray.idle_minutes": "minutos sem uso (1 a 240)"}

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
            if key == "stt.engine":
                value = {label: code for code, label in _STT_LABEL.items()}.get(value, "auto")
            if (key in ("audio.input_device", "audio.output_device") and value == _DEFAULT_DEVICE) or                (key == "llm.model" and value == _RECOMMENDED):
                value = None
            new_items[key] = value
        new_items["tray.games"] = [line.strip() for line in self._games.get("1.0", tk.END).splitlines() if line.strip()]
        self._keep_routine_edits()
        if problem := routines.problem(self._routines):
            errors.append(f"rotinas ({problem})")
        new_items["routines"] = self._routines
        previous_items = {c: self.st.get(c) for c in new_items}
        for key, value in new_items.items():
            try:
                self.st.set(key, value)
            except ValueError:
                if key != "routines":                       # its problem is already in the list
                    errors.append(self._LABELS.get(key, key))
        if errors:
            for key, value in previous_items.items():      # nothing is saved halfway
                self.st.set(key, value)
            self._status.config(text="corrija: " + ", ".join(errors), fg=theme.DANGER)
            return
        startup_problem = self._apply_startup()
        self.st.save()                   # notifies the subscribers: prompt, voice, audio...
        if startup_problem:
            self._status.config(text=startup_problem, fg=theme.DANGER)
        else:
            self._status.config(text="salvo — vale a partir da próxima interação", fg=theme.MUTED)

    def _apply_startup(self) -> str | None:
        """Writes or deletes the Run value; on failure the setting keeps what Windows really has."""
        wanted = self.st.get("tray.start_with_windows")
        if wanted == startup.is_enabled():
            return None
        try:
            startup.set_enabled(wanted)
            return None
        except OSError as e:
            self.st.set("tray.start_with_windows", startup.is_enabled())
            self.v["tray.start_with_windows"].set(startup.is_enabled())
            return f"não consegui mudar o início com o Windows ({e.strerror or e})"


    def _needs_voice_download(self) -> bool:
        """The chosen voice's (or recognition's) files are missing (the default comes with the install;
        the Kokoro voices and the GPU recognition only when chosen): download them, then save."""
        from pidreams.hardware import models
        from pidreams.stt import openvino_whisper
        from pidreams.ui.download_dialog import DownloadDialog

        if self.v["stt.engine"].get() == _STT_LABEL["turbo"] and not openvino_whisper.present():
            def recognition_ready(ok: bool, failures: list[str]):
                if ok:
                    self.save()
                else:
                    self._status.config(text="reconhecimento não baixado: " + "; ".join(failures), fg=theme.DANGER)

            DownloadDialog(self.window, "Reconhecimento de voz — baixando o modelo",
                           [("Reconhecimento na placa de vídeo (~0,8 GB, uma vez só)", models.download_whisper_turbo)],
                           on_finish=recognition_ready)
            return True

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
_STT_LABEL = {"auto": "Recomendado para este PC",
              "small": "Rápido no processador (Whisper small)",
              "turbo": "Mais preciso na placa de vídeo Intel (Whisper large-v3-turbo)"}
_CALIBRATION_PAIRS = 3
_CALIBRATION_S = 30
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
