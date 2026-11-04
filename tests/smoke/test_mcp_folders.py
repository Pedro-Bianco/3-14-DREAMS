"""O servidor de arquivos real não sai das pastas liberadas.

Precisa do Node e dos servidores instalados (pidreams.mcp.runtime); sem eles o teste é pulado
em vez de baixar 35 MB. Para rodar: instale uma vez pelo app (ligar Arquivos) ou
`runtime.instalar`, com LOCALAPPDATA apontando para a mesma pasta.
"""

import os
import subprocess
import time

import pytest

from pidreams.mcp import builtin, runtime
from pidreams.mcp.connections import Connections

SECRET = "conteúdo fictício que não pode vazar"

pytestmark = pytest.mark.skipif(not runtime.is_ready(), reason="Node e servidores MCP não instalados")


@pytest.fixture(scope="module")
def env_vars(tmp_path_factory):
    root_dir = tmp_path_factory.mktemp("sc004")
    allowed, outside = root_dir / "Liberada", root_dir / "Fora"
    allowed.mkdir()
    outside.mkdir()
    (outside / "segredo.txt").write_text(SECRET, encoding="utf-8")
    (allowed / "nota.txt").write_text("nota liberada", encoding="utf-8")
    # Junção (não precisa de administrador) dentro da pasta liberada apontando para fora.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(allowed / "atalho"), str(outside)],
                   capture_output=True, check=True)
    c = Connections(limit_s=20)
    c.start_connection("arquivos", **builtin.launch_params("arquivos", {}, [str(allowed)]))
    end = time.time() + 60
    while c.state("arquivos")[0] == "iniciando" and time.time() < end:
        time.sleep(0.1)
    assert c.state("arquivos")[0] == "conectado"
    yield c, allowed, outside
    c.stop_all()


def _attempts(allowed, outside):
    return [
        ("read_text_file", {"path": str(outside / "segredo.txt")}),
        ("read_text_file", {"path": str(allowed / ".." / "Fora" / "segredo.txt")}),
        ("read_text_file", {"path": "..\\Fora\\segredo.txt"}),
        ("read_text_file", {"path": str(allowed / "atalho" / "segredo.txt")}),
        ("list_directory", {"path": str(outside)}),
        ("search_files", {"path": str(outside), "pattern": "**/*segredo*"}),
        ("move_file", {"source": str(allowed / "nota.txt"), "destination": str(outside / "nota.txt")}),
        ("write_file", {"path": str(outside / "novo.txt"), "content": "x"}),
    ]


def test_nenhum_acesso_fora_das_pastas_liberadas(env_vars):
    connections, allowed, outside = env_vars
    for tool, arguments in _attempts(allowed, outside):
        result = connections.call("arquivos", tool, arguments)
        assert SECRET not in result, (tool, arguments)
        assert "segredo.txt" not in result or "denied" in result.lower(), (tool, arguments)
    assert sorted(os.listdir(outside)) == ["segredo.txt"]          # nada movido nem criado lá
    assert (allowed / "nota.txt").exists()
    assert "nota liberada" in connections.call("arquivos", "read_text_file", {"path": str(allowed / "nota.txt")})
