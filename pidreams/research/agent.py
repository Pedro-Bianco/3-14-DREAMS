"""The deep-research mode's agent: same chat model, its own prompt and two tools. `pesquisar` only
starts the research (job.py) in the background and answers at once; progress milestones and the
final summary go to an announcement queue that the loop speaks between turns. Opening, closing and
cancelling are decided by code in the loop, never by the model."""

import logging
import queue
import re
from datetime import datetime

import ollama

from pidreams.core import paths
from pidreams.core.config import CONFIG
from pidreams.core.settings import SETTINGS
from pidreams.core.text import asks_to_close, asks_to_open
from pidreams.research.job import Cancelled, ResearchJob

log = logging.getLogger(__name__)

OPEN_PHRASES = {"pesquisa profunda", "abre a pesquisa profunda", "abra a pesquisa profunda", "abrir pesquisa profunda",
                "abrir a pesquisa profunda", "modo pesquisa", "modo pesquisa profunda", "entrar na pesquisa profunda"}
CLOSE_PHRASES = {"fechar pesquisa", "fechar a pesquisa", "fechar pesquisa profunda", "fecha a pesquisa",
                 "fechar a pesquisa profunda", "sair da pesquisa", "sair da pesquisa profunda", "voltar ao normal"}
CANCEL_PHRASES = {"cancelar pesquisa", "cancela a pesquisa", "cancelar a pesquisa", "para a pesquisa",
                  "parar pesquisa", "parar a pesquisa", "cancela pesquisa"}


def _phrase(text: str) -> str:
    return " ".join(text.lower().strip(" .,!?").split())


def is_open_request(text: str) -> bool:
    # Up to 6 words: a longer sentence usually brings the topic, which the research agent must read.
    phrase = _phrase(text)
    return phrase in OPEN_PHRASES or asks_to_open(phrase, "pesquisa profunda", max_words=6)


def is_close_request(text: str) -> bool:
    phrase = _phrase(text)
    return phrase in CLOSE_PHRASES or asks_to_close(phrase, "pesquisa")


def is_cancel_request(text: str) -> bool:
    return _phrase(text) in CANCEL_PHRASES


def prompt() -> str:
    name = SETTINGS.get("assistant_name") or "PI dreams"
    treatment = SETTINGS.get("treatment")
    # Measured: "Você é o X no modo Y. Trate o usuário por Z." at the top made qwen2.5:14b answer in
    # Thai or loop until Ollama aborted (3 of 3 requests); "em modo de ..." with the form of address
    # at the end: 0 of 3 (2026-11-03).
    address = f"\nChame o usuário de {treatment}." if treatment else ""
    return (f"Você é o {name}, assistente de voz, agora em modo de pesquisa.\n"
            "Fale em português do Brasil, em frases curtas (a resposta é falada).\n"
            "Quando o usuário pedir uma pesquisa sobre um tema, chame `pesquisar` com o tema. Se o tema for "
            "ambíguo, com mais de um sentido, pergunte antes qual sentido.\n"
            "Se perguntarem como está a pesquisa, chame `andamento_pesquisa`.\n"
            "Nunca responda o conteúdo de uma pesquisa por conta própria: os fatos vêm só do relatório.\n"
            "Se pedirem outra coisa (abrir programas, lembretes, conversa geral), diga que neste modo você só "
            "pesquisa e que, para o resto, é só fechar a Pesquisa profunda." + address)


