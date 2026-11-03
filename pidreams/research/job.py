"""One deep research, in a thread: plan → search → read → take notes → write → save.

Fixed steps in code with the model at set points, not an agent looping on its own: the time stays
predictable and the report can only cite what was read. The report is written from short notes
(one per source), not from the pages, so 12 sources fit the model's 8192-token window.
"""

import logging
import re
import threading
import time
from datetime import datetime

from pidreams.research import sources

log = logging.getLogger(__name__)

MAX_SOURCES = 12
CLARIFY_WAIT_S = 120     # without an answer to the clarifying questions, the research goes on
_NOTHING = "NADA"

CLARIFY_PROMPT = """\
Tema de pesquisa pedido pelo usuário: {topic}

Antes de pesquisar, escreva de 1 a 3 perguntas de múltipla escolha que ajudem a entender o que o
usuário quer: o sentido do tema (se tiver mais de um), o foco (conceitos, prática, comparação,
história, novidades) ou a profundidade. Perguntas curtas (até 8 palavras) e 2 a 4 opções de até
4 palavras cada. Se o tema já estiver
claro e específico, responda só: {nothing}
Formato, uma pergunta por linha:
Q: pergunta | opção 1 | opção 2 | opção 3"""

PLAN_PROMPT = """\
Tema de pesquisa: {topic}{preferences}

Primeiro, numa linha, a palavra-chave principal do tema (1 a 3 palavras, como se busca em notícias).
Depois divida o tema em 3 a 5 perguntas que, respondidas, cobrem o assunto. Para cada uma, dê um termo
de busca curto em português e outro em inglês. Responda só com as linhas, neste formato:
C: palavra-chave
P: pergunta | busca em português | busca em inglês"""

NOTES_PROMPT = """\
Perguntas da pesquisa:
{questions}

Texto da fonte "{title}":
\"\"\"
{text}
\"\"\"

Anote, em tópicos curtos em português, só os fatos DESTE texto que ajudam a responder às perguntas
(números, datas, nomes, comparações). Não use conhecimento de fora do texto. No máximo 8 tópicos.
Se o texto não ajudar em nenhuma pergunta, responda só: {nothing}"""

WRITE_PROMPT = """\
Tema: {topic}

Perguntas:
{questions}

Anotações das fontes (o número entre colchetes identifica a fonte):
{notes}

Escreva um relatório em português do Brasil usando SÓ essas anotações. Formato:
## Resumo
(3 a 5 frases)
## (uma seção por pergunta, com a pergunta como título)
## Conclusão

Depois de cada afirmação, coloque o número da fonte entre colchetes, como [2] ou [1][3]. Use só os
números acima. Se as fontes discordarem, diga isso citando as duas. Se uma pergunta não tiver
resposta nas anotações, diga que as fontes lidas não trataram dela. Não escreva a lista de fontes."""

SUMMARY_PROMPT = """\
Relatório:
{report}

Resuma em 2 ou 3 frases, para falar em voz alta (sem colchetes nem números de fonte), e termine
dizendo em quais sites a pesquisa se baseou: {sites}."""


def parse_clarify(raw: str) -> list[dict]:
    """[{question, options}] — up to 3 questions with 2 to 4 options; [] when the topic is clear."""
    out = []
    for line in (raw or "").splitlines():
        m = re.match(r"\s*(?:\d+[.)]\s*)?Q\s*:\s*(.+)", line)
        if not m:
            continue
        parts = [p.strip() for p in m.group(1).split("|") if p.strip()]
        if len(parts) >= 3:
            out.append({"question": parts[0], "options": parts[1:5]})
    return out[:3]


def parse_keyword(raw: str, topic: str) -> str:
    """The short key term (for news and one more search); the topic when the model gave none."""
    m = re.search(r"^\s*C\s*:\s*(.+)$", raw, re.MULTILINE)
    return m.group(1).strip()[:60] if m else topic


def parse_plan(raw: str, topic: str) -> list[dict]:
    """[{question, pt, en}] — at most 5; without a usable line, the topic itself."""
    plan = []
    for line in raw.splitlines():
        m = re.match(r"\s*(?:\d+[.)]\s*)?P\s*:\s*(.+)", line)
        if not m:
            continue
        parts = [p.strip() for p in m.group(1).split("|")]
        question = parts[0]
        plan.append({"question": question, "pt": parts[1] if len(parts) > 1 and parts[1] else question,
                     "en": parts[2] if len(parts) > 2 and parts[2] else ""})
    return plan[:5] or [{"question": topic, "pt": topic, "en": ""}]


def clean_citations(report: str, valid: set[int]) -> str:
    """Drops [n] that point to no source that was read (the model sometimes invents a number)."""
    def keep(m):
        return m.group(0) if int(m.group(1)) in valid else ""
    return re.sub(r"\[(\d+)\]", keep, report)


