"""First-run wizard: form of address, persona, audio, city and voice.

Runs before the main window while settings.first_run_done is false. Each step
only reads and writes preferences; nothing here needs the agent to be loaded.
"""

import logging
import threading
import tkinter as tk
from tkinter import ttk

import numpy as np
import sounddevice as sd

from pidreams.agent.personas import conduct
from pidreams.audio import devices, voices
from pidreams.ui import theme

log = logging.getLogger(__name__)

_STEPS = ("Apresentação", "Personalidade", "Áudio", "Clima", "Voz")


class FirstRunWizard:
    def __init__(self, settings, root: tk.Tk | None = None):
        self.st = settings
        self.root = root or tk.Tk()
        theme.init(self.root)
        self.root.title("PI dreams — Primeiro uso")
        self.root.configure(bg=theme.GLASS)
        self.root.geometry(f"{theme.px(600)}x{theme.px(500)}")
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)
        self.finished = False
        self._step = 0
        self._meter = None          # microphone stream in the audio step

        self._name = tk.StringVar(value=settings.get("assistant_name"))
        self._treatment = tk.StringVar(value=settings.get("treatment"))
        self._persona = tk.StringVar(value=settings.get("persona_id"))
        self._city = tk.StringVar(value=settings.get("weather.city"))
        self._voice = tk.StringVar(value=settings.get("voice.model"))
        default = "Padrão do Windows"
        self._inputs = {default: None, **{n: n for n in devices.list_items("input")}}
        self._outputs = {default: None, **{n: n for n in devices.list_items("output")}}
        self._mic = tk.StringVar(value=settings.get("audio.input_device") or default)
        self._output = tk.StringVar(value=settings.get("audio.output_device") or default)
        self._level = 0.0

        self._title = tk.Label(self.root, bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT_TITLE)
        self._title.pack(pady=(theme.px(18), theme.px(4)))
        self._step_size = tk.Label(self.root, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL)
        self._step_size.pack()
        self._body = tk.Frame(self.root, bg=theme.GLASS)
        self._body.pack(fill=tk.BOTH, expand=True, padx=theme.px(26), pady=theme.px(12))
        footer = tk.Frame(self.root, bg=theme.GLASS)
        footer.pack(fill=tk.X, padx=theme.px(26), pady=(0, theme.px(18)))
        self._back = theme.button(footer, "Voltar", self.go_back)
        self._back.pack(side=tk.LEFT)
        self._advance = theme.button(footer, "Avançar", self.advance, kind="primary")
        self._advance.pack(side=tk.RIGHT)
        self._show()

    # ── layout ────────────────────────────────────────────────────────────

    def _label(self, text, dim=False):
        tk.Label(self._body, text=text, bg=theme.GLASS, fg=theme.MUTED if dim else theme.TEXT,
                 font=theme.FONT_SMALL if dim else theme.FONT, justify="left", anchor="w",
                 wraplength=theme.px(540)).pack(fill=tk.X, pady=(theme.px(10), theme.px(3)))

    def _field(self, var):
        theme.entry(self._body, textvariable=var).pack(fill=tk.X, ipady=theme.px(4))

    def _items(self, var, options, on_change=None):
        box = ttk.Combobox(self._body, textvariable=var, values=options, state="readonly")
        if on_change:
            box.bind("<<ComboboxSelected>>", lambda _e: on_change())
        box.pack(fill=tk.X)

    def _show(self):
        self._stop_meter()
        for w in self._body.winfo_children():
            w.destroy()
        self._title.config(text=_STEPS[self._step])
        self._step_size.config(text=f"Etapa {self._step + 1} de {len(_STEPS)}")
        self._back.config(state=tk.NORMAL if self._step else tk.DISABLED)
        self._advance.config(text="Concluir" if self._step == len(_STEPS) - 1 else "Avançar")
        (self._step_name, self._step_persona, self._step_audio,
         self._step_weather, self._step_voice)[self._step]()

    def advance(self):
        if self._step == len(_STEPS) - 1:
            self._finish()
        else:
            self._step += 1
            self._show()

    def go_back(self):
        if self._step:
            self._step -= 1
            self._show()

    # ── steps ───────────────────────────────────────────────────────────────

    def _step_name(self):
        self._label("Como o assistente deve se chamar?")
        self._field(self._name)
        self._label("Como ele deve chamar você? (ex.: seu nome, \"senhor\", \"senhora\")")
        self._field(self._treatment)
        self._label("Deixe em branco para ele não usar um vocativo fixo.", dim=True)

    def _step_persona(self):
        self._label("Escolha a personalidade (dá para trocar depois):")
        for p in conduct.list_items():
            example = conduct.sample_phrase(p, self._treatment.get().strip())
            tk.Radiobutton(self._body, text=p["name"], value=p["id"], variable=self._persona, bg=theme.GLASS,
                           fg=theme.TEXT, selectcolor=theme.INPUT, activebackground=theme.GLASS,
                           activeforeground=theme.CYAN, font=theme.FONT, anchor="w", bd=0,
                           highlightthickness=0, cursor="hand2").pack(fill=tk.X, pady=(theme.px(8), 0))
            for text in (p["description"], f"“{example}”"):
                tk.Label(self._body, text=text, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                         justify="left", anchor="w", wraplength=theme.px(500)).pack(fill=tk.X, padx=(theme.px(26), 0))

    def _step_audio(self):
        self._label("Microfone — fale algo e veja a barra se mexer:")
        self._items(self._mic, list(self._inputs), self._start_meter)
        self._bar = tk.Canvas(self._body, height=12, bg=theme.INPUT, highlightthickness=0)
        self._bar.pack(fill=tk.X, pady=(4, 0))
        self._label("Saída de som:")
        self._items(self._output, list(self._outputs))
        theme.button(self._body, "Tocar som de teste", self._test_sound).pack(anchor="w", pady=theme.px(8))
        self._start_meter()
        self._update_bar()

    def _step_weather(self):
        self._label("Cidade para a previsão do tempo (opcional):")
        self._field(self._city)
        self._label("Deixe em branco para não mostrar o clima.", dim=True)

    def _step_voice(self):
        names = list(voices.list_items()) or [self._voice.get()]
        if self._voice.get() not in names:
            self._voice.set(names[0])
        self._label("Voz do assistente:")
        self._items(self._voice, names)
        theme.button(self._body, "Ouvir prévia", self._preview).pack(anchor="w", pady=theme.px(8))

    # ── audio ────────────────────────────────────────────────────────────────

    def _start_meter(self):
        self._stop_meter()
        index = devices.index(self._inputs.get(self._mic.get()), "input")

        def callback(data, *_):
            self._level = float(np.sqrt(np.mean(data ** 2)))
        try:
            self._meter = sd.InputStream(device=index, channels=1, samplerate=16000, callback=callback)
            self._meter.start()
        except Exception as e:
            log.warning("Could not open the microphone in the wizard: %s", e)
            self._meter = None

    def _stop_meter(self):
        if self._meter is not None:
            try:
                self._meter.stop()
                self._meter.close()
            except Exception:
                pass
            self._meter = None

    def _update_bar(self):
        if self._step != 2 or not self._bar.winfo_exists():
            return
        width = self._bar.winfo_width()
        self._bar.delete("all")
        self._bar.create_rectangle(0, 0, int(width * min(1.0, self._level * 20)), 12,
                                     fill=theme.CYAN, outline="")
        self.root.after(50, self._update_bar)

    def _test_sound(self):
        t = np.linspace(0, 0.6, int(22050 * 0.6), endpoint=False)
        beep = (0.3 * np.sin(2 * np.pi * 660 * t)).astype(np.float32)
        try:
            sd.play(beep, 22050, device=devices.index(self._outputs.get(self._output.get()), "output"))
        except Exception as e:
            log.warning("Test sound failed: %s", e)

    def _preview(self):
        file = voices.list_items().get(self._voice.get())
        if file is None:
            return
        text = conduct.sample_phrase(conduct.load(self._persona.get()),
                                         self._treatment.get().strip())
        output = devices.index(self._outputs.get(self._output.get()), "output")

        def speak():
            try:
                from piper import PiperVoice

                voice = PiperVoice.load(str(file), use_cuda=False)
                audio = np.concatenate([c.audio_float_array for c in voice.synthesize(text)])
                sd.play(audio, voice.config.sample_rate, device=output)
            except Exception as e:
                log.warning("Voice preview failed: %s", e)

        threading.Thread(target=speak, daemon=True).start()

    # ── fim ──────────────────────────────────────────────────────────────────

    def _finish(self):
        self.st.set("assistant_name", self._name.get().strip() or "PI dreams")
        self.st.set("treatment", self._treatment.get().strip())
        self.st.set("persona_id", self._persona.get())
        self.st.set("audio.input_device", self._inputs.get(self._mic.get()))
        self.st.set("audio.output_device", self._outputs.get(self._output.get()))
        self.st.set("weather.city", self._city.get().strip())
        self.st.set("voice.model", self._voice.get())
        self.st.set("first_run_done", True)
        self.st.save()
        self.finished = True
        self._close()

    def _cancel(self):
        self._close()

    def _close(self):
        self._stop_meter()
        self.root.destroy()

    def run(self) -> bool:
        """True if the user finished; False if they closed the window."""
        self.root.mainloop()
        return self.finished
