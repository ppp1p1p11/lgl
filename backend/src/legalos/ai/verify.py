"""Check that text attributed to a document really is in it (brief rule 1).

A quote counts as verified only if it appears in the document's extracted text, ignoring
differences in whitespace, letter case and typographic quotes/dashes. Verified quotes are
mapped back to exact positions in the page text, so the UI can highlight them.
"""

from dataclasses import dataclass

MIN_QUOTE_CHARS = 8

_EQUIVALENTS = str.maketrans(
    {
        "\u201c": '"',  # left double quotation mark
        "\u201d": '"',  # right double quotation mark
        "\u201e": '"',  # low double quotation mark
        "\u2018": "'",  # left single quotation mark
        "\u2019": "'",  # right single quotation mark
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u00a0": " ",  # no-break space
    }
)


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class Located:
    page_number: int
    char_start: int
    char_end: int
    text: str  # the exact passage as it appears in the document


def _normalize(text: str) -> tuple[str, list[int]]:
    """Normalized text plus, for each normalized character, its index in the original."""
    out: list[str] = []
    index_map: list[int] = []
    previous_space = True
    for i, ch in enumerate(text.translate(_EQUIVALENTS)):
        if ch.isspace():
            if previous_space:
                continue
            ch = " "
            previous_space = True
        else:
            previous_space = False
            lowered = ch.lower()
            ch = lowered if len(lowered) == 1 else ch
        out.append(ch)
        index_map.append(i)
    while out and out[-1] == " ":
        out.pop()
        index_map.pop()
    return "".join(out), index_map


def locate(quote: str, pages: list[PageText]) -> Located | None:
    needle, _ = _normalize(quote.strip().strip('"').strip())
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    for page in pages:
        haystack, index_map = _normalize(page.text)
        found = haystack.find(needle)
        if found >= 0:
            start = index_map[found]
            end = index_map[found + len(needle) - 1] + 1
            return Located(page.page_number, start, end, page.text[start:end])
    return None
