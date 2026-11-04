"""Depois do assistente, nenhuma variável Tk dele continua viva.

No app instalado em 2026-10-19, as 7 variáveis do assistente ficaram presas num
ciclo de referências e foram recolhidas depois, uma a uma, pelas threads que
carregavam os modelos — 7 erros "main thread is not in main loop" no log.
Reproduzir o momento exato da coleta não é determinístico; verificar que nada
sobra para ser recolhido depois é.
"""

import gc
import tkinter

from pidreams.core.settings import Settings


def _live_variables() -> int:
    return sum(isinstance(o, tkinter.Variable) for o in gc.get_objects())


def test_assistente_nao_deixa_variaveis_para_coleta_tardia(tmp_path, fake_sound, monkeypatch):
    from pidreams.ui import first_run
    import pidreams.__main__ as main

    def finish_direct(self):
        self._step = 2               # etapa de áudio: liga o medidor do microfone
        self._show()
        self._finish()
        return self.finished
    monkeypatch.setattr(first_run.FirstRunWizard, "run", finish_direct)

    gc.collect()
    before = _live_variables()
    gc.disable()                  # só as coletas explícitas do código contam
    try:
        assert main.run_wizard(Settings(tmp_path / "settings.json"))
        leftover = _live_variables() - before
    finally:
        gc.enable()
    assert leftover == 0
