"""Master volume and mute of the default output device (Windows Core Audio through ctypes COM)
and the media keys. No extra dependency: pycaw would add comtypes for these few calls.

Measured 2026-11-01: reading volume + mute takes ~18 ms, no administrator rights needed.
"""

import ctypes
import ctypes.wintypes as wt
import uuid
from contextlib import contextmanager

_CLSID_ENUMERATOR = "BCDE0395-E52F-467C-8E3D-C4579291692E"
_IID_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
_IID_ENDPOINT_VOLUME = "5CDF2C82-841E-4546-9722-0CF74078229A"
_CLSCTX_ALL = 23
_RPC_E_CHANGED_MODE = -2147417850 & 0xFFFFFFFF

# Virtual-key codes of the media keys; "pause" and "play" share the same key.
_MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
_KEYEVENTF_KEYUP = 0x2


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        u = uuid.UUID(text)
        super().__init__(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def _method(ptr, index: int, *argtypes):
    """COM method index of the interface's vtable (0–2 are IUnknown)."""
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[index])


def _release(ptr) -> None:
    if ptr:
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(ptr)


@contextmanager
def _endpoint():
    """IAudioEndpointVolume of the default render device, released on exit."""
    ole32 = ctypes.OleDLL("ole32")
    try:
        ole32.CoInitializeEx(None, 0)          # tools run on worker threads: init per call
    except OSError as e:                       # already initialized in another mode: fine
        if (e.winerror or 0) & 0xFFFFFFFF != _RPC_E_CHANGED_MODE:
            raise
    enumerator, device, endpoint = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        ole32.CoCreateInstance(ctypes.byref(_GUID(_CLSID_ENUMERATOR)), None, 1,
                               ctypes.byref(_GUID(_IID_ENUMERATOR)), ctypes.byref(enumerator))
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eMultimedia)
        _method(enumerator, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
            enumerator, 0, 1, ctypes.byref(device))
        # IMMDevice::Activate(IAudioEndpointVolume)
        _method(device, 3, ctypes.POINTER(_GUID), wt.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            device, ctypes.byref(_GUID(_IID_ENDPOINT_VOLUME)), _CLSCTX_ALL, None, ctypes.byref(endpoint))
        yield endpoint
    finally:
        for ptr in (endpoint, device, enumerator):
            _release(ptr)


def get_volume() -> int:
    level = ctypes.c_float()
    with _endpoint() as ep:
        _method(ep, 9, ctypes.POINTER(ctypes.c_float))(ep, ctypes.byref(level))   # GetMasterVolumeLevelScalar
    return round(level.value * 100)


def set_volume(percent: int) -> None:
    with _endpoint() as ep:
        _method(ep, 7, ctypes.c_float, ctypes.c_void_p)(ep, percent / 100, None)  # SetMasterVolumeLevelScalar


def get_mute() -> bool:
    muted = wt.BOOL()
    with _endpoint() as ep:
        _method(ep, 15, ctypes.POINTER(wt.BOOL))(ep, ctypes.byref(muted))           # GetMute
    return bool(muted.value)


def set_mute(muted: bool) -> None:
    with _endpoint() as ep:
        _method(ep, 14, wt.BOOL, ctypes.c_void_p)(ep, muted, None)                 # SetMute


def media_key(name: str) -> None:
    """Same as pressing the keyboard key: the player Windows considers active reacts."""
    vk = _MEDIA_KEYS[name]
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
