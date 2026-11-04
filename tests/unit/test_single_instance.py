"""A segunda instância percebe a primeira e desiste."""

import subprocess
import sys

CODE = "from pidreams.core import single_instance as s; print(s.acquire('janela-de-teste-pidreams'))"


def test_segunda_instancia_e_recusada():
    from pidreams.core import single_instance

    assert single_instance.acquire("janela-de-teste-pidreams") is True
    monday = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True, check=True)
    assert monday.stdout.strip() == "False"
