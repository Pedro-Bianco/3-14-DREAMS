# PyInstaller — PIDreams.exe (onedir mode, no console). Run through installer/build.ps1.
#
# Kept out of the package on purpose:
#   - AI models and voices: downloaded at install time into %LOCALAPPDATA%\PIDreams\models.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "pidreams" / "ui" / "assets" / "face_mesh.json"), "pidreams/ui/assets"),   # 3D face geometry
    (str(ROOT / "pidreams" / "assets" / "world_110m.json"), "pidreams/assets"),   # Monitoramento globe
    (str(ROOT / "pidreams" / "assets" / "world_50m_outline.npy"), "pidreams/assets"),   # globe zoomed in (planes)
    # Only the persona files: copying the folder took its __pycache__ along, compiled with the
    # build machine's absolute path (the code itself is already packaged as modules).
    (str(ROOT / "pidreams" / "agent" / "personas" / "*.json"), "pidreams/agent/personas"),
    (str(ROOT / "pidreams" / "assets" / "voices"), "pidreams/assets/voices"),   # default voice state
    (str(ROOT / "pidreams" / "assets" / "pidreams.ico"), "pidreams/assets"),   # tray icon
]
datas += collect_data_files("faster_whisper")          # voice filter model (Silero)
datas += collect_data_files("pocket_tts")             # default voice: model configs (weights downloaded at install)
datas += collect_data_files("kokoro_onnx")             # Kokoro voices: config.json (model downloaded when chosen)
datas += collect_data_files("espeakng_loader")         # espeak-ng-data (pronunciation)
datas += collect_data_files("fastembed")
datas += collect_data_files("tzdata")                    # calendar time zones (Windows does not ship them)
datas += collect_data_files("tiktoken_ext", include_py_files=True)

binaries = []
binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("espeakng_loader")    # espeak-ng.dll (pronunciation)

hiddenimports = []
hiddenimports += collect_submodules("pidreams")
hiddenimports += collect_submodules("tiktoken_ext")
# SciPy picks its array backends by name at run time; without these the voice failed to load in the
# packaged app (No module named 'scipy._external.array_api_compat.numpy.fft', 2026-11-07).
hiddenimports += collect_submodules("scipy._external.array_api_compat")
hiddenimports += collect_submodules("kokoro_onnx") + collect_submodules("phonemizer")   # imported lazily
hiddenimports += ["sounddevice", "PIL.ImageTk", "miniaudio", "sgp4.api", "sgp4.omm"]
# Speech recognition on Intel GPUs (OpenVINO, stt/openvino_whisper.py). Only what it runs is kept (see
# _OPENVINO_UNUSED): the full wheels are ~250 MB, mostly the NPU compiler and model-format readers.
binaries += collect_dynamic_libs("openvino") + collect_dynamic_libs("openvino_genai")
binaries += collect_dynamic_libs("openvino_tokenizers")
datas += collect_data_files("openvino", includes=["libs/*.json"])
hiddenimports += ["openvino", "openvino_genai", "openvino_tokenizers"]
_OPENVINO_UNUSED = ("openvino_intel_npu", "_frontend.dll", "openvino_auto_batch_plugin", "openvino_hetero_plugin",
                    "openvino_auto_plugin", "tbbmalloc_proxy")
_OPENVINO_KEPT = ("openvino_ir_frontend.dll",)        # the reader of the model files themselves

a = Analysis(
    [str(ROOT / "installer" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # PyTorch is needed by the default voice (pocket-tts). starlette and uvicorn stay: the MCP library
    # imports them on start (leaving them out made v0.9.0 and v0.9.1 fail to open).
    # openvino_telemetry: OpenVINO's usage statistics, not needed to run (checked on 2026-11-09).
    excludes=["matplotlib", "IPython", "jupyter", "pytest", "tensorflow", "torchvision", "torchaudio", "fastapi",
              "openvino_telemetry", "openvino.tools", "openvino.frontend.tensorflow", "openvino.frontend.pytorch",
              "openvino.frontend.onnx", "openvino.frontend.paddle", "openvino.frontend.jax"],
    noarchive=False,
)
a.binaries = [b for b in a.binaries
              if b[0].endswith(_OPENVINO_KEPT) or not any(part in b[0] for part in _OPENVINO_UNUSED)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PIDreams",
    console=False,
    icon=str(ROOT / "pidreams" / "assets" / "pidreams.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PIDreams")
