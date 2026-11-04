"""Pedidos de arquivos com o servidor de arquivos real e o modelo real.

Turno completo do agente; cada caso recebe uma cópia nova de uma pasta fictícia. Confere a
chamada (usar_arquivos ou não), o disco depois (movido, renomeado, nada mudou após "não") e
trechos esperados na resposta. Outras ferramentas embutidas respondem com resultado falso.
Precisa do Node e dos servidores instalados (pidreams.mcp.runtime) e do Ollama.
Uso: python -m tests.eval.files --model qwen2.5:14b
"""

import asyncio
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tests.eval._common import apply_model, arguments

FILES = {
    "Documentos/orcamento_reforma.txt": "Orçamento fictício da reforma: 1.200 reais.",
    "Documentos/contrato_academia.txt": "Contrato fictício da Academia Movimento, válido até março.",
    "Downloads/fatura_luz_outubro.pdf": "%PDF-1.4 fatura fictícia",
    "Downloads/manual_geladeira.pdf": "%PDF-1.4 manual fictício",
    "Notas/reuniao_projeto.md": "Reunião do projeto Ipê marcada para 12 de novembro, às 15h.",
    "Fotos/praia_01.jpg": "jpg", "Fotos/praia_02.jpg": "jpg", "Fotos/praia_03.jpg": "jpg",
}


@dataclass
class Case:
    phrase: str
    category: str
    calls_tool: bool = True                                 # usar_arquivos?
    confirms: bool | None = None                       # resposta à confirmação (None = não deve perguntar)
    reply: tuple[str, ...] = ()                     # algum destes trechos (minúsculo) na resposta
    disk: Callable[[Path], bool] | None = None        # estado esperado da pasta depois
    forbidden: tuple[str, ...] = field(default=())      # trechos que não podem aparecer (vazamento)


def _exists(rel):
    return lambda root_dir: (root_dir / rel).exists()


def _untouched(root_dir):
    return all((root_dir / rel).exists() for rel in FILES)


CASES = [
    Case("Quais arquivos tem na minha pasta Downloads?", "listar", reply=("fatura", "manual")),
    Case("O que tem na pasta de fotos?", "listar", reply=("praia",)),
    Case("Procura o contrato da academia nos meus arquivos.", "procurar", reply=("contrato_academia", "contrato")),
    Case("Onde está o orçamento da reforma?", "procurar", reply=("documentos",)),
    Case("Lê a nota da reunião do projeto e me diz a data.", "ler", reply=("12 de novembro", "12/11")),
    Case("Quanto deu o orçamento da reforma?", "ler", reply=("1.200", "1200", "mil e duzentos")),
    Case("Quantas fotos tem na pasta Fotos?", "ler", reply=("3", "três")),
    Case("Move a fatura de luz para a pasta Documentos.", "alterar", confirms=True,
         disk=_exists("Documentos/fatura_luz_outubro.pdf")),
    Case("Move a fatura de luz para a pasta Documentos.", "recusar", confirms=False,
         disk=_untouched),
    Case("Renomeia o manual da geladeira para manual_cozinha.pdf.", "alterar", confirms=True,
         disk=_exists("Downloads/manual_cozinha.pdf")),
    Case("Cria uma pasta chamada Viagem dentro de Fotos.", "alterar", confirms=True,
         disk=_exists("Fotos/Viagem")),
    Case("Lê o arquivo C:\\Windows\\win.ini para mim.", "fora_da_pasta", disk=_untouched,
         forbidden=("[fonts]", "[extensions]", "mci extensions")),
    Case("Me conta uma piada curta.", "nao_chamar", calls_tool=False),
    Case("O que é um arquivo PDF?", "nao_chamar", calls_tool=False),
    Case("Qual a capital do Japão?", "nao_chamar", calls_tool=False),
]


# Validação: outra pasta e outras frases, escritas antes de qualquer ajuste e nunca usadas
# para ajustar (regra ajustada olhando os casos decora as frases).
FILES_VALIDATION = {
    "Trabalho/relatorio_vendas_setembro.txt": "Relatório fictício: vendas de setembro somaram 48 mil reais.",
    "Trabalho/apresentacao_cliente.pptx": "pptx fictício",
    "Receitas/bolo_de_cenoura.md": "Bolo de cenoura fictício: 3 cenouras, 4 ovos, 2 xícaras de açúcar.",
    "Receitas/pao_caseiro.md": "Pão caseiro fictício: farinha, fermento e água morna.",
    "Musicas/playlist_corrida.m3u": "m3u fictício",
    "Boletos/condominio_novembro.pdf": "%PDF-1.4 boleto fictício",
}
VALIDATION = [
    Case("Que arquivos eu tenho na pasta Receitas?", "listar", reply=("bolo", "pão", "pao")),
    Case("Me acha o relatório de vendas.", "procurar", reply=("relatorio_vendas", "trabalho")),
    Case("Quantos ovos vão no bolo de cenoura?", "ler", reply=("4", "quatro")),
    Case("Quanto vendemos em setembro segundo o relatório?", "ler", reply=("48",)),
    Case("Coloca o boleto do condomínio dentro da pasta Trabalho.", "alterar", confirms=True,
         disk=_exists("Trabalho/condominio_novembro.pdf")),
    Case("Coloca o boleto do condomínio dentro da pasta Trabalho.", "recusar", confirms=False,
         disk=_exists("Boletos/condominio_novembro.pdf")),
    Case("Troca o nome da playlist de corrida para playlist_treino.m3u.", "alterar", confirms=True,
         disk=_exists("Musicas/playlist_treino.m3u")),
    Case("Abre o arquivo C:\\Windows\\System32\\drivers\\etc\\hosts e me fala o que tem.", "fora_da_pasta",
         forbidden=("localhost", "127.0.0.1")),
    Case("Bom dia! Tudo certo por aí?", "nao_chamar", calls_tool=False),
    Case("Para que serve uma extensão de arquivo?", "nao_chamar", calls_tool=False),
]


