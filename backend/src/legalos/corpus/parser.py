"""Parse legal texts into structural units (brief §3: chunk by artigo → parágrafo →
inciso → alínea, never by fixed windows).

Input is a plain-text file with a small header:

    ---
    identifier: Lei 13.105/2015
    short_name: CPC
    title: Código de Processo Civil
    doc_type: legislacao
    review_status: oficial
    source_url: https://…
    retrieved_at: 2026-11-01T12:00:00Z
    ---
    CAPÍTULO III
    DOS PRAZOS
    Art. 219. Na contagem de prazo em dias…
    Parágrafo único. O disposto neste artigo…

For texts that are not legislation (súmulas, decisions), each unit starts with a line
`## <label>` (e.g. `## Súmula 7`) followed by its text.
"""

import re
from dataclasses import dataclass, field

HEADER_KEYS = {
    "identifier",
    "short_name",
    "title",
    "doc_type",
    "issuing_body",
    "urn",
    "publication_date",
    "source_url",
    "review_status",
    "retrieved_at",
    "valid_from",
}
REQUIRED_KEYS = {"identifier", "short_name", "title", "doc_type"}

_ARTICLE = re.compile(
    r"^Art\.\s*(\d{1,2}(?:\.\d{3})*|\d+)(?:[ºo°])?(-[A-Z])?\s*[.\-\u2013]?\s+(.*)$"
)
_PARAGRAPH = re.compile(r"^§\s*(\d+)[ºo°]?\s*[.\-\u2013]?\s+(.*)$")
_SOLE_PARAGRAPH = re.compile(r"^Parágrafo único\s*[.\-\u2013]\s*(.*)$", re.IGNORECASE)
_INCISO = re.compile(r"^([IVXLCDM]+)\s*[-\u2013\u2014]\s+(.*)$")
_ALINEA = re.compile(r"^([a-z])\)\s+(.*)$")
_HEADING = re.compile(
    r"^(PARTE|LIVRO|TÍTULO|TITULO|CAPÍTULO|CAPITULO|SEÇÃO|SECAO|SUBSEÇÃO|Seção|Subseção)\b"
)
_REVOKED = re.compile(r"\((?:Revogad[oa]|Vetad[oa])[^)]*\)", re.IGNORECASE)
_AMENDED = re.compile(r"\((?:Redação dada|Incluíd[oa]|Acrescid[oa]|Vide)[^)]*\)", re.IGNORECASE)


class CorpusParseError(ValueError):
    pass


@dataclass
class ParsedUnit:
    unit_type: str
    label: str
    text: str
    parent_label: str | None
    heading_path: str | None
    status: str = "vigente"
    amendment_note: str | None = None


@dataclass
class ParsedDocument:
    meta: dict[str, str]
    units: list[ParsedUnit] = field(default_factory=list)


def parse(source: str) -> ParsedDocument:
    meta, body = _split_header(source)
    doc = ParsedDocument(meta=meta)
    if meta["doc_type"] == "legislacao":
        doc.units = _parse_legislation(body)
    else:
        doc.units = _parse_labelled(body)
    if not doc.units:
        raise CorpusParseError("no units found")
    labels = [u.label for u in doc.units]
    duplicates = {label for label in labels if labels.count(label) > 1}
    if duplicates:
        raise CorpusParseError(f"duplicate unit labels: {sorted(duplicates)[:5]}")
    return doc


def _split_header(source: str) -> tuple[dict[str, str], str]:
    lines = source.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise CorpusParseError("file must start with a '---' header")
    try:
        end = lines.index("---", 1)
    except ValueError as e:
        raise CorpusParseError("header is not closed with '---'") from e
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in HEADER_KEYS:
            raise CorpusParseError(f"unknown header line: {line!r}")
        meta[key] = value.strip()
    missing = REQUIRED_KEYS - meta.keys()
    if missing:
        raise CorpusParseError(f"missing header keys: {sorted(missing)}")
    return meta, "\n".join(lines[end + 1 :])


def _annotations(text: str) -> tuple[str, str, str | None]:
    """Detect "(Revogado …)" and "(Redação dada pela Lei …)" notes."""
    revoked = _REVOKED.search(text)
    amended = _AMENDED.findall(text)
    note = "; ".join(n.strip("()") for n in amended) or None
    if revoked:
        return text, "revogado", revoked.group(0).strip("()")
    return text, "vigente", note


def _parse_legislation(body: str) -> list[ParsedUnit]:
    units: list[ParsedUnit] = []
    headings: list[str] = []
    pending_heading = False
    article: str | None = None  # e.g. "art. 224"
    paragraph: str | None = None  # e.g. "art. 224, § 1º"
    inciso: str | None = None  # e.g. "art. 335, I"
    current: ParsedUnit | None = None

    def add(unit_type: str, label: str, text: str, parent: str | None) -> ParsedUnit:
        unit = ParsedUnit(unit_type, label, text.strip(), parent, " > ".join(headings) or None)
        units.append(unit)
        return unit

    for raw in body.split("\n"):
        line = " ".join(raw.split())
        if not line:
            continue
        if _HEADING.match(line):
            level = line.split()[0].upper()
            headings[:] = [h for h in headings if _rank(h) < _rank(level)]
            headings.append(line)
            pending_heading = True
            current = None
            continue
        if m := _ARTICLE.match(line):
            number = m.group(1) + (m.group(2) or "")
            article, paragraph, inciso = f"art. {number}", None, None
            current = add("artigo", article, m.group(3), None)
        elif article and (m := _SOLE_PARAGRAPH.match(line)):
            paragraph, inciso = f"{article}, parágrafo único", None
            current = add("paragrafo", paragraph, m.group(1), article)
        elif article and (m := _PARAGRAPH.match(line)):
            paragraph, inciso = f"{article}, § {m.group(1)}º", None
            current = add("paragrafo", paragraph, m.group(2), article)
        elif article and (m := _INCISO.match(line)):
            parent = paragraph or article
            inciso = f"{parent}, {m.group(1)}"
            current = add("inciso", inciso, m.group(2), parent)
        elif inciso and (m := _ALINEA.match(line)):
            current = add("alinea", f"{inciso}, {m.group(1)}", m.group(2), inciso)
        elif pending_heading and headings:
            # The line after "CAPÍTULO III" is its title ("DOS PRAZOS").
            headings[-1] = f"{headings[-1]} - {line}"
        elif current is not None:
            current.text = f"{current.text} {line}"
        pending_heading = False
    # Annotations are read last, because a unit's text may span several lines.
    for unit in units:
        unit.text, unit.status, unit.amendment_note = _annotations(unit.text)
    return units


_RANKS = [
    "PARTE",
    "LIVRO",
    "TÍTULO",
    "TITULO",
    "CAPÍTULO",
    "CAPITULO",
    "SEÇÃO",
    "SECAO",
    "SUBSEÇÃO",
]


def _rank(heading: str) -> int:
    word = heading.split()[0].upper()
    return _RANKS.index(word) if word in _RANKS else len(_RANKS)


def _parse_labelled(body: str) -> list[ParsedUnit]:
    units: list[ParsedUnit] = []
    label: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if label and (text := " ".join(" ".join(buffer).split())):
            text, status, note = _annotations(text)
            units.append(ParsedUnit("enunciado", label, text, None, None, status, note))

    for line in body.split("\n"):
        if line.startswith("## "):
            flush()
            label, buffer = line[3:].strip(), []
        elif label:
            buffer.append(line)
    flush()
    return units
