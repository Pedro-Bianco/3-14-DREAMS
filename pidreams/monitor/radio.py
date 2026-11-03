"""MP3 radio inside the app: miniaudio decodes the stream, sounddevice plays it on the app's
output with its volume and mute. While the assistant talks the radio goes silent but keeps
reading the stream, so it comes back live, not delayed. miniaudio (0.27 MB) instead of PyAV
(28 MB): it only reads MP3, which is 65% of the radios with coordinates (2026-11-02).

The stream is read here, not with miniaudio's IceCastClient: that one asks for the ICY titles
and only hands over audio in whole metadata intervals (seconds each), without a timeout —
measured, 5 of 10 popular radios took over 5 s to start and two never did."""

import logging
import threading
import urllib.request

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

_RATE, _CHANNELS, _FRAMES = 44100, 2, 2048
_CONNECT_TIMEOUT_S = 6
_TRIES = 4                       # stations tried in order when one does not answer


def _source_class():
    import miniaudio

    class HttpStream(miniaudio.StreamableSource):
        """Hands the decoder whatever bytes already arrived (read1), instead of waiting for a block."""

        def __init__(self, url: str):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PI-dreams", "Icy-MetaData": "0"})
            self._resp = urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT_S)

        def read(self, num_bytes: int) -> bytes:
            return self._resp.read1(num_bytes)

        def close(self) -> None:
            self._resp.close()
    return HttpStream


class RadioPlayer:
    def __init__(self, out_device_ref: list, volume_ref: list, mute_ref: list, quiet=lambda: False, on_change=None):
        """quiet(): True while the assistant is working or speaking. on_change(station | None, error | None)."""
        self._device, self._volume, self._mute = out_device_ref, volume_ref, mute_ref
        self._quiet, self._on_change = quiet, on_change or (lambda *_: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.station: dict | None = None

    def play(self, stations, wait_s: float = 0) -> dict | None:
        """Plays the first station (of a list, in order) that answers. With wait_s, waits until the
        sound starts and returns the station that played (None if none did)."""
        stations = [stations] if isinstance(stations, dict) else list(stations)[:_TRIES]
        self.stop()
        self._stop = threading.Event()
        started = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(stations, self._stop, started), daemon=True, name="radio")
        self._thread.start()
        if wait_s:
            started.wait(wait_s)
            return self.station
        return None

    def stop(self) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread = None
        if self.station is not None:
            self.station = None
            self._on_change(None, None)

    def _run(self, stations: list[dict], stop: threading.Event, started: threading.Event) -> None:
        import miniaudio
        HttpStream = _source_class()
        for station in stations:
            source = None
            try:
                source = HttpStream(station["url"])
                frames = miniaudio.stream_any(source, source_format=miniaudio.FileFormat.MP3,
                                              output_format=miniaudio.SampleFormat.SIGNED16,
                                              nchannels=_CHANNELS, sample_rate=_RATE, frames_to_read=_FRAMES)
                first = next(frames)
                kwargs = {"samplerate": _RATE, "channels": _CHANNELS, "dtype": "float32"}
                if self._device[0] is not None:
                    kwargs["device"] = self._device[0]
                with sd.OutputStream(**kwargs) as out:
                    if stop.is_set():
                        return
                    self.station = station
                    started.set()
                    self._on_change(station, None)
                    for chunk in _chain(first, frames):
                        if stop.is_set():
                            return
                        pcm = np.frombuffer(chunk, dtype=np.int16).reshape(-1, _CHANNELS).astype(np.float32) / 32768
                        gain = 0.0 if self._mute[0] or self._quiet() else float(self._volume[0])
                        out.write(pcm * gain)
                return                                      # the stream ended
            except Exception as e:
                log.warning(f"[Radio] {station.get('name')}: {e}")
                if self.station is station:                 # it had started and then dropped
                    self.station = None
                    self._on_change(None, f"A rádio {station.get('name', '')} caiu.")
                    return
            finally:
                if source is not None:
                    try:
                        source.close()
                    except Exception:
                        pass
            if stop.is_set():
                return
        started.set()
        self._on_change(None, "Nenhuma rádio respondeu agora.")


def _chain(first, rest):
    yield first
    yield from rest
