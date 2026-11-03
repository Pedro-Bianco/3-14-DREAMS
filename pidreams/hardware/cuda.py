"""CUDA libraries for Whisper on NVIDIA cards.

faster-whisper (ctranslate2) needs cuBLAS 12 and cuDNN 9. The installer puts them in
%LOCALAPPDATA%\\PIDreams\\models\\cuda only on NVIDIA PCs. This is the only place
with CUDA-specific code: the transcriber only
asks "can the GPU be used?".

Source of the DLLs and validation on an NVIDIA PC: pending.
"""

import ctypes
import logging
import os

from pidreams.core import paths

log = logging.getLogger(__name__)

# Loading these two proves ctranslate2 will be able to run on CUDA.
_REQUIRED_DLLS = ("cublas64_12.dll", "cudnn_ops64_9.dll")
_registered = False


def prepare_runtime() -> bool:
    """True if the CUDA DLLs load; False (with the reason in the log) otherwise."""
    global _registered
    folder = paths.models_dir("cuda")
    if not folder.is_dir() or not any(folder.glob("*.dll")):
        log.info("CUDA: libraries not installed in %s; Whisper will use the CPU", folder)
        return False
    if not _registered:
        os.add_dll_directory(str(folder))
        os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"
        _registered = True
    for dll in _REQUIRED_DLLS:
        try:
            ctypes.WinDLL(str(folder / dll))
        except OSError as e:
            log.warning("CUDA: %s did not load (%s); Whisper will use the CPU", dll, e)
            return False
    return True
