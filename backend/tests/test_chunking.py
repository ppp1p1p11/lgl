import random
from itertools import pairwise

from legalos.documents.chunking import chunk_page


def _check(text: str, target: int = 1200) -> None:
    chunks = chunk_page(text, target)
    for c in chunks:
        assert text[c.char_start : c.char_end] == c.text
        assert c.text == c.text.strip() and c.text
        assert len(c.text) <= target
    # Every non-space character is in exactly one chunk, in order.
    covered = "".join(c.text for c in chunks).replace(" ", "").replace("\n", "")
    assert covered == text.replace(" ", "").replace("\n", "")
    assert all(a.char_end <= b.char_start for a, b in pairwise(chunks))


def test_short_page_is_one_chunk() -> None:
    chunks = chunk_page("Primeiro parágrafo.\n\nSegundo parágrafo.")
    assert len(chunks) == 1


def test_paragraphs_are_grouped_up_to_the_target() -> None:
    text = "\n\n".join(f"Parágrafo {i}. " + "palavra " * 40 for i in range(20))
    _check(text)
    assert len(chunk_page(text)) > 1


def test_long_paragraph_is_split_at_sentences() -> None:
    text = " ".join(f"Frase número {i} do mesmo parágrafo longo." for i in range(200))
    _check(text)
    assert all(c.text.endswith(".") for c in chunk_page(text)[:-1])


def test_text_without_spaces_still_splits() -> None:
    _check("x" * 5000)


def test_random_texts_keep_invariants() -> None:
    rng = random.Random(1)
    words = ["lei", "artigo", "prazo", "recurso.", "autor", "réu;", "\n", "\n\n", "  "]
    for _ in range(50):
        _check(" ".join(rng.choice(words) for _ in range(rng.randint(0, 800))), target=300)


def test_empty_page() -> None:
    assert chunk_page("") == []
    assert chunk_page("   \n\n  ") == []
