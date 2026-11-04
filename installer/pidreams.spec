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
    (str(ROOT / "pidreams" / "agent" / "personas"), "pidreams/agent/personas"),
    (str(ROOT / "pidreams" / "assets" / "voices"), "pidreams/assets/voices"),   # default voice state
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
hiddenimports += collect_submodules("kokoro_onnx") + collect_submodules("phonemizer")   # imported lazily
hiddenimports += ["sounddevice", "PIL.ImageTk", "miniaudio", "sgp4.api", "sgp4.omm"]

a = Analysis(
    [str(ROOT / "installer" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # PyTorch is needed by the default voice (pocket-tts); its web server parts are not.
    excludes=["matplotlib", "IPython", "jupyter", "pytest", "tensorflow", "torchvision", "torchaudio",
              "fastapi", "uvicorn", "starlette", "typer"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PIDreams",
    console=False,
    icon=str(ROOT / "installer" / "assets" / "pidreams.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PIDreams")
