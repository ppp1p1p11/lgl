"""Split page text into passages for search and citations.

Chunks never cross pages, and each one records its exact position in the page text,
so a citation can point to the precise passage: `page_text[start:end] == chunk_text`.
"""

import re
from dataclasses import dataclass

TARGET_CHARS = 1200
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+")


@dataclass(frozen=True)
class Chunk:
    char_start: int
    char_end: int
    text: str


def chunk_page(text: str, target: int = TARGET_CHARS) -> list[Chunk]:
    spans = _split_spans(text, target)
    chunks: list[Chunk] = []
    start: int | None = None
    end = 0
    for s, e in spans:
        if start is None:
            start, end = s, e
        elif e - start <= target:
            end = e
        else:
            chunks.append(Chunk(start, end, text[start:end]))
            start, end = s, e
    if start is not None:
        chunks.append(Chunk(start, end, text[start:end]))
    return chunks


def _split_spans(text: str, target: int) -> list[tuple[int, int]]:
    """Paragraph spans; paragraphs longer than `target` are split at sentence ends,
    and as a last resort at spaces."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for match in [*_PARAGRAPH_BREAK.finditer(text), None]:
        para_end = match.start() if match else len(text)
        if text[pos:para_end].strip():
            spans.extend(_split_long(text, pos, para_end, target))
        pos = match.end() if match else len(text)
    return spans


def _split_long(text: str, start: int, end: int, target: int) -> list[tuple[int, int]]:
    if end - start <= target:
        return [_trim(text, start, end)]
    pieces: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > target:
        window = text[cursor : cursor + target]
        cut = max((m.start() for m in _SENTENCE_END.finditer(window)), default=-1)
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = target
        pieces.append(_trim(text, cursor, cursor + cut))
        cursor += cut
        while cursor < end and text[cursor].isspace():
            cursor += 1
    if cursor < end:
        pieces.append(_trim(text, cursor, end))
    return [p for p in pieces if p[1] > p[0]]


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
