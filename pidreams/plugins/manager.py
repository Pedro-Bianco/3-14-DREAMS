"""PI dreams services that can be turned on and off.

Each service is a capability the agent gains or loses at runtime, with a button
in the panel. Turning it off must be real: the service's tools disappear from the
schema sent to the model.

A configuration error becomes a RuntimeError with a message in Portuguese — the GUI
shows that text straight to the user.
"""

import threading

from pidreams.agent.tools import set_service_enabled


class Service:
    name = ""
    label = ""

    def __init__(self, on_log=None):
        self._on_log = on_log
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def log(self, msg: str) -> None:
        if self._on_log:
            self._on_log(self.name, msg)

    def start(self) -> str:
        raise NotImplementedError

    def stop(self) -> str:
        raise NotImplementedError

    def status(self) -> str:
        return "ligado" if self._running else "desligado"


class CameraService(Service):
    """Opens the webcam (live video in the panel) and exposes the ver_camera tool.
    Off by default: the webcam only stays open while the button is on."""

    name = "camera"
    label = "Câmera"

    def start(self) -> str:
        try:
            import cv2  # noqa: F401
        except ImportError:
            raise RuntimeError("OpenCV não instalado — rode: pip install opencv-python")
        from pidreams.camera import tools
        from pidreams.camera.stream import STREAM

        STREAM.start()                # RuntimeError if the webcam does not open
        tools.register()
        set_service_enabled("camera", True)
        self._running = True
        from pidreams.core.config import CONFIG

        self.log(f"modelo de visão: {CONFIG.vision_model} (carregado só na hora de olhar)")
        return "ferramenta ver_camera liberada"

    def stop(self) -> str:
        set_service_enabled("camera", False)
        self._running = False
        from pidreams.camera.stream import STREAM

        STREAM.stop()
        return "webcam fechada e ferramenta ver_camera bloqueada"

    def status(self) -> str:
        if not self._running:
            return "desligada"
        from pidreams.core.config import CONFIG

        return f"pronta — {CONFIG.vision_model}, webcam {CONFIG.camera_index}"


class MemoryService(Service):
    """Turns use of the long-term memory and the knowledge base on or off.

    When off, nothing from the LTM/KB enters the model's context and nothing new is stored.
    Useful when recall gets in the way instead of helping — writing about a new
    subject, for instance, with old memories pulling toward another topic.
    The data stays on disk; it just stops being looked up.
    """

    name = "memory"
    label = "Memória (LTM + KB)"

    def __init__(self, on_log=None):
        super().__init__(on_log)
        self._running = True          # on by default, as it always was

    def start(self) -> str:
        self._running = True
        return "recall e gravação ativos"

    def stop(self) -> str:
        self._running = False
        return "recall e gravação desativados — os dados continuam no disco"

    def status(self) -> str:
        return "consultando e gravando" if self._running else "desligada (dados preservados)"


_memory_svc: MemoryService | None = None


def memory_active() -> bool:
    """Checked by the agent loop."""
    return _memory_svc is None or _memory_svc.running


class ServiceManager:
    def __init__(self, on_log=None):
        self._lock = threading.Lock()
        self.services: dict[str, Service] = {}
        for cls in (CameraService, MemoryService):
            svc = cls(on_log=on_log)
            self.services[svc.name] = svc
            if isinstance(svc, MemoryService):
                global _memory_svc
                _memory_svc = svc

    def get(self, name: str) -> Service:
        return self.services[name]

    def toggle(self, name: str, start_connection: bool) -> str:
        """Returns the status message. Propagates configuration RuntimeErrors."""
        svc = self.services[name]
        with self._lock:
            return svc.start() if start_connection else svc.stop()

    def stop_all(self) -> None:
        for svc in self.services.values():
            if isinstance(svc, MemoryService):
                continue          # not an external resource to shut down
            if svc.running:
                try:
                    svc.stop()
                except Exception:
                    pass
