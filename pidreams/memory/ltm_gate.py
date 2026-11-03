
"""Signs that the user has just STATED something about themselves: worth reflecting now instead of
waiting for the next window. (Reading the memory no longer depends on words: since v0.4.0 it is
looked up on every question by similarity.)"""


_CLAIMS_FACT = (
    "eu trabalho", "eu moro", "eu sou", "eu tenho", "me chamo", "meu nome",
    "trabalho na", "trabalho no", "moro em", "moro no", "meu time",
    "minha empresa", "meu cargo", "eu gosto", "eu prefiro", "eu odeio",
    "completei", "comecei", "entrei na", "faço aniversário", "nasci",
    "minha esposa", "meu marido", "meu filho", "minha filha", "meu cachorro",
    "meu gato", "minha mãe", "meu pai", "meu irmão", "minha irmã",
    # changes and instructions: the old fact must be updated or deleted soon
    "vendi", "me mudei", "mudei de", "não tenho mais", "nao tenho mais", "saí da", "sai da",
    "me chama de", "me chame de", "prefiro que", "responde sempre", "responda sempre",
)


def has_personal_fact(text: str) -> bool:
    """True when the message seems to carry a new fact about the user."""
    if not text:
        return False
    normalized = " " + text.lower().strip() + " "
    return any(marker in normalized for marker in _CLAIMS_FACT)
