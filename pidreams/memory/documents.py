"""Text of the documents saved to the knowledge base, with where each piece came from.

PDF uses pypdf (0.65 s for 100 pages, measured 2026-11-01). Word, PowerPoint and Excel files are zip
packages of XML: reading them directly avoids three libraries (one of them needs lxml) just to get
the text.
"""

import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt", ".md"}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PARAGRAPHS_PER_PIECE = 20           # Word has no page numbers in the file: "trecho N" groups paragraphs
_ROWS_PER_PIECE = 40


class Unreadable(Exception):
    """The file cannot be saved; the message is shown to the person as is."""


def kind_of(path: str | Path) -> str:
    return Path(path).suffix.lower().lstrip(".")


def read(path: str | Path) -> list[tuple[str, str]]:
    """[(where, text)] — where is "p. 3", "slide 5", "aba Vendas", "trecho 2" or "linha 41"."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise Unreadable(f"Formato não suportado ({suffix or 'sem extensão'}).")
    try:
        pieces = _READERS[suffix](path)
    except Unreadable:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError):
        raise Unreadable("O arquivo está corrompido ou não é do formato que a extensão diz.") from None
    except Exception as e:
        raise Unreadable(f"Não consegui ler o arquivo ({type(e).__name__}).") from None
    pieces = [(where, text.strip()) for where, text in pieces if text and text.strip()]
    if not pieces:
        raise Unreadable("O arquivo não tem texto para guardar.")
    return pieces


def _pdf(path: Path) -> list[tuple[str, str]]:
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise Unreadable("O PDF é protegido por senha.")
        pages = [(f"p. {i}", page.extract_text() or "") for i, page in enumerate(reader.pages, 1)]
    except FileNotDecryptedError:
        raise Unreadable("O PDF é protegido por senha.") from None
    except PdfReadError:
        raise Unreadable("O PDF está corrompido.") from None
    if not any(text.strip() for _, text in pages):
        raise Unreadable("É um PDF de imagem (escaneado): não há texto para ler, só figuras das páginas.")
    return pages


def _docx(path: Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    paragraphs = ["".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
    paragraphs = [p for p in paragraphs if p.strip()]
    return [(f"trecho {n}", "\n".join(paragraphs[i:i + _PARAGRAPHS_PER_PIECE]))
            for n, i in enumerate(range(0, len(paragraphs), _PARAGRAPHS_PER_PIECE), 1)]


def _pptx(path: Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        out = []
        for name in slides:
            root = ElementTree.fromstring(z.read(name))
            lines = ["".join(t.text or "" for t in p.iter(f"{_A}t")) for p in root.iter(f"{_A}p")]
            out.append((f"slide {re.search(r'(\d+)\.xml$', name).group(1)}", "\n".join(l for l in lines if l.strip())))
    return out


def _rows_as_text(rows: list[list[str]], first_line: int, label) -> list[tuple[str, str]]:
    """First non-empty row = headers; each row becomes "Header: value | …" (empty cells skipped)."""
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    headers, body = rows[0], rows[1:]

    def header(i: int) -> str:
        return (headers[i].strip() if i < len(headers) else "") or f"Coluna {i + 1}"

    if body:
        lines = [" | ".join(f"{header(i)}: {v.strip()}" for i, v in enumerate(r) if v.strip()) for r in body]
    else:                                         # a single row has nothing to label it with
        lines = [" | ".join(c.strip() for c in headers if c.strip())]
    return [(label(first_line + i, n), "\n".join(lines[i:i + _ROWS_PER_PIECE]))
            for n, i in enumerate(range(0, len(lines), _ROWS_PER_PIECE))]


def _xlsx(path: Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{_S}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_S}t")))
        book = ElementTree.fromstring(z.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        out = []
        for sheet in book.iter(f"{_S}sheet"):
            target = targets[sheet.get(f"{_R}id")].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            root = ElementTree.fromstring(z.read(target))
            rows = []
            for row in root.iter(f"{_S}row"):
                values = []
                for c in row.iter(f"{_S}c"):
                    column = _column_index(c.get("r", ""))
                    while len(values) < column:
                        values.append("")
                    v = c.find(f"{_S}v")
                    if c.get("t") == "s" and v is not None:
                        values.append(shared[int(v.text)])
                    elif c.get("t") == "inlineStr":
                        values.append("".join(t.text or "" for t in c.iter(f"{_S}t")))
                    else:
                        values.append(v.text if v is not None and v.text else "")
                rows.append(values)
            name = sheet.get("name")
            out += _rows_as_text(rows, 1, lambda _line, _n, name=name: f"aba {name}")
    return out


def _column_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return 0
    n = 0
    for ch in letters.group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")      # old Windows text files


def _csv(path: Path) -> list[tuple[str, str]]:
    text = _decode(path)
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    return _rows_as_text(rows, 2, lambda line, _n: f"linha {line}")


def _text(path: Path) -> list[tuple[str, str]]:
    return [("", _decode(path))]                  # the splitter numbers the pieces ("trecho N")


_READERS = {".pdf": _pdf, ".docx": _docx, ".pptx": _pptx, ".xlsx": _xlsx, ".csv": _csv,
            ".txt": _text, ".md": _text}
