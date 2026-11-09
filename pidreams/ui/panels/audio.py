"""Audio panel: microphone, output, volume, Mudo and Câmera."""

import tkinter as tk
import threading
from tkinter import ttk

from pidreams.audio import devices
from pidreams.core.config import CONFIG
from pidreams.core.settings import SETTINGS
from pidreams.ui import theme


class AudioPanelMixin:
    """Audio panel: microphone, output, volume, Mudo and Câmera."""

    # ── Audio device selectors ─────────────────────────────────────────────────

    def _build_audio_selectors(self, parent, toggles):
        """Microphone, output and volume rows in parent; MUDO and CÂMERA join the Voz/Texto
        buttons in toggles."""
        def mapping(kind: str) -> dict:
            # label shown -> device name (the name is what goes to settings.json)
            m = {"Padrão do Windows": None}
            for name in devices.list_items(kind):
                m[name] = name
            return m

        self._input_device_map  = mapping("input")
        self._output_device_map = mapping("output")

        def label_for(name, dmap):
            return next((lbl for lbl, n in dmap.items() if n == name), "Padrão do Windows")

        parent.columnconfigure(1, weight=1)

        def _row(row, text, widget):
            tk.Label(parent, text=text, bg=theme.GLASS, fg=theme.TEXT2, font=theme.FONT_SMALL,
                     anchor="w").grid(row=row, column=0, sticky="w", padx=(0, theme.px(12)), pady=theme.px(4))
            widget.grid(row=row, column=1, sticky="ew", pady=theme.px(4))

        def _combo(strvar, options, trace_fn):
            box = ttk.Combobox(parent, textvariable=strvar, values=options, state="readonly", width=1)
            strvar.trace_add("write", trace_fn)
            return box

        self._mic_var = tk.StringVar(
            value=label_for(SETTINGS.get("audio.input_device"), self._input_device_map))
        self._out_var = tk.StringVar(
            value=label_for(SETTINGS.get("audio.output_device"), self._output_device_map))
        _row(0, "Microfone", _combo(self._mic_var, list(self._input_device_map), self._on_mic_change))
        _row(1, "Saída", _combo(self._out_var, list(self._output_device_map), self._on_out_change))

        self._btn_mute = theme.button(toggles, "Mudo", self._toggle_mute, icon="mute")
        self._btn_mute.pack(side=tk.LEFT, padx=(theme.px(16), theme.px(4)))
        # Answer everything said with the window open, or only speech that starts with "PI, ...".
        self._btn_wake = theme.button(toggles, "Só com PI", self._toggle_wake_name, icon="name")
        self._btn_wake.pack(side=tk.LEFT, padx=(0, theme.px(4)))
        self._refresh_wake_btn()
        # Turns the "camera" service on/off (ver_camera tool). It lives here, and
        # not in the Serviços tab, to be in sight while chatting.
        self._btn_camera = theme.button(toggles, "Câmera", self._toggle_camera, icon="camera")
        self._btn_camera.pack(side=tk.LEFT)
        self._refresh_camera_btn()

        self._vol_var = tk.DoubleVar(value=self._volume_ref[0] * 100)
        self._vol_scale = theme.Slider(parent, self._vol_var, 0, 100, command=self._on_volume_change)
        self._vol_scale.bind("<ButtonRelease-1>", lambda _e: SETTINGS.save())
        _row(2, "Volume", self._vol_scale)

    def _on_mic_change(self, *_):
        name = self._input_device_map.get(self._mic_var.get())
        SETTINGS.set("audio.input_device", name)
        SETTINGS.save()
        self._mic_device_ref[0] = devices.index(name, "input")

    def _on_out_change(self, *_):
        name = self._output_device_map.get(self._out_var.get())
        SETTINGS.set("audio.output_device", name)
        SETTINGS.save()
        self._out_device_ref[0] = devices.index(name, "output")

    def _on_volume_change(self, val):
        # Writes the file only when the slider is released (bind above), not on every step.
        self._volume_ref[0] = round(float(val)) / 100.0
        SETTINGS.set("audio.volume", self._volume_ref[0])


    def _toggle_mute(self):
        self._mute_ref[0] = not self._mute_ref[0]
        theme.set_kind(self._btn_mute, "danger" if self._mute_ref[0] else "normal")

    def _toggle_wake_name(self):
        SETTINGS.set("voice.wake_name", not SETTINGS.get("voice.wake_name"))
        SETTINGS.save()                  # the settings subscription refreshes the button
        self._refresh_wake_btn()

    def _refresh_wake_btn(self):
        theme.set_kind(self._btn_wake, "on" if SETTINGS.get("voice.wake_name") else "normal")

    def _toggle_camera(self):
        if str(self._btn_camera.cget("state")) == tk.DISABLED:
            return                    # already turning on/off
        svc = self._services.get("camera")
        start_connection = not svc.running
        self._btn_camera.config(state=tk.DISABLED, text=f"{theme.ICON['camera']}  …")

        if start_connection:
            # First time: the vision model is downloaded on demand.
            threading.Thread(target=self._camera_check_model, daemon=True).start()
            return
        self._camera_toggle(False)

    def _camera_check_model(self):
        from pidreams.hardware import models

        try:
            present = models.ollama_model_present(CONFIG.vision_model)
        except Exception:
            present = True           # Ollama is down: the tool itself reports it later
        if present:
            self.root.after(0, self._camera_toggle, True)
        else:
            self.root.after(0, self._camera_download_model)

    def _camera_download_model(self):
        from pidreams.hardware import models
        from pidreams.ui.download_dialog import DownloadDialog

        def finished(ok: bool, failures: list[str]):
            if ok:
                self._camera_toggle(True)
            else:
                self._on_service_log("camera", "modelo de visão não baixado: " + "; ".join(failures))
                self._refresh_camera_btn()

        DownloadDialog(self.root, "Câmera — baixando o modelo de visão",
                       [(f"Modelo de visão ({CONFIG.vision_model})",
                         lambda p, c: models.download_ollama(CONFIG.vision_model, p, c))],
                       on_finish=finished)

    def _camera_toggle(self, start_connection: bool):
        def _work():
            try:
                msg = self._services.toggle("camera", start_connection)
                self._on_service_log("camera", msg)
            except RuntimeError as e:
                self._on_service_log("camera", f"não foi possível ligar: {e}")
                from pidreams.agent import problems
                self.root.after(0, self._notices.show, problems.from_camera(e))
            except Exception as e:
                self._on_service_log("camera", f"erro inesperado: {e!r}")
            self.root.after(0, self._refresh_camera_btn)

        threading.Thread(target=_work, daemon=True).start()

    def _refresh_camera_btn(self):
        b = self._btn_camera
        if self._services.get("camera").running:
            b.config(state=tk.NORMAL, text=f"{theme.ICON['camera']}  Câmera ●")
            theme.set_kind(b, "on")
            self._open_camera_window()
        else:
            b.config(state=tk.NORMAL, text=f"{theme.ICON['camera']}  Câmera")
            theme.set_kind(b, "normal")
            self._close_camera_window()
