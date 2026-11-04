"""Documentos fictícios montados à mão (sem bibliotecas), para testes e avaliações da base."""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


def make_pdf(path: Path, pages: list[str]) -> Path:
    """PDF mínimo com Helvetica; página com texto vazio = página só de imagem (sem texto)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for text in pages:
        lines = [text[i:i + 90] for i in range(0, len(text), 90)]
        ops = "BT /F1 10 Tf 40 800 Td 12 TL " + " ".join(
            "(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for l in lines) + " ET"
        stream = ops.encode("cp1252") if text else b""
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >>"
                    b" /Contents %d 0 R >>" % len(objs))
        kids.append(len(objs))
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % x for x in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{body}</w:body></w:document>")
    return path


def make_pptx(path: Path, slides: list[list[str]]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for n, lines in enumerate(slides, 1):
            paras = "".join(f"<a:p><a:r><a:t>{escape(l)}</a:t></a:r></a:p>" for l in lines)
            z.writestr(f"ppt/slides/slide{n}.xml",
                       '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                       f"<p:cSld><p:spTree><p:sp><p:txBody>{paras}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
    return path


def make_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    """Células como strings compartilhadas; a 1ª linha de cada aba é o cabeçalho."""
    shared: list[str] = []
    s = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as z:
        book, rels = [], []
        for n, (name, rows) in enumerate(sheets.items(), 1):
            xml_rows = []
            for i, row in enumerate(rows, 1):
                cells = []
                for j, value in enumerate(row):
                    if value == "":
                        continue
                    shared.append(value)
                    cells.append(f'<c r="{chr(65 + j)}{i}" t="s"><v>{len(shared) - 1}</v></c>')
                xml_rows.append(f'<row r="{i}">{"".join(cells)}</row>')
            z.writestr(f"xl/worksheets/sheet{n}.xml", f'<worksheet xmlns="{s}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
            book.append(f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>')
            rels.append(f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml" Type="x"/>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{s}" xmlns:r="{r}"><sheets>{"".join(book)}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   f'<sst xmlns="{s}">' + "".join(f"<si><t>{escape(v)}</t></si>" for v in shared) + "</sst>")
    return path
