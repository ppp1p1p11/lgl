"""Deadline engine. Every expected date below was counted by hand on a calendar."""

from datetime import date

import pytest

from legalos.deadlines.engine import (
    DeadlineInput,
    calculate,
    easter,
    in_recess,
    movable_suggestions,
)

TIRADENTES = {date(2026, 4, 21): "Tiradentes"}
TRABALHO = {date(2026, 5, 1): "Dia do Trabalho"}


def due(rule_set, trigger_kind, trigger, days, holidays=None, **kw) -> date:  # type: ignore[no-untyped-def]
    inp = DeadlineInput(rule_set, trigger_kind, trigger, days, **kw)
    return calculate(inp, holidays or {}).proposed_date


def test_business_days_exclude_start_include_end() -> None:
    # Ciência on Friday 06/03/2026; 5 business days: Mon 9, 10, 11, 12, Fri 13.
    assert due("cpc", "ciencia", date(2026, 3, 6), 5) == date(2026, 3, 13)


def test_dje_publication_is_next_business_day_and_count_starts_the_day_after() -> None:
    # Available Tue 10/03; published Wed 11/03; count starts Thu 12/03; 15th day Wed 01/04.
    r = calculate(DeadlineInput("cpc", "disponibilizacao_dje", date(2026, 3, 10), 15), {})
    assert r.counting_start == date(2026, 3, 12)
    assert r.proposed_date == date(2026, 4, 1)
    # Available on a Friday: published Monday, count starts Tuesday.
    r = calculate(DeadlineInput("cpc", "disponibilizacao_dje", date(2026, 3, 13), 1), {})
    assert r.counting_start == date(2026, 3, 17) == r.proposed_date


def test_holidays_are_not_counted_and_are_listed() -> None:
    # Ciência Thu 16/04; Fri 17 (1), Mon 20 (2), Tue 21 holiday, Wed 22 (3).
    r = calculate(DeadlineInput("cpc", "ciencia", date(2026, 4, 16), 3), TIRADENTES)
    assert r.proposed_date == date(2026, 4, 22)
    assert [h.name for h in r.skipped_holidays] == ["Tiradentes"]
    assert any("Tiradentes" in s.detail for s in r.steps)


def test_recess_suspends_counting() -> None:
    # Available Thu 10/12/2026; published Fri 11; count Mon 14..Fri 18 = 5 days;
    # recess 20/12-20/01; resumes Thu 21/01/2027 (6) ... 15th day Wed 03/02/2027.
    r = calculate(DeadlineInput("cpc", "disponibilizacao_dje", date(2026, 12, 10), 15), {})
    assert r.proposed_date == date(2027, 2, 3)
    assert r.recess_days_skipped > 0
    assert any("recesso" in s.detail for s in r.steps)
    # An event inside the recess: counting starts on 21/01.
    assert due("cpc", "ciencia", date(2026, 12, 28), 5) == date(2027, 1, 27)


def test_recess_boundaries() -> None:
    assert in_recess(date(2026, 12, 20)) and in_recess(date(2027, 1, 20))
    assert not in_recess(date(2026, 12, 19)) and not in_recess(date(2027, 1, 21))


def test_doubling() -> None:
    # Ciência Mon 01/06/2026; 15 days doubled = 30 business days from Tue 02/06 -> Mon 13/07.
    r = calculate(
        DeadlineInput("cpc", "ciencia", date(2026, 6, 1), 15, doubled_reason="fazenda_publica"),
        {},
    )
    assert r.effective_days == 30 and r.proposed_date == date(2026, 7, 13)
    assert any("art. 183" in s.detail for s in r.steps)
    with pytest.raises(ValueError):
        calculate(DeadlineInput("cpc", "ciencia", date(2026, 6, 1), 15, doubled_reason="x"), {})


def test_calendar_days_roll_to_next_business_day() -> None:
    # 30 calendar days from Wed 01/04/2026 = Fri 01/05 (holiday) -> Mon 04/05.
    r = calculate(
        DeadlineInput("cpc", "ciencia", date(2026, 4, 1), 30, unit="dias_corridos"), TRABALHO
    )
    assert r.proposed_date == date(2026, 5, 4)
    assert any("art. 132" in s.detail for s in r.steps)
    # Calendar-day deadlines are not suspended by the recess.
    assert due("cpc", "ciencia", date(2026, 12, 21), 10, unit="dias_corridos") == date(2026, 12, 31)


@pytest.mark.parametrize(
    ("rule_set", "basis"),
    [
        ("cpc", "CPC, art. 219"),
        ("clt", "CLT, art. 775"),
        ("jec", "Lei 9.099/1995, art. 12-A"),
    ],
)
def test_each_rule_set_cites_its_basis(rule_set: str, basis: str) -> None:
    r = calculate(DeadlineInput(rule_set, "ciencia", date(2026, 3, 6), 5), {})  # type: ignore[arg-type]
    assert r.proposed_date == date(2026, 3, 13)
    assert any(basis in s.detail for s in r.steps)


def test_every_result_ends_with_a_caution_and_is_only_a_proposal() -> None:
    r = calculate(DeadlineInput("cpc", "ciencia", date(2026, 3, 6), 5), {})
    assert r.steps[-1].label == "Atenção" and "proposta" in r.steps[-1].detail
    assert r.steps[-2].label == "Vencimento proposto"


def test_input_limits() -> None:
    with pytest.raises(ValueError):
        calculate(DeadlineInput("cpc", "ciencia", date(2026, 3, 6), 0), {})


def test_easter_and_movable_dates() -> None:
    assert easter(2024) == date(2024, 3, 31)
    assert easter(2025) == date(2025, 4, 20)
    assert easter(2026) == date(2026, 4, 5)
    names = {h.name: h.day for h in movable_suggestions(2026)}
    assert names["Sexta-feira Santa"] == date(2026, 4, 3)
    assert names["Carnaval (terça-feira)"] == date(2026, 2, 17)
    assert names["Corpus Christi"] == date(2026, 6, 4)