SCHEMAS = [
    {"type": "function", "function": {
        "name": "pesquisar",
        "description": "Começa uma pesquisa profunda na web sobre um tema (leva de 1 a 3 minutos e gera um relatório com fontes).",
        "parameters": {"type": "object", "properties": {
            "tema": {"type": "string", "description": "O tema da pesquisa, como o usuário disse."}}, "required": ["tema"]}}},
    {"type": "function", "function": {
        "name": "andamento_pesquisa",
        "description": "Diz em que etapa está a pesquisa em andamento.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]

_STEPS = {"esclarecendo": "esperando o usuário escolher as opções mostradas na tela (ainda não começou a buscar)", "planejando": "planejando as perguntas", "buscando": "buscando fontes", "lendo": "lendo as fontes",
          "escrevendo": "escrevendo o relatório", "guardando": "guardando o relatório", "pronta": "pronta",
          "cancelada": "cancelada", "falhou": "falhou"}


def research_model(strong: bool) -> tuple[str, str]:
    """(model, keep_alive): for strong calls, the stronger research model when it is installed;
    otherwise the chat one."""
    from pidreams.hardware import models

    if not strong or CONFIG.research_model == CONFIG.ollama_model:
        return CONFIG.ollama_model, CONFIG.ollama_keep_alive
    try:
        if models.ollama_model_present(CONFIG.research_model):
            return CONFIG.research_model, CONFIG.research_keep_alive
    except Exception as e:          # noqa: BLE001 — Ollama down: the call below says so
        log.warning("[Research] could not list the models: %s", e)
    log.info("[Research] %s not installed, using %s", CONFIG.research_model, CONFIG.ollama_model)
    return CONFIG.ollama_model, CONFIG.ollama_keep_alive


def chat(prompt_text: str, max_tokens: int, cancel, strong: bool = False) -> str:
    """One model call, streamed so a cancel stops it within a fraction of a second. strong=True
    (the report itself) uses the stronger research model; the other steps are short and stay on
    the chat model: the 14b at 2.4 tok/s on every step made a research take ~25 min (2026-11-04)."""
    client = ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s)
    model, keep_alive = research_model(strong)
    parts = []
    for chunk in client.chat(model=model, messages=[{"role": "user", "content": prompt_text}],
                             options={**CONFIG.ollama_options, "num_predict": max_tokens}, think=False,
                             keep_alive=keep_alive, stream=True):
        if cancel.is_set():
            raise Cancelled()
        parts.append(chunk.message.content or "")
    return "".join(parts)


def save_report(kb_store, topic: str, report: str):
    """Into the document base (never replacing an older one: the date is in the name) and as a .md
    file to open. Returns (name in the base, file path)."""
    when = datetime.now()
    # Seconds in the name: two reports on one topic in the same minute had the same name, and the
    # base replaces a text saved again under the same name.
    name = f"Pesquisa: {topic} — {when.strftime('%d/%m/%Y %H:%M:%S')}"
    folder = paths.user_data_dir() / "research"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w]+", "-", topic.lower()).strip("-")[:50] or "pesquisa"
    file = folder / f"{when.strftime('%Y-%m-%d_%H%M%S')}_{slug}.md"
    file.write_text(report, encoding="utf-8")
    if kb_store is not None and kb_store.available:
        kb_store.ingest(report, name)
    return name, file


_ORDINALS = [("primeira", "primeiro", "um", "1", "opção a", "letra a"), ("segunda", "segundo", "dois", "2", "opção b"),
             ("terceira", "terceiro", "três", "tres", "3", "opção c"), ("quarta", "quarto", "quatro", "4", "opção d")]
_ANY = ("tanto faz", "qualquer", "pular", "sem preferência", "sem preferencia", "pode seguir", "não sei", "nao sei")


def match_choices(choices: list[dict], text: str) -> list[str]:
    """Spoken answer → one option per question ("" = no preference). "a segunda", the option's own
    words, or "tanto faz"; with a single question and no match, the answer itself is the preference."""
    said = f" {_phrase(text)} "
    if any(w in said for w in _ANY):
        return [""] * len(choices)
    # Ordinals in the order they were said go to the questions in order ("a primeira" answers only
    # the first question, "a segunda e a primeira" answers two).
    spoken = sorted({said.find(f" {w} "): i for i, words in enumerate(_ORDINALS) for w in words
                     if f" {w} " in said}.items())
    ordinals = [i for _pos, i in spoken]
    picks = []
    for q, c in enumerate(choices):
        pick = c["options"][ordinals[q]] if q < len(ordinals) and ordinals[q] < len(c["options"]) else ""
        if not pick:
            pick = next((o for o in c["options"] if any(len(w) >= 4 and w in said for w in _phrase(o).split())), "")
        picks.append(pick)
    if len(choices) == 1 and not picks[0]:
        picks[0] = text.strip()
    return picks


class ResearchAgentTools:
    def __init__(self, emit, kb_store=lambda: None, chat_fn=chat):
        self._emit, self._kb, self._chat = emit, kb_store, chat_fn
        self.announcements: queue.Queue = queue.Queue()
        self.job: ResearchJob | None = None

    def schemas(self) -> list[dict]:
        return SCHEMAS

    @property
    def running(self) -> bool:
        return self.job is not None and self.job.running

    @property
    def awaiting(self) -> bool:
        """The research is waiting for the answers to its clarifying questions."""
        return self.running and self.job.awaiting

    def answer(self, picks: list[str]) -> None:
        if self.awaiting:
            self.job.answer(picks)

    def answer_text(self, text: str) -> str:
        self.answer(match_choices(self.job.choices, text))
        return "Certo, vou pesquisar com essas preferências."

    def cancel(self) -> bool:
        if not self.running:
            return False
        self.job.cancel.set()
        return True

    def dispatch(self, name: str, args: dict) -> str:
        if name == "pesquisar":
            topic = str(args.get("tema", "")).strip()
            if not topic:
                return "[Erro] A chamada de 'pesquisar' veio sem tema. Chame de novo preenchendo: tema."
            return self.start(topic)
        if name == "andamento_pesquisa":
            if self.job is None:
                return "Nenhuma pesquisa foi feita ainda."
            s = self.job.snapshot()
            return (f"Pesquisa sobre {s['tema']}: {_STEPS.get(s['etapa'], s['etapa'])}; "
                    f"{s['fontes_lidas']} de {s['fontes_total']} fontes lidas, {s['segundos']} s.")
        return f"[Erro] Ferramenta desconhecida: {name}."

    def start(self, topic: str) -> str:
        if self.running:
            return f"Já há uma pesquisa em andamento sobre {self.job.topic}. Espere terminar ou diga 'cancelar pesquisa'."
        self.job = ResearchJob(topic, self._chat, on_progress=lambda s: self._emit("research_progress", s),
                               announce=self.announcements.put,
                               save=lambda t, r: save_report(self._kb(), t, r))
        self.job.start()
        return f"Comecei a pesquisa sobre {topic}. Vou avisando o andamento."
