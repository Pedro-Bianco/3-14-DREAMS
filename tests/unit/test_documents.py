"""Leitura dos formatos da base, com a origem de cada parte e recusas claras."""

import pytest

from pidreams.memory import documents
from pidreams.memory.documents import Unreadable
from tests.fixtures.fake_documents import make_docx, make_pdf, make_pptx, make_xlsx


def test_pdf_por_pagina(tmp_path):
    pdf = make_pdf(tmp_path / "contrato.pdf", ["Cláusula primeira: objeto.", "Penalidade por mora de 2% ao mês."])
    partes = documents.read(pdf)
    assert [onde for onde, _ in partes] == ["p. 1", "p. 2"]
    assert "Penalidade por mora" in partes[1][1] and "Cláusula" in partes[0][1]


def test_pdf_so_de_imagem_e_recusado_com_motivo(tmp_path):
    with pytest.raises(Unreadable, match="escaneado"):
        documents.read(make_pdf(tmp_path / "scan.pdf", ["", ""]))


def test_docx_em_trechos(tmp_path):
    docx = make_docx(tmp_path / "manual.docx", [f"Parágrafo {i}" for i in range(25)])
    partes = documents.read(docx)
    assert [onde for onde, _ in partes] == ["trecho 1", "trecho 2"]
    assert partes[1][1].startswith("Parágrafo 20")


def test_pptx_por_slide_em_ordem_numerica(tmp_path):
    slides = [[f"Título {n}", f"Texto do slide {n}"] for n in range(1, 12)]
    partes = documents.read(make_pptx(tmp_path / "apresentacao.pptx", slides))
    assert partes[0][0] == "slide 1" and partes[10][0] == "slide 11"
    assert "Texto do slide 11" in partes[10][1]


def test_xlsx_linhas_com_cabecalho_por_aba(tmp_path):
    xlsx = make_xlsx(tmp_path / "vendas.xlsx", {
        "Vendas": [["Região", "Mês", "Valor"], ["Sul", "março", "1520"], ["", "", ""], ["Norte", "abril", ""]],
        "Metas": [["Ano", "Meta"], ["2026", "5000"]]})
    partes = dict(documents.read(xlsx))
    assert partes["aba Vendas"] == "Região: Sul | Mês: março | Valor: 1520\nRegião: Norte | Mês: abril"
    assert partes["aba Metas"] == "Ano: 2026 | Meta: 5000"


def test_csv_com_ponto_e_virgula(tmp_path):
    arquivo = tmp_path / "clientes.csv"
    arquivo.write_text("Nome;Cidade\nAna Exemplo;Recife\nBruno Teste;Salvador\n", encoding="utf-8")
    assert documents.read(arquivo) == [("linha 2", "Nome: Ana Exemplo | Cidade: Recife\nNome: Bruno Teste | Cidade: Salvador")]


def test_texto_em_cp1252_e_markdown(tmp_path):
    antigo = tmp_path / "notas.txt"
    antigo.write_bytes("Reunião às 10h".encode("cp1252"))
    assert documents.read(antigo) == [("", "Reunião às 10h")]
    md = tmp_path / "leia.md"
    md.write_text("# Título\nConteúdo", encoding="utf-8")
    assert documents.read(md)[0][1].startswith("# Título")


def test_arquivo_corrompido_vazio_e_formato_desconhecido(tmp_path):
    ruim = tmp_path / "quebrado.docx"
    ruim.write_bytes(b"isto nao e um zip")
    with pytest.raises(Unreadable, match="corrompido"):
        documents.read(ruim)
    vazio = tmp_path / "vazio.txt"
    vazio.write_text("   ", encoding="utf-8")
    with pytest.raises(Unreadable, match="não tem texto"):
        documents.read(vazio)
    with pytest.raises(Unreadable, match="não suportado"):
        documents.read(tmp_path / "foto.png")