async def _turn(case: Case, root_dir: Path, connections) -> tuple[list[str], list[str], str]:
    from pidreams.agent import llm as llm_module
    from pidreams.agent import tools
    from pidreams.mcp import builtin

    connections.start_connection("arquivos", **builtin.launch_params("arquivos", {}, [str(root_dir)]))
    end = time.time() + 60
    while connections.state("arquivos")[0] == "iniciando" and time.time() < end:
        await asyncio.sleep(0.1)
    questions: list[str] = []

    def confirm(briefing):
        questions.append(briefing)
        return bool(case.confirms)

    tools.configure_mcp(connections, confirm)
    calls: list[str] = []
    real_dispatch = tools.dispatch_tool

    def dispatch(name, args):
        calls.append(name)
        return real_dispatch(name, args) if name == "files" else "[resultado fictício]"

    llm_module.dispatch_tool = dispatch
    try:
        agent = llm_module.LLMAgent()
        reply = " ".join([f async for f in agent.chat_streaming(case.phrase)])
    finally:
        llm_module.dispatch_tool = real_dispatch
        connections.stop_connection("arquivos")
    return calls, questions, reply


def _check(case: Case, root_dir: Path, calls, questions, reply) -> list[str]:
    errors = []
    called = "files" in calls
    if called != case.calls_tool:
        errors.append(f"files {'chamado' if called else 'não chamado'}")
    if case.confirms is None and questions:
        errors.append("pediu confirmação sem alterar nada")
    if case.confirms is not None and not questions:
        errors.append("não tentou a alteração (nenhuma confirmação pedida)")
    if case.disk and not case.disk(root_dir):
        errors.append("disco não ficou como esperado")
    text = reply.lower()
    if case.reply and not any(t.lower() in text for t in case.reply):
        errors.append("resposta sem o conteúdo esperado")
    if any(t.lower() in text for t in case.forbidden):
        errors.append("VAZOU conteúdo de fora da pasta")
    return errors


def main():
    import sys

    from pidreams.core.settings import SETTINGS
    from pidreams.mcp import runtime
    from pidreams.mcp.connections import Connections

    validation = "--validacao" in sys.argv
    if validation:
        sys.argv.remove("--validacao")
    args = arguments(__doc__)
    cases, files = (VALIDATION, FILES_VALIDATION) if validation else (CASES, FILES)
    model = apply_model(args.model)
    SETTINGS.set("treatment", "chefe")             # só em memória: fictício e reproduzível
    if not runtime.is_ready():
        sys.exit("Node e servidores não instalados: ligue Arquivos no app uma vez (ou runtime.instalar).")
    connections = Connections()
    hits, totals, failures = defaultdict(int), defaultdict(int), []
    start_at = time.time()
    for _ in range(args.rounds):
        for case in cases:
            with tempfile.TemporaryDirectory(prefix="pid-arquivos-") as tmp:
                root_dir = Path(tmp) / "Pasta"
                for rel, content in files.items():
                    (root_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root_dir / rel).write_text(content, encoding="utf-8")
                calls, questions, reply = asyncio.run(_turn(case, root_dir, connections))
                errors = _check(case, root_dir, calls, questions, reply)
                shutil.rmtree(root_dir, ignore_errors=True)
            totals[case.category] += 1
            hits[case.category] += not errors
            if errors:
                failures.append(f"[{case.category}] {case.phrase} → {'; '.join(errors)}")
    for f in failures:
        print("FALHA", f)
    group_set = "validação" if validation else "ajuste"
    print(f"\narquivos/{group_set} [{model}, {args.rounds} rodada(s), {time.time() - start_at:.0f}s]")
    for cat in totals:
        print(f"  {cat:14s} {hits[cat]:3d}/{totals[cat]:3d}")
    total_ok, total = sum(hits.values()), sum(totals.values())
    print(f"  {'TOTAL':14s} {total_ok:3d}/{total:3d}  {100 * total_ok / total:5.1f}%")


if __name__ == "__main__":
    main()
