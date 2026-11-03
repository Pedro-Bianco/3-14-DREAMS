# PyInstaller — PIDreams.exe (onedir mode, no console). Run through installer/build.ps1.
#
# Kept out of the package on purpose:
#   - AI models: downloaded at install time into %LOCALAPPDATA%\PIDreams\models;
#   - default Piper voice: Inno Setup copies it to {app}\models\piper.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "pidreams" / "ui" / "assets" / "face_mesh.json"), "pidreams/ui/assets"),   # 3D face geometry
    (str(ROOT / "pidreams" / "assets" / "world_110m.json"), "pidreams/assets"),   # Monitoramento globe
    (str(ROOT / "pidreams" / "agent" / "personas"), "pidreams/agent/personas"),
]
datas += collect_data_files("faster_whisper")          # voice filter model (Silero)
datas += collect_data_files("piper")                   # espeak-ng-data (pronunciation)
datas += collect_data_files("fastembed")
datas += collect_data_files("tzdata")                    # calendar time zones (Windows does not ship them)
datas += collect_data_files("tiktoken_ext", include_py_files=True)

binaries = []
binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("piper")              # espeakbridge

hiddenimports = []
hiddenimports += collect_submodules("pidreams")
hiddenimports += collect_submodules("tiktoken_ext")
hiddenimports += ["sounddevice", "PIL.ImageTk", "miniaudio", "sgp4.api", "sgp4.omm"]

a = Analysis(
    [str(ROOT / "installer" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "IPython", "jupyter", "pytest", "torch", "tensorflow"],
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
