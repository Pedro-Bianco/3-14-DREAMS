"""Tray mode: settings, start with Windows, game detection and the wake message."""

import json
import sys
import time
import tkinter as tk
import winreg
from types import SimpleNamespace

import pytest

from pidreams.core.settings import Settings
from pidreams.pc import games, startup

TEST_KEY = r"Software\PIDreamsTest\Run"


def test_tray_defaults_are_off(tmp_path):
    s = Settings(tmp_path / "settings.json")
    assert s.get("tray") == {"start_with_windows": False, "close_to_tray": False, "idle_minutes": 10,
                             "claps": True, "clap_level": 0.2, "games": [],
                             "speak_reminders": True}


def test_invalid_tray_values_fall_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"tray": {"idle_minutes": 0, "games": ["jogo.exe", 3], "claps": "sim"}}),
                    encoding="utf-8")
    s = Settings(path)
    assert s.get("tray.idle_minutes") == 10
    assert s.get("tray.games") == []
    assert s.get("tray.claps") is True
    with pytest.raises(ValueError):
        s.set("tray.idle_minutes", 241)
    s.set("tray.games", ["jogo.exe"])
    assert s.get("tray.games") == ["jogo.exe"]


@pytest.fixture
def test_run_key():
    yield TEST_KEY
    for path in (TEST_KEY, r"Software\PIDreamsTest"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def test_start_with_windows_writes_and_removes(test_run_key):
    assert not startup.is_enabled(test_run_key)
    startup.set_enabled(True, test_run_key)
    assert startup.is_enabled(test_run_key)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, test_run_key) as key:
        value, _ = winreg.QueryValueEx(key, startup.VALUE_NAME)
    assert value.endswith("--tray")
    startup.set_enabled(False, test_run_key)
    startup.set_enabled(False, test_run_key)            # already off: no error
    assert not startup.is_enabled(test_run_key)


def test_packaged_app_starts_itself_in_the_tray(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\PI dreams\PIDreams.exe")
    assert startup.command() == r'"C:\Program Files\PI dreams\PIDreams.exe" --tray'


def _processes(*names):
    return lambda attrs: [SimpleNamespace(info={"name": n}) for n in names]


def test_listed_game_is_found(monkeypatch):
    monkeypatch.setattr(games, "_fullscreen_d3d", lambda: False)
    monkeypatch.setattr(games.psutil, "process_iter", _processes("explorer.exe", "Jogo.EXE"))
    assert games.game_running(["jogo.exe"]) == "jogo.exe"
    assert games.game_running(["outro.exe", " "]) is None
    assert games.game_running([]) is None


def test_full_screen_game_is_found_without_a_list(monkeypatch):
    monkeypatch.setattr(games, "_fullscreen_d3d", lambda: True)
    assert games.game_running([]) == "full-screen game"


def test_second_copy_wakes_the_resident_one():
    from pidreams.ui import tray

    root = tk.Tk()
    root.withdraw()
    woken = []
    icon = tray.TrayIcon(on_wake=lambda: woken.append(1), on_claps=lambda on: None, on_quit=lambda: None)
    try:
        assert tray.wake_running_copy()
        end = time.time() + 2
        while not woken and time.time() < end:
            root.update()                 # Tk's loop dispatches the message window's messages
            time.sleep(0.01)
        assert woken
    finally:
        icon.destroy()
        root.destroy()
