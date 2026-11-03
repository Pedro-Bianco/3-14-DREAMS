"""
Text splitting (chunking) strategies for ingestion into vector stores.

Modes supported through ``split_text()``:
    character, word, token, sentence, markdown, html, semantic, json_mixed, faq.
"""

import json
import re
from typing import Any, Dict, List, Union

from langchain_experimental.text_splitter import SemanticChunker
from langchain_text_splitters import (
    HTMLSectionSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)


def split_by_character(text: str, chunk_size: int = 250, chunk_overlap: int = 0) -> List[str]:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    ).split_text(text)


def split_by_word(text: str, chunk_size: int = 250, chunk_overlap: int = 50) -> List[str]:
    words = text.split(" ")
    step = chunk_size - chunk_overlap
    return [
        " ".join(words[i: i + chunk_size])
        for i in range(0, len(words), step)
        if words[i: i + chunk_size]
    ]


def split_by_token(text: str, chunk_size: int = 250, chunk_overlap: int = 0) -> List[str]:
    return TokenTextSplitter(
        model_name="gpt-4",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    ).split_text(text)


def split_by_sentence(text: str, sentences_size: int = 8, sentences_overlap: int = 2) -> List[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    step = max(1, sentences_size - sentences_overlap)
    return [
        " ".join(sentences[i: i + sentences_size])
        for i in range(0, len(sentences), step)
        if sentences[i: i + sentences_size]
    ]


def split_by_markdown(text: str, chunk_size: int = 300, chunk_overlap: int | None = None) -> List[str]:
    if chunk_overlap is None:
        chunk_overlap = int(chunk_size * 0.2)

    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "H1"), ("##", "H2"), ("###", "H3"), ("####", "H4"),
        ],
        strip_headers=False,
    )
    md_docs = md_splitter.split_text(text)

    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", ". ", " "],
    )

    chunks: List[str] = []
    for doc in md_docs:
        header_context = " > ".join(
            doc.metadata.get(level, "")
            for level in ("H1", "H2", "H3", "H4")
            if doc.metadata.get(level)
        )
        for chunk in recursive_splitter.split_text(doc.page_content):
            chunks.append(f"{header_context}\n{chunk}".strip() if header_context else chunk.strip())
    return chunks


def split_by_html(text: str, chunk_size: int = 250, chunk_overlap: int = 0) -> List[str]:
    html_docs = HTMLSectionSplitter(
        headers_to_split_on=[("h1", "H1"), ("h2", "H2"), ("h3", "H3"), ("h4", "H4")],
    ).split_text(text)
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return [c for doc in html_docs for c in splitter.split_text(doc.page_content)]


def split_by_semantic(
    text: str,
    embedding_model: Any,
    min_chunk_size: int = 250,
    buffer_size: int = 1,
) -> List[str]:
    return SemanticChunker(
        embedding_model, min_chunk_size=min_chunk_size, buffer_size=buffer_size,
    ).split_text(text)


def split_by_json_mixed(text: str) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    text_buffer = ""
    buffer_json = ""
    inside_json = False
    key_counter = 0

    for char in text:
        if not inside_json:
            if char == "{":
                inside_json = True
                key_counter = 1
                buffer_json += char
            else:
                text_buffer += char
        else:
            buffer_json += char
            if char == "{":
                key_counter += 1
            elif char == "}":
                key_counter -= 1
            if key_counter == 0:
                try:
                    pairs.append({
                        "texto_vetor": text_buffer.strip(),
                        "json_payload": json.loads(buffer_json.strip()),
                    })
                except json.JSONDecodeError:
                    pass
                text_buffer = ""
                buffer_json = ""
                inside_json = False

    if text_buffer.strip():
        pairs.append({"texto_vetor": text_buffer.strip(), "json_payload": {}})
    return pairs


def split_by_qna(text: str) -> List[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    chunks: List[str] = []
    question: str | None = None
    answer: List[str] = []

    for sentence in sentences:
        if "?" in sentence:
            if question is not None:
                ans = " ".join(answer).strip()
                chunks.append(f"{question}\n{ans}" if ans else question)
            question, answer = sentence, []
        else:
            answer.append(sentence)

    if question is not None:
        ans = " ".join(answer).strip()
        chunks.append(f"{question}\n{ans}" if ans else question)
    return chunks


def split_text(
    text: str,
    mode: str = "character",
    chunk_size: int = 250,
    chunk_overlap: int = 0,
    embedding_model: Any = None,
    sentences_size: int = 8,
    sentences_overlap: int = 2,
) -> Union[List[str], List[Dict[str, Any]]]:
    """
    Dispatcher central de chunking.

    Args:
        mode: ``character`` | ``word`` | ``token`` | ``sentence`` | ``markdown``
              | ``html`` | ``semantic`` | ``json_mixed`` | ``faq``
    """
    mode = mode.lower()
    if mode in ("character", "char"):
        return split_by_character(text, chunk_size, chunk_overlap)
    if mode == "word":
        return split_by_word(text, chunk_size, chunk_overlap)
    if mode == "token":
        return split_by_token(text, chunk_size, chunk_overlap)
    if mode == "sentence":
        return split_by_sentence(text, sentences_size, sentences_overlap)
    if mode == "markdown":
        return split_by_markdown(text, chunk_size, chunk_overlap)
    if mode == "html":
        return split_by_html(text, chunk_size, chunk_overlap)
    if mode in ("json_mixed", "json"):
        return split_by_json_mixed(text)
    if mode == "semantic":
        if embedding_model is None:
            raise ValueError("embedding_model é obrigatório para o modo semantic")
        return split_by_semantic(text, embedding_model, chunk_size)
    if mode in ("faq", "qna"):
        return split_by_qna(text)
    raise ValueError(f"Modo de chunking '{mode}' não reconhecido")
