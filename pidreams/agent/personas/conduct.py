"""Personas and the system prompt built from them.

Prompt = identity + persona style + form of address + conduct rules.
The conduct rules apply to every persona and live only here (DRY).
"""

import json
import logging
from pathlib import Path

from pidreams.core.text import today_in_words

log = logging.getLogger(__name__)

_FOLDER = Path(__file__).resolve().parent
DEFAULT_PERSONA = "espirituoso"
_RENAMED = {"jarvis": "espirituoso"}      # ids saved by older versions

CONDUCT_RULES = """Regras ABSOLUTAS — nunca quebre estas regras:
- Responda SEMPRE e EXCLUSIVAMENTE em português do Brasil, independentemente do idioma em que o usuário escrever.
- NUNCA use emojis ou emoticons em nenhuma resposta.
- NUNCA escreva qualquer palavra ou frase em inglês (exceto nomes próprios ou termos técnicos sem tradução).
- Seja conciso — o usuário ouvirá a resposta em voz alta, então evite respostas longas.
- Use as ferramentas disponíveis quando o usuário pedir para abrir apps, pesquisar na web ou usar a área de transferência.
- Quando o usuário enviar uma URL ou link (http:// ou https://), use IMEDIATAMENTE a ferramenta scrape_url para ler o conteúdo antes de responder.
- Se a ferramenta ver_camera estiver disponível e o usuário perguntar se você o vê, ou
  qualquer coisa sobre a aparência dele, o que ele segura, mostra ou veste, CHAME
  ver_camera antes de responder — a pergunta já é o pedido. Sem a ferramenta, diga
  que a câmera está desligada no painel.
- Fora dos casos de URL e câmera, não use ferramentas por iniciativa própria sem o usuário solicitar.
- NUNCA diga que fez algo sem ter chamado a ferramenta correspondente: anunciar uma
  ação sem chamá-la é mentir para o usuário.
- Se um termo do pedido parecer nome de empresa, produto ou projeto (ex.: "2 anos
  de Orbita"), trate como nome próprio. Não invente um sentido literal para ele.
- Se não souber algo, admita honestamente.
"""


def list_items() -> list[dict]:
    personas = []
    for file in sorted(_FOLDER.glob("*.json")):
        try:
            personas.append(json.loads(file.read_text(encoding="utf-8")))
        except ValueError:
            log.warning("Invalid persona ignored: %s", file.name)
    return sorted(personas, key=lambda p: p.get("id") != DEFAULT_PERSONA)   # default first


def load(persona_id: str) -> dict:
    persona_id = _RENAMED.get(persona_id, persona_id)
    by_id = {p["id"]: p for p in list_items()}
    if persona_id not in by_id:
        log.warning("Persona '%s' does not exist; using '%s'", persona_id, DEFAULT_PERSONA)
    return by_id.get(persona_id) or by_id[DEFAULT_PERSONA]


def sample_phrase(persona: dict, treatment: str) -> str:
    if treatment:
        return persona["example_line"].replace("{tratamento}", treatment)
    return persona["example_line"].replace(", {tratamento}", "").replace(" {tratamento}", "")


def _treatment_rule(treatment: str) -> str:
    if treatment:
        return f'- Chame o usuário de "{treatment}" de forma natural, sem repetir em toda frase.'
    return "- Não use um vocativo fixo para o usuário."


def build_prompt(settings) -> str:
    persona = load(settings.get("persona_id"))
    name = settings.get("assistant_name")
    treatment = settings.get("treatment").strip()
    return (
        f"Você é {name}, um assistente de voz pessoal rodando localmente no computador do usuário.\n\n"
        f"Personalidade:\n{persona['style']}\n{_treatment_rule(treatment)}\n\n"
        f"{CONDUCT_RULES}\n\n"
        # In the system prompt, not in the message: at the start of the message the date hurt
        # tool choice on all three models and was even copied as "o que você falou".
        # Only the day: the time would change every minute and invalidate Ollama's cache;
        # the agent rebuilds this prompt when the day turns.
        f"Data de hoje, pelo relógio do computador: {today_in_words()}. Use-a para \"hoje\", "
        f"\"amanhã\" e datas em pesquisas."
    )
