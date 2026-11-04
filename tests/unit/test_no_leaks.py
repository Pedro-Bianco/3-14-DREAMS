"""Nenhum dado pessoal ou segredo nos arquivos versionados.

Duas camadas:
1. padrões genéricos (caminho de usuário, e-mail, telefone, formato de chave);
2. termos privados de %LOCALAPPDATA%\\PIDreams\\dev\\leak-terms.txt — fora do
   repositório, porque escrever aqui o nome de alguém para procurá-lo seria o
   próprio vazamento. Um termo por linha; linhas com # são ignoradas.
"""

import os
import re
import subprocess
import unicodedata
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PATTERNS = {
    "caminho de usuário": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!usuario\b|<|%)[A-Za-z0-9._-]+", re.I),
    "e-mail": re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}"),
    "telefone": re.compile(r"(?<!\d)55\d{10,11}(?!\d)"),
    "chave/token": re.compile(
        r"(?i)(api[_-]?key|secret|token|password|senha)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
        r"|\bsk-[A-Za-z0-9]{20,}|\bghp_[A-Za-z0-9]{30,}|\bAKIA[0-9A-Z]{16}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}"
        r"|\bhf_[A-Za-z0-9]{30,}"),
}
# Exemplos e placeholders que podem aparecer.
# git@github.com é o formato padrão de endereço SSH do git; Funcao@biblioteca.dll é
# como o Inno Setup importa funções do Windows. Nenhum dos dois é e-mail de alguém.
ALLOWED_EMAILS = re.compile(
    r"(^git@github\.com|@(example\.(com|org)|users\.noreply\.github\.com|[cg]\.us|lid|\w+\.dll))$", re.I)
SAMPLE_PHONES = {"5511999999999", "5511888888888", "5511000000000"}
# The public repository's own address, allowed only in this exact form (the maintainer agreed,
# 2026-11-03): Wikimedia asks programs to identify themselves with a contact. The username in any
# other context is still a leak.
PUBLIC_PROJECT_URL = "github.com/pedro-bianco/3-14-dreams"
PRIVATE_TERMS = Path(os.environ.get("LOCALAPPDATA", "")) / "PIDreams" / "dev" / "leak-terms.txt"


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _tracked_files() -> list[Path]:
    output = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [ROOT / p for p in output.decode("utf-8").split("\0") if p]


def _private_terms() -> list[str]:
    if not PRIVATE_TERMS.is_file():
        warnings.warn(f"lista privada ausente ({PRIVATE_TERMS}); só os padrões genéricos foram verificados")
        return []
    lines = PRIVATE_TERMS.read_text(encoding="utf-8").splitlines()
    return [_strip_accents(l.strip()) for l in lines if l.strip() and not l.startswith("#")]


def _found(text: str, terms: list[str]) -> list[str]:
    found = []
    for name, default in PATTERNS.items():
        for m in default.finditer(text):
            snippet = m.group(0)
            if name == "e-mail" and ALLOWED_EMAILS.search(snippet):
                continue
            if name == "telefone" and snippet in SAMPLE_PHONES:
                continue
            found.append(name)          # o trecho em si não vai para a saída do teste
    normalized_text = _strip_accents(text).replace(PUBLIC_PROJECT_URL, "")
    found += ["termo da lista privada" for t in terms if t in normalized_text]
    return found


def test_nenhum_vazamento_nos_arquivos_versionados():
    terms = _private_terms()
    problems = {}
    for file in _tracked_files():
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                       # binários (imagens, modelos)
        # Third-party license texts go in verbatim (the license requires it) and are not ours: a
        # private term once matched inside a word of the Apache-2.0 text. E-mail and phone checks
        # still apply to them.
        verbatim = file.relative_to(ROOT).parts[0] == "LICENSES"
        found = _found(text, [] if verbatim else terms)
        if found:
            problems[str(file.relative_to(ROOT))] = sorted(set(found))
    assert not problems, f"possíveis vazamentos: {problems}"
