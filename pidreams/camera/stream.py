"""Camera kept open while the service is on.

The panel shows the live video and the ver_camera tool uses the latest frame from
here instead of opening the camera again: the same webcam opened twice at once
usually fails on Windows. This way the user sees exactly what the model will
receive.
"""

import threading
import time

import cv2

from pidreams.core.config import CONFIG


class CameraStream:
    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None            # latest BGR frame, not mirrored
        self._cap = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_snapshot: list = []

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Opens the camera right here (synchronously) so the error reaches the caller."""
        if self.running:
            return
        # CAP_DSHOW opens much faster on Windows than the default backend (MSMF).
        cap = cv2.VideoCapture(CONFIG.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(
                f"não consegui abrir a câmera {CONFIG.camera_index} "
                "(outro programa usando, ou permissão de câmera negada no Windows)"
            )
        self._cap = cap
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None
        if self._cap is not None:
            self._cap.release()       # turns off the webcam light
            self._cap = None
        with self._lock:
            self._frame = None

    def _loop(self) -> None:
        failures = 0
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok:
                failures += 1
                if failures > 50:       # ~5 s without a picture: camera disconnected
                    break
                time.sleep(0.1)
                continue
            failures = 0
            with self._lock:
                self._frame = frame

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def snapshot(self):
        """Frame that goes to the model — tells the panel to flash the border."""
        frame = self.latest()
        if frame is not None:
            for cb in list(self._on_snapshot):
                try:
                    cb()
                except Exception:
                    pass
        return frame

    def on_snapshot(self, cb) -> None:
        if cb not in self._on_snapshot:
            self._on_snapshot.append(cb)


STREAM = CameraStream()
