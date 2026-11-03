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


def main():
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