class Cancelled(Exception):
    pass


class ResearchJob:
    def __init__(self, topic: str, chat, on_progress=None, announce=None, save=None):
        """chat(prompt, max_tokens, cancel) -> str; on_progress(dict); announce(text) to speak
        between turns; save(topic, report_md) -> (name in the Base, file path)."""
        self.topic = topic.strip()
        self._chat, self._save = chat, save
        self._progress = on_progress or (lambda _d: None)
        self._announce = announce or (lambda _t: None)
        self.cancel = threading.Event()
        self.state = "planejando"
        self.questions: list[dict] = []
        self.keyword = topic.strip()
        self.choices: list[dict] = []          # clarifying questions shown to the user
        self.preferences: list[str] = []       # what the user chose, fed to the plan
        self.awaiting = False
        self._answered = threading.Event()
        self.sources: list[dict] = []          # candidates, then marked read/notes
        self.read_count = 0
        self.report = ""
        self.summary = ""
        self.saved_as = ""
        self.file = None
        self.error = ""
        self.started = time.time()
        self._thread: threading.Thread | None = None

    # ── running ──

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, daemon=True, name="research")
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _step(self, state: str) -> None:
        if self.cancel.is_set():
            raise Cancelled()
        self.state = state
        self._progress(self.snapshot())

    def snapshot(self) -> dict:
        return {"tema": self.topic, "etapa": self.state, "perguntas": [q["question"] for q in self.questions],
                "fontes_lidas": self.read_count, "fontes_total": len(self.sources),
                "fontes": [{"n": s.get("n"), "title": s["title"], "url": s["url"], "ok": s.get("ok")} for s in self.sources],
                "segundos": int(time.time() - self.started), "arquivo": str(self.file) if self.file else "",
                "resumo": self.summary if self.state == "pronta" else "",
                "aguardando": self.awaiting, "escolhas": self.choices if self.awaiting else []}

    def run(self) -> None:
        try:
            self._clarify()
            self._plan()
            self._gather()
            self._read_and_note()
            self._write()
            self.state = "pronta"
            self._progress(self.snapshot())
            self._announce(self.summary)
        except Cancelled:
            self.state = "cancelada"
            self._progress(self.snapshot())
            self._announce("Pesquisa cancelada.")
        except Exception as e:
            log.warning(f"[Research] failed: {e!r}")
            self.state, self.error = "falhou", str(e)
            self._progress(self.snapshot())
            self._announce("A pesquisa falhou: não consegui terminar agora.")

    # ── steps ──

    def answer(self, choices: list[str]) -> None:
        """The user's picks (one per question; "" = no preference). Lets the research go on."""
        self.preferences = [f"{c['question']} {a}" for c, a in zip(self.choices, choices) if a]
        self._answered.set()

    def _clarify(self) -> None:
        """Multiple-choice questions before searching, to pin down vague topics ("TikTok", "KISS")."""
        self._step("esclarecendo")
        raw = self._chat(CLARIFY_PROMPT.format(topic=self.topic, nothing=_NOTHING), 260, self.cancel)
        self.choices = parse_clarify(raw)
        if not self.choices:
            return
        self.awaiting = True
        self._progress(self.snapshot())
        self._announce("Antes de pesquisar, escolha as opções na tela, ou me diga qual prefere.")
        deadline = time.time() + CLARIFY_WAIT_S
        while not self._answered.wait(0.3):
            if self.cancel.is_set():
                raise Cancelled()
            if time.time() > deadline:
                break                                   # no answer: go on without preferences
        self.awaiting = False

    def _plan(self) -> None:
        self._step("planejando")
        preferences = ("\nO que o usuário quer: " + "; ".join(self.preferences)) if self.preferences else ""
        raw = self._chat(PLAN_PROMPT.format(topic=self.topic, preferences=preferences), 300, self.cancel)
        self.questions = parse_plan(raw, self.topic)
        self.keyword = parse_keyword(raw, self.topic)
        self._announce(f"Vou pesquisar {len(self.questions)} perguntas sobre {self.topic}. Levo uns dois minutos.")

    def _gather(self) -> None:
        self._step("buscando")
        per_question: list[list[dict]] = []
        sources.reset_wiki_limit()
        # Every question in Portuguese AND English (technical topics often only exist in English: "regra
        # KISS" found "Cássia Kis" in Portuguese); each search already brings the articles' openings.
        searches = [{"pt": self.keyword, "en": self.keyword}] + self.questions
        for q in searches:
            found = []
            for search, lang in ((q["pt"], "pt"), (q["en"], "en")):
                if search and not sources.wiki_limited(lang):
                    try:
                        found += sources.wiki_search(search, lang, limit=2)
                    except Exception as e:
                        log.warning(f"[Research] wikipedia {lang}: {e}")
            per_question.append(found)
            if self.cancel.is_set():
                raise Cancelled()
        # The key term's best article in each language is read whole; the others by their opening.
        for hit in per_question[0][:1] + [h for h in per_question[0] if h.get("lang") == "en"][:1]:
            hit.pop("text", None)
        seen, picked = set(), []
        # Round robin across questions, so each one gets sources before any gets a third.
        for rank in range(max((len(f) for f in per_question), default=0)):
            for found in per_question:
                if rank < len(found) and found[rank]["url"] not in seen and len(picked) < MAX_SOURCES - 1:
                    seen.add(found[rank]["url"])
                    picked.append(found[rank])
        # News by the questions' search terms, not the whole topic: "a história do Pix no Brasil"
        # found nothing, while "Pix" does (measured: 2 of 5 topics ended with fewer than 4 sources).
        for terms in dict.fromkeys([self.keyword, self.topic]):
            if len(picked) >= MAX_SOURCES:
                break
            news = sources.news(terms)
            if news:
                picked += news
                break
        self.sources = picked
        self._progress(self.snapshot())

    def _read_and_note(self) -> None:
        self._step("lendo")
        questions = "\n".join(f"- {q['question']}" for q in self.questions)
        keywords = [q["pt"] for q in self.questions] + [q["en"] for q in self.questions] + [self.topic]
        halfway = max(1, len(self.sources) // 2)
        for i, s in enumerate(self.sources, 1):
            if self.cancel.is_set():
                raise Cancelled()
            try:
                if "text" in s:
                    text = s["text"]
                else:
                    text = sources.wiki_text(s["title"], s["lang"])
                text = sources.useful_part(text, keywords)
                if len(text.strip()) < 200 and s["origin"] != "noticias":
                    raise ValueError("sem texto útil")
                note = self._chat(NOTES_PROMPT.format(questions=questions, title=s["title"], text=text, nothing=_NOTHING),
                                  260, self.cancel).strip()
                s["ok"] = True
                s["note"] = "" if note.upper().startswith(_NOTHING) or len(note) < 20 else note
            except Cancelled:
                raise
            except Exception as e:
                log.info(f"[Research] skipped {s['url']}: {e}")
                s["ok"] = False
            self.read_count = sum(1 for x in self.sources if x.get("ok"))
            self._progress(self.snapshot())
            if i == halfway:
                self._announce(f"Li {i} de {len(self.sources)} fontes.")

    def _write(self) -> None:
        useful = [s for s in self.sources if s.get("ok") and s.get("note")]
        if len(useful) < 2:
            if sources.wiki_limited():
                self.summary = ("A Wikipédia limitou as consultas agora, porque foram muitas em pouco tempo, e "
                                "não consegui ler fontes suficientes. Tente de novo em alguns minutos.")
            else:
                self.summary = (f"Não encontrei material suficiente sobre {self.topic} nas fontes que consegui ler. "
                                "Tente um tema mais específico ou outra forma de dizer.")
            self.report = ""
            return
        for n, s in enumerate(useful, 1):
            s["n"] = n
        self._step("escrevendo")
        self._announce("Escrevendo o relatório.")
        notes = "\n\n".join(f"[{s['n']}] {s['title']}:\n{s['note']}" for s in useful)
        questions = "\n".join(f"- {q['question']}" for q in self.questions)
        body = self._chat(WRITE_PROMPT.format(topic=self.topic, questions=questions, notes=notes), 1400, self.cancel)
        body = clean_citations(body.strip(), {s["n"] for s in useful})
        when = datetime.now().strftime("%d/%m/%Y %H:%M")
        refs = "\n".join(f"[{s['n']}] {s['title']} — {s['url']}" for s in useful)
        wiki = any(s["origin"].startswith("wikipedia") for s in useful)
        license_note = "\n\nTextos da Wikipédia sob CC BY-SA 4.0." if wiki else ""
        self.report = f"# Pesquisa: {self.topic}\n\n_{when} · {len(useful)} fontes lidas_\n\n{body}\n\n## Fontes\n{refs}{license_note}\n"
        sites = ", ".join(dict.fromkeys(_site(s) for s in useful))
        self.summary = self._chat(SUMMARY_PROMPT.format(report=body[:3500], sites=sites), 220, self.cancel).strip()
        self.summary = re.sub(r"\[\d+\]", "", self.summary)
        self._step("guardando")
        if self._save:
            self.saved_as, self.file = self._save(self.topic, self.report)


def _site(source: dict) -> str:
    if source["origin"].startswith("wikipedia"):
        return "Wikipédia"
    if source["origin"] == "noticias":
        return "Notícias (" + source["title"].rsplit("(", 1)[-1].rstrip(")") + ")"
    host = re.sub(r"^https?://(www\.)?", "", source["url"]).split("/")[0]
    return host
