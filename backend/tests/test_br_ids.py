import pytest

from legalos.core.br_ids import (
    cnj_check_digits,
    format_cnpj,
    is_valid_cnpj,
    is_valid_cpf,
    mask_document,
    parse_cnj,
)


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("529.982.247-25", True),
        ("52998224725", True),
        ("529.982.247-24", False),
        ("111.111.111-11", False),  # repeated digits pass the arithmetic but are invalid
        ("123", False),
    ],
)
def test_cpf(value: str, valid: bool) -> None:
    assert is_valid_cpf(value) is valid


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("11.222.333/0001-81", True),
        ("11222333000181", True),
        ("11.222.333/0001-82", False),
        ("00.000.000/0000-00", False),
        # Alphanumeric CNPJ (new format): example published by the Receita Federal.
        ("12.ABC.345/01DE-35", True),
        ("12.abc.345/01de-35", True),
        ("12.ABC.345/01DE-36", False),
    ],
)
def test_cnpj(value: str, valid: bool) -> None:
    assert is_valid_cnpj(value) is valid


def test_masking_hides_identifying_digits() -> None:
    assert mask_document("PF", "52998224725") == "***.982.247-**"
    assert mask_document("PJ", "11222333000181") == "11.***.***/0001-**"
    assert format_cnpj("12abc34501de35") == "12.ABC.345/01DE-35"


def test_cnj_number() -> None:
    dd = cnj_check_digits("0001234", "2024", "8", "26", "0100")
    canonical = f"0001234-{dd}.2024.8.26.0100"
    assert parse_cnj(canonical) == canonical
    assert parse_cnj(f"0001234{dd}2024826" + "0100") == canonical  # 20 digits, no mask
    wrong = f"{(int(dd) + 1) % 100:02d}"
    assert parse_cnj(f"0001234-{wrong}.2024.8.26.0100") is None
    assert parse_cnj("not a number") is None
