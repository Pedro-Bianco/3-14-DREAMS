"""Whisper só vai para a GPU quando o perfil é NVIDIA e as DLLs CUDA carregam."""

from pidreams.hardware import cuda
from pidreams.hardware.detect import HardwareProfile
from pidreams.stt import transcriber


def _profile(backend):
    return HardwareProfile(backend, None, None, None, None, 0)


def test_cpu_quando_nao_e_nvidia(monkeypatch):
    monkeypatch.setattr("pidreams.hardware.detect.current_profile", lambda: _profile("vulkan"))
    assert transcriber._device() == ("cpu", "int8")


def test_cuda_so_com_dlls(monkeypatch):
    monkeypatch.setattr("pidreams.hardware.detect.current_profile", lambda: _profile("nvidia"))
    monkeypatch.setattr(cuda, "prepare_runtime", lambda: False)
    assert transcriber._device() == ("cpu", "int8")
    monkeypatch.setattr(cuda, "prepare_runtime", lambda: True)
    assert transcriber._device() == ("cuda", "float16")


def test_sem_dlls_instaladas_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setattr(cuda.paths, "models_dir", lambda _k: tmp_path)
    assert cuda.prepare_runtime() is False
