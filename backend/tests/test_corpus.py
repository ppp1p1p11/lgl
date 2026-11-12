from datetime import date

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from legalos.config import get_settings
from legalos.corpus import search
from legalos.corpus.ingest import ingest_demo, ingest_text
from legalos.corpus.models import LegalUnit, LegalUnitVersion
from legalos.corpus.parser import CorpusParseError, parse
from tests.conftest import app_db

HEADER = """---
identifier: Lei Fictícia 1/2099
short_name: LF
title: Lei fictícia para testes
doc_type: legislacao
review_status: oficial
source_url: https://example.org/lei
retrieved_at: 2026-11-01T12:00:00Z
{extra}---
"""

LAW_V1 = (
    HEADER.format(extra="")
    + """TÍTULO I
DAS DISPOSIÇÕES GERAIS
CAPÍTULO II
DOS PRAZOS
Art. 1º O prazo para resposta é de 10 (dez) dias.
Parágrafo único. O prazo conta-se em dias úteis.
Art. 2º São deveres das partes:
I - agir com boa-fé;
II - apresentar documentos:
a) pessoais;
b) societários.
§ 1º O descumprimento sujeita a parte a multa.
§ 2º (Revogado pela Lei Fictícia 3/2099)
Art. 1.003-A. Este artigo trata de recursos
e continua na linha seguinte. (Redação dada pela Lei Fictícia 2/2099)
"""
)

LAW_V2 = (
    HEADER.format(extra="valid_from: 2027-01-01\n")
    + """Art. 1º O prazo para resposta é de 15 (quinze) dias.
Parágrafo único. O prazo conta-se em dias úteis.
"""
)

SUMULAS = """---
identifier: Súmulas fictícias do Tribunal X
short_name: Súmulas TX
title: Súmulas fictícias
doc_type: sumula
---
## Súmula 1
O prazo para resposta conta-se em dias úteis.

## Súmula 2
Texto de outra súmula
em duas linhas.
"""


def test_parser_builds_the_structural_tree() -> None:
    doc = parse(LAW_V1)
    units = {u.label: u for u in doc.units}
    assert list(units) == [
        "art. 1",
        "art. 1, parágrafo único",
        "art. 2",
        "art. 2, I",
        "art. 2, II",
        "art. 2, II, a",
        "art. 2, II, b",
        "art. 2, § 1º",
        "art. 2, § 2º",
        "art. 1.003-A",
    ]
    assert units["art. 2, II, a"].parent_label == "art. 2, II"
    assert units["art. 2, § 1º"].parent_label == "art. 2"
    assert units["art. 1"].heading_path == (
        "TÍTULO I - DAS DISPOSIÇÕES GERAIS > CAPÍTULO II - DOS PRAZOS"
    )
    assert units["art. 2, § 2º"].status == "revogado"
    assert units["art. 1.003-A"].text.startswith("Este artigo trata de recursos e continua")
    assert units["art. 1.003-A"].amendment_note == "Redação dada pela Lei Fictícia 2/2099"


def test_parser_labelled_format_and_errors() -> None:
    doc = parse(SUMULAS)
    assert [(u.label, u.text) for u in doc.units] == [
        ("Súmula 1", "O prazo para resposta conta-se em dias úteis."),
        ("Súmula 2", "Texto de outra súmula em duas linhas."),
    ]
    with pytest.raises(CorpusParseError, match="header"):
        parse("Art. 1º Sem cabeçalho.")
    with pytest.raises(CorpusParseError, match="missing"):
        parse("---\nidentifier: X\n---\nArt. 1º Texto.")
    with pytest.raises(CorpusParseError, match="duplicate"):
        parse(HEADER.format(extra="") + "Art. 1º A.\nArt. 1º B.\n")


@pytest.fixture
def corpus(owner_engine: Engine) -> None:
    with Session(owner_engine) as db, db.begin():
        ingest_text(db, LAW_V1, source_name="lei.txt")
        ingest_text(db, SUMULAS, source_name="sumulas.txt")


def test_ingestion_is_idempotent_and_versions_changes(corpus, owner_engine: Engine) -> None:
    with Session(owner_engine) as db, db.begin():
        again = ingest_text(db, LAW_V1, source_name="lei.txt")
        assert again == {"units": 10, "new": 0, "changed": 0, "unchanged": 10}
        changed = ingest_text(db, LAW_V2, source_name="lei-v2.txt")
        assert changed == {"units": 2, "new": 0, "changed": 1, "unchanged": 1}
    with Session(owner_engine) as db:
        versions = db.execute(
            select(
                LegalUnitVersion.text,
                LegalUnitVersion.valid_from,
                LegalUnitVersion.valid_to,
                LegalUnitVersion.status,
                LegalUnitVersion.retrieved_at,
                LegalUnitVersion.content_hash,
            )
            .join(LegalUnit)
            .where(LegalUnit.label == "art. 1")
            .order_by(LegalUnitVersion.created_at)
        ).all()
    old, new = versions
    assert (old.valid_to, old.status) == (date(2027, 1, 1), "alterado")
    assert (new.valid_from, new.valid_to, new.status) == (date(2027, 1, 1), None, "vigente")
    assert new.retrieved_at is not None and len(new.content_hash) == 64

    # Temporal validity: the answer depends on the date asked about.
    with app_db() as db:
        before = search.search(db, "prazo para resposta", on_date=date(2026, 6, 1))
        after = search.search(db, "prazo para resposta", on_date=date(2027, 6, 1))
    assert "10 (dez) dias" in next(h.text for h in before if h.label == "art. 1")
    assert "15 (quinze) dias" in next(h.text for h in after if h.label == "art. 1")


def test_search_ranks_by_relevance_and_source_weight(corpus) -> None:
    with app_db() as db:
        hits = search.search(db, "o prazo conta-se em dias úteis")
        labels = [(h.short_name, h.label) for h in hits]
        # Same wording in the law and in a súmula: legislation ranks first.
        assert labels.index(("LF", "art. 1, parágrafo único")) < labels.index(
            ("Súmulas TX", "Súmula 1")
        )
        assert {h.doc_type for h in hits} == {"legislacao", "sumula"}
        # An explicit citation finds the article and its sub-units even without other words.
        cited = [h.label for h in search.search(db, "o que diz o art. 2?")]
        assert cited[0] == "art. 2" and "art. 2, II, a" in cited
        assert search.search(db, "zzzz inexistente") == []
        assert search.search(db, "?!") == []


def test_revoked_units_are_returned_with_their_status(corpus) -> None:
    with app_db() as db:
        hit = next(h for h in search.search(db, "art. 2") if h.label == "art. 2, § 2º")
    assert hit.status == "revogado"


def test_app_role_cannot_change_the_corpus(corpus) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), app_db() as db:
        db.execute(text("UPDATE legal_unit_versions SET text = 'adulterado'"))
    with pytest.raises(ProgrammingError, match="permission denied"), app_db() as db:
        db.execute(text("DELETE FROM legal_documents"))


def test_demo_corpus_loads_and_is_hidden_in_production(
    owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(owner_engine) as db, db.begin():
        stats = ingest_demo(db)
    assert stats["cpc-prazos-amostra.txt"]["units"] == 24
    with app_db() as db:
        hits = search.search(db, "prazo para contestação")
        assert hits[0].label == "art. 335" and hits[0].review_status == "demonstracao_nao_conferida"
        monkeypatch.setattr(get_settings(), "environment", "production")
        assert search.search(db, "prazo para contestação") == []
