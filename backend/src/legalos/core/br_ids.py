"""Brazilian identifiers: CPF, CNPJ and the CNJ unified process number.

The check-digit algorithms are the published ones; the exact references are tracked in
docs/VERIFY.md (ID-1 to ID-3) until confirmed against the official texts.
"""

import re

_NON_DIGITS = re.compile(r"\D")
_CNPJ_CHARS = re.compile(r"[^0-9A-Z]")


def only_digits(value: str) -> str:
    return _NON_DIGITS.sub("", value)


# --- CPF ----------------------------------------------------------------------------------


def _cpf_digit(digits: str) -> int:
    weight = len(digits) + 1
    total = sum(int(d) * (weight - i) for i, d in enumerate(digits))
    rest = (total * 10) % 11
    return 0 if rest == 10 else rest


def is_valid_cpf(value: str) -> bool:
    cpf = only_digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    return cpf[9] == str(_cpf_digit(cpf[:9])) and cpf[10] == str(_cpf_digit(cpf[:10]))


def format_cpf(value: str) -> str:
    c = only_digits(value)
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


# --- CNPJ (numeric, and the alphanumeric format introduced for new CNPJs) -----------------


def normalize_cnpj(value: str) -> str:
    return _CNPJ_CHARS.sub("", value.upper())


def _cnpj_digit(chars: str) -> int:
    # Each character counts as its ASCII code minus 48, so digits keep their value and
    # letters A-Z count 17-42 (VERIFY ID-2).
    weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(chars) :]
    total = sum((ord(c) - 48) * w for c, w in zip(chars, weights, strict=True))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def is_valid_cnpj(value: str) -> bool:
    cnpj = normalize_cnpj(value)
    if len(cnpj) != 14 or not cnpj[12:].isdigit() or cnpj == cnpj[0] * 14:
        return False
    return cnpj[12] == str(_cnpj_digit(cnpj[:12])) and cnpj[13] == str(_cnpj_digit(cnpj[:13]))


def format_cnpj(value: str) -> str:
    c = normalize_cnpj(value)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def mask_document(kind: str, value: str) -> str:
    """Show only the middle digits, as is common practice for CPF in public documents."""
    if kind == "PF":
        c = only_digits(value)
        return f"***.{c[3:6]}.{c[6:9]}-**"
    c = normalize_cnpj(value)
    return f"{c[:2]}.***.***/{c[8:12]}-**"


# --- CNJ unified process number (NNNNNNN-DD.AAAA.J.TR.OOOO) -------------------------------

CNJ_PATTERN = re.compile(r"^(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})$")


def cnj_check_digits(sequence: str, year: str, segment: str, court: str, origin: str) -> str:
    """Check digits by ISO 7064 mod 97-10, as in the CNJ numbering rules (VERIFY ID-3)."""
    number = int(f"{sequence}{year}{segment}{court}{origin}00")
    return f"{98 - (number % 97):02d}"


def parse_cnj(value: str) -> str | None:
    """Return the number in canonical format if valid, else None."""
    compact = value.strip()
    if compact.isdigit() and len(compact) == 20:
        compact = (
            f"{compact[:7]}-{compact[7:9]}.{compact[9:13]}."
            f"{compact[13]}.{compact[14:16]}.{compact[16:]}"
        )
    m = CNJ_PATTERN.match(compact)
    if not m:
        return None
    seq, dd, year, seg, court, origin = m.groups()
    if cnj_check_digits(seq, year, seg, court, origin) != dd:
        return None
    return f"{seq}-{dd}.{year}.{seg}.{court}.{origin}"
