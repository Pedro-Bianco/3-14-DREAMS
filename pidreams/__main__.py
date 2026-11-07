import asyncio
import gc
import sys

# `--mcp <name>`: the app starts one of its own MCP servers (e.g. Gmail) as a child process over
# stdio. This must run before logging is set up: with a console, logging writes to stdout, which
# here is the protocol channel — any extra line corrupts the conversation with the client.
if "--mcp" in sys.argv:
    from pidreams.mcp import ical_calendar, gmail

    servers = {"gmail": gmail.SERVER, "agenda": ical_calendar.SERVER}
    servers[sys.argv[sys.argv.index("--mcp") + 1]].run("stdio")
    sys.exit(0)

from pidreams.core import logging_setup, migrate_legacy, paths  # noqa: E402

log = logging_setup.setup()


def download_essential_models() -> int:
    """PIDreams.exe --setup-models: called by the installer; shows progress in its own
    window (the exe has no console) and returns 0 only if everything is ready."""
    from pidreams.hardware import models
    from pidreams.ui.download_dialog import DownloadDialog

    try:
        models.ensure_ollama()
    except models.DownloadFailed as e:
        log.error("%s", e)
        return 1
    window = DownloadDialog(None, "PI dreams — baixando modelos", models.essentials())
    window.window.mainloop()
    log.info("Essential models: %s", "ready" if window.ok else "; ".join(window.failures))
    return 0 if window.ok else 1


def run_wizard(settings) -> bool:
    from pidreams.ui.first_run import FirstRunWizard

    wizard = FirstRunWizard(settings)
    finished = wizard.run()
    # The wizard's Tk variables must die HERE, on the main thread: collected later by
    # an app thread, each one logged "main thread is not in main loop" (seen 2026-10-19).
    del wizard
    gc.collect()
    return finished


def check_imports() -> int:
    """PIDreams.exe --check-imports: imports every module of the app, as packaged, and says one
    sentence with the default voice when its files are there. The build runs it: v0.9.0 and v0.9.1
    shipped without starlette (MCP needs it) and did not even open, while every test passed from the
    source. Failures go to logs/check-imports.log; 0 = all imported."""
    import importlib
    import pkgutil

    import pidreams

    failures = []
    for module in pkgutil.walk_packages(pidreams.__path__, "pidreams."):
        try:
            importlib.import_module(module.name)
        except Exception as e:                    # noqa: BLE001 — every failure is reported, not just the first
            failures.append(f"{module.name}: {type(e).__name__}: {e}")
    # What the app only loads when it is used: the GPU globe and the voice, which once imported fine and
    # then failed on its first sentence (a SciPy module picked at run time).
    try:
        importlib.import_module("OpenGL.GL")
    except Exception as e:                        # noqa: BLE001
        failures.append(f"OpenGL.GL: {type(e).__name__}: {e}")
    from pidreams.hardware import models
    if models.pocket_present():
        try:
            from pidreams.audio.pocket import PocketVoice
            if not sum(len(c) for c in PocketVoice("baritono.safetensors").stream("Teste da voz.")):
                failures.append("voice: no audio")
        except Exception as e:                    # noqa: BLE001
            failures.append(f"voice: {type(e).__name__}: {e}")
    (paths.logs_dir() / "check-imports.log").write_text("\n".join(failures) or "ok", encoding="utf-8")
    return 1 if failures else 0


def main():
    if "--check-imports" in sys.argv:
        paths.ensure_dirs()
        sys.exit(check_imports())
    from pidreams.ui import theme

    theme.enable_dpi_awareness()     # before any window, or Windows blurs it at 125%+
    paths.ensure_dirs()
    migrate_legacy.migrate()
    migrate_legacy.reuse_caches()
    if "--setup-models" in sys.argv:
        sys.exit(download_essential_models())

    if "--cli" in sys.argv:
        from pidreams.agent.loop import run_agent
        print("=" * 50)
        print("  Agent LLM Local - Modo Terminal")
        print("=" * 50)
        try:
            asyncio.run(run_agent())
        except KeyboardInterrupt:
            print("\n[Interrompido]")
    else:
        from pidreams.core import single_instance
        from pidreams.ui.main_window import WINDOW_TITLE, AgentApp
        if not single_instance.acquire(WINDOW_TITLE):
            return
        from pidreams.core.settings import SETTINGS
        if not SETTINGS.get("first_run_done") and not run_wizard(SETTINGS):
            return                  # wizard closed: it opens again next time
        app = AgentApp()
        logging_setup.install_on_tk(app.root)
        app.run()


if __name__ == "__main__":
    main()
