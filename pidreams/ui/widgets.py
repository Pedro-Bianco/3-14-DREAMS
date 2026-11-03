"""Shared visual pieces: colors, system monitor, weather and meter."""

import collections
import tkinter as tk
import threading
import time
import subprocess
import psutil
from pidreams.core.config import CONFIG
from pidreams.ui import theme


# ─────────────────────────────────────────────────────────────────────────────
#  Colour helpers (tkinter has no native alpha — blend manually with bg)
# ─────────────────────────────────────────────────────────────────────────────

def _blend(r, g, b, alpha: float) -> str:
    """(r, g, b) over the glass panel the appearances sit on."""
    r, g, b = (max(0, min(255, int(v))) for v in (r, g, b))
    return theme.blend(f"#{r:02x}{g:02x}{b:02x}", alpha)


# ─────────────────────────────────────────────────────────────────────────────
#  System Monitor  (background threads — CPU/RAM every 1s, GPU every 3s)
# ─────────────────────────────────────────────────────────────────────────────

class SystemMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            'cpu_pct': 0.0, 'cpu_temp': None,
            'ram_pct': 0.0, 'ram_used_gb': 0.0, 'ram_total_gb': 0.0,
            'gpu_pct': None, 'gpu_temp': None,
        }
        self._running = True
        threading.Thread(target=self._run_cpu_ram, daemon=True).start()
        threading.Thread(target=self._run_gpu,     daemon=True).start()

    # ── CPU / RAM ────────────────────────────────────────────────────────────

    def _run_cpu_ram(self):
        while self._running:
            cpu  = psutil.cpu_percent(interval=1)
            mem  = psutil.virtual_memory()
            temp = self._get_cpu_temp()
            with self._lock:
                self._data['cpu_pct']      = cpu
                self._data['cpu_temp']     = temp
                self._data['ram_pct']      = mem.percent
                self._data['ram_used_gb']  = mem.used  / (1024 ** 3)
                self._data['ram_total_gb'] = mem.total / (1024 ** 3)

    def _get_cpu_temp(self):
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for key in ('coretemp', 'k10temp', 'cpu-thermal', 'acpitz'):
                    if key in temps:
                        return temps[key][0].current
        except Exception:
            pass
        try:
            import wmi as _wmi
            w = _wmi.WMI(namespace="root\\wmi")
            zones = w.MSAcpi_ThermalZoneTemperature()
            if zones:
                return round((zones[0].CurrentTemperature / 10.0) - 273.15, 1)
        except Exception:
            pass
        return None

    # ── GPU ──────────────────────────────────────────────────────────────────

    def _run_gpu(self):
        while self._running:
            pct = self._get_gpu_pct()
            with self._lock:
                self._data['gpu_pct'] = pct
            time.sleep(3)

    def _get_gpu_pct(self):
        try:
            cmd = (
                "try { $v=(Get-Counter '\\GPU Engine(*engtype_3D*)\\Utilization Percentage'"
                " -ErrorAction Stop).CounterSamples | Measure-Object CookedValue -Sum;"
                " [math]::Round([math]::Min(100,$v.Sum),1) } catch { -1 }"
            )
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command', cmd],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            v = float(r.stdout.strip())
            return max(0.0, v) if v >= 0 else None
        except Exception:
            return None

    # ── Public ───────────────────────────────────────────────────────────────

    def get(self):
        with self._lock:
            return dict(self._data)

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────────────────────────────────────
#  Weather Fetcher  (background thread — fetches from Open-Meteo every 10 min)
# ─────────────────────────────────────────────────────────────────────────────

class WeatherFetcher:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {'city': '---', 'temp': '--', 'desc': '---'}
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        """Fetches every 10 min, or as soon as the city changes in the settings."""
        previous_city, last_search = None, 0.0
        while self._running:
            city = CONFIG.weather_city
            if not city:
                with self._lock:
                    self._data = {'city': '', 'temp': '', 'desc': ''}
            elif city != previous_city or time.time() - last_search > 600:
                ok = self._fetch(city)
                # A failure tries again in a minute instead of keeping "obtendo o clima…" for 10.
                previous_city, last_search = city, time.time() - (0 if ok else 540)
            time.sleep(5)

    def _fetch(self, city: str):
        from pidreams import weather

        try:
            data = weather.fetch(city)
        except Exception:
            return False
        with self._lock:
            self._data = data
        return True

    def get(self):
        with self._lock:
            return dict(self._data)

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────────────────────────────────────
#  MeterWidget  —  cyberpunk-style stat bar
# ─────────────────────────────────────────────────────────────────────────────

class MeterWidget(tk.Frame):
    """Glass card: current value in large digits and a line with the last 60 s.

    update() is called ~30 times per second by the window; the chart only takes a sample
    and redraws once per second, so the card costs nothing between samples."""

    _SAMPLES = 60

    def __init__(self, parent, label: str, color: str = theme.CYAN):
        super().__init__(parent, bg=theme.GLASS_HI, highlightthickness=1, highlightbackground=theme.BORDER)
        self._color = color
        self._history: collections.deque[float] = collections.deque(maxlen=self._SAMPLES)
        self._last_sample = 0.0
        self._shown = ("", "")

        top = tk.Frame(self, bg=theme.GLASS_HI)
        top.pack(fill=tk.X, padx=theme.px(12), pady=(theme.px(10), 0))
        tk.Label(top, text=label, bg=theme.GLASS_HI, fg=theme.TEXT2, font=theme.FONT).pack(side=tk.LEFT, anchor="n")
        self._value = tk.Label(top, text="--%", bg=theme.GLASS_HI, fg=color, font=theme.FONT_NUMBER)
        self._value.pack(side=tk.RIGHT)
        self._detail = tk.Label(self, text="", bg=theme.GLASS_HI, fg=theme.MUTED, font=theme.FONT_SMALL, anchor="w")
        self._detail.pack(fill=tk.X, padx=theme.px(12))
        self._chart = tk.Canvas(self, bg=theme.GLASS_HI, highlightthickness=0, width=1, height=theme.px(30))
        self._chart.pack(fill=tk.BOTH, expand=True, padx=theme.px(12), pady=(theme.px(6), theme.px(10)))
        self._chart.bind("<Configure>", lambda _e: self._draw())

    def update(self, pct: float, sub: str = ""):
        pct = max(0.0, min(100.0, float(pct)))
        shown = (f"{pct:.0f}%", sub)
        if shown != self._shown:
            self._shown = shown
            self._value.config(text=shown[0])
            self._detail.config(text=sub)
        now = time.monotonic()
        if now - self._last_sample >= 1.0:
            self._last_sample = now
            self._history.append(pct)
            self._draw()

    def _draw(self):
        c = self._chart
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10 or h < 10:
            return
        c.create_line(0, h - 1, w, h - 1, fill=theme.BORDER)
        if len(self._history) < 2:
            return
        step = w / (self._SAMPLES - 1)
        x0 = w - step * (len(self._history) - 1)
        points = [(x0 + i * step, (h - 3) - (h - 6) * v / 100) for i, v in enumerate(self._history)]
        c.create_polygon([(points[0][0], h - 1), *points, (points[-1][0], h - 1)],
                         fill=theme.blend(self._color, 0.15, theme.GLASS_HI), outline="")
        c.create_line(points, fill=self._color, width=2, smooth=True)
