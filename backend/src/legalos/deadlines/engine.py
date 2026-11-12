"""Deadline (prazo) calculation. Pure functions: no database, no clock.

The engine only *proposes* a date and shows every step of its reasoning (brief rule 5).
A lawyer confirms or rejects the proposal; nothing here is ever final on its own.

Legal basis of each rule is cited next to the code that applies it. The citations are
tracked in docs/VERIFY.md (DL-1 to DL-9) until a lawyer confirms them against the
official texts.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

RuleSet = Literal["cpc", "clt", "jec"]
TriggerKind = Literal["disponibilizacao_dje", "ciencia"]
Unit = Literal["dias_uteis", "dias_corridos"]

WEEKDAYS = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]

MAX_DAYS = 3650


@dataclass(frozen=True)
class RuleSetInfo:
    id: RuleSet
    label: str
    business_days_basis: str
    start_basis: str
    recess_basis: str


RULE_SETS: dict[str, RuleSetInfo] = {
    "cpc": RuleSetInfo(
        "cpc",
        "Processo civil (CPC)",
        business_days_basis="CPC, art. 219",
        start_basis="CPC, art. 224, caput",
        recess_basis="CPC, art. 220",
    ),
    "clt": RuleSetInfo(
        "clt",
        "Processo do trabalho (CLT)",
        business_days_basis="CLT, art. 775",
        start_basis="CLT, art. 775",
        recess_basis="CLT, art. 775-A",
    ),
    "jec": RuleSetInfo(
        "jec",
        "Juizados Especiais Cíveis (Lei 9.099/1995)",
        business_days_basis="Lei 9.099/1995, art. 12-A",
        start_basis="CPC, art. 224, caput (aplicação subsidiária)",
        recess_basis="CPC, art. 220 (aplicação subsidiária; confirme no juizado)",
    ),
}


@dataclass(frozen=True)
class Preset:
    id: str
    rule_set: RuleSet
    label: str
    days: int
    basis: str


# Common deadlines, offered as shortcuts. Not yet reviewed by a lawyer (VERIFY DL-10):
# the UI says so, and the user can always type the number of days.
PRESETS: tuple[Preset, ...] = (
    Preset("cpc_contestacao", "cpc", "Contestação", 15, "CPC, art. 335"),
    Preset("cpc_replica", "cpc", "Réplica", 15, "CPC, arts. 350 e 351"),
    Preset("cpc_apelacao", "cpc", "Apelação", 15, "CPC, art. 1.003, § 5º"),
    Preset("cpc_contrarrazoes", "cpc", "Contrarrazões de apelação", 15, "CPC, art. 1.010, § 1º"),
    Preset("cpc_agravo_instrumento", "cpc", "Agravo de instrumento", 15, "CPC, art. 1.003, § 5º"),
    Preset("cpc_embargos_declaracao", "cpc", "Embargos de declaração", 5, "CPC, art. 1.023"),
    Preset("cpc_manifestacao", "cpc", "Manifestação sem prazo fixado", 5, "CPC, art. 218, § 3º"),
    Preset("clt_recurso_ordinario", "clt", "Recurso ordinário", 8, "CLT, art. 895"),
    Preset("clt_contrarrazoes", "clt", "Contrarrazões", 8, "CLT, art. 900"),
    Preset("clt_embargos_declaracao", "clt", "Embargos de declaração", 5, "CLT, art. 897-A"),
    Preset("jec_recurso_inominado", "jec", "Recurso inominado", 10, "Lei 9.099/1995, art. 42"),
    Preset(
        "jec_embargos_declaracao", "jec", "Embargos de declaração", 5, "Lei 9.099/1995, art. 49"
    ),
)

DOUBLING_REASONS: dict[str, str] = {
    "fazenda_publica": "Fazenda Pública (CPC, art. 183)",
    "ministerio_publico": "Ministério Público (CPC, art. 180)",
    "defensoria_publica": "Defensoria Pública (CPC, art. 186)",
    "litisconsortes": "Litisconsortes com procuradores de escritórios distintos, em autos "
    "físicos (CPC, art. 229)",
}


@dataclass(frozen=True)
class Holiday:
    day: date
    name: str


@dataclass(frozen=True)
class DeadlineInput:
    rule_set: RuleSet
    trigger_kind: TriggerKind
    trigger_date: date
    days: int
    unit: Unit = "dias_uteis"
    doubled_reason: str | None = None


@dataclass(frozen=True)
class Step:
    label: str
    detail: str


@dataclass
class DeadlineResult:
    proposed_date: date
    counting_start: date
    effective_days: int
    steps: list[Step] = field(default_factory=list)
    skipped_holidays: list[Holiday] = field(default_factory=list)
    recess_days_skipped: int = 0
    weekend_days_skipped: int = 0


def fmt(d: date) -> str:
    return f"{d.strftime('%d/%m/%Y')} ({WEEKDAYS[d.weekday()]})"


def in_recess(d: date) -> bool:
    """20 December to 20 January, inclusive (CPC art. 220; CLT art. 775-A)."""
    return (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm), for movable-date suggestions."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def movable_suggestions(year: int) -> list[Holiday]:
    """Dates on which courts usually have no expediente, but which depend on each court's
    own calendar. Offered as suggestions for the firm to confirm, never applied silently."""
    e = easter(year)
    return [
        Holiday(e - timedelta(days=48), "Carnaval (segunda-feira)"),
        Holiday(e - timedelta(days=47), "Carnaval (terça-feira)"),
        Holiday(e - timedelta(days=2), "Sexta-feira Santa"),
        Holiday(e + timedelta(days=60), "Corpus Christi"),
    ]


def calculate(inp: DeadlineInput, holidays: dict[date, str]) -> DeadlineResult:
    """Propose a due date. `holidays` maps each day without court business to its name."""
    if inp.days < 1 or inp.days > MAX_DAYS:
        raise ValueError("days out of range")
    if inp.doubled_reason is not None and inp.doubled_reason not in DOUBLING_REASONS:
        raise ValueError("unknown doubling reason")
    rules = RULE_SETS[inp.rule_set]
    procedural = inp.unit == "dias_uteis"
    steps: list[Step] = []
    skipped: list[Holiday] = []
    counters = {"recess": 0, "weekend": 0}

    def is_business_day(d: date, *, count_skips: bool = False) -> bool:
        if d.weekday() >= 5:
            if count_skips:
                counters["weekend"] += 1
            return False
        if d in holidays:
            if count_skips:
                skipped.append(Holiday(d, holidays[d]))
            return False
        if procedural and in_recess(d):
            if count_skips:
                counters["recess"] += 1
            return False
        return True

    def next_business_day(d: date, check: Callable[[date], bool]) -> date:
        d += timedelta(days=1)
        while not check(d):
            d += timedelta(days=1)
        return d

    # 1. The event and, for the Diário da Justiça eletrônico, the publication date.
    if inp.trigger_kind == "disponibilizacao_dje":
        steps.append(
            Step(
                "Evento",
                f"Disponibilização no Diário da Justiça eletrônico em {fmt(inp.trigger_date)}.",
            )
        )
        # Publication is deemed to happen on the first business day after the text is made
        # available (CPC art. 224, § 2º; Lei 11.419/2006, art. 4º, § 3º).
        reference = next_business_day(inp.trigger_date, is_business_day)
        steps.append(
            Step(
                "Publicação",
                f"Considera-se publicado no primeiro dia útil seguinte à disponibilização: "
                f"{fmt(reference)} (CPC, art. 224, § 2º; Lei 11.419/2006, art. 4º, § 3º).",
            )
        )
        start_basis = "CPC, art. 224, § 3º"
    else:
        reference = inp.trigger_date
        steps.append(Step("Evento", f"Ciência/intimação em {fmt(reference)}."))
        start_basis = rules.start_basis

    # 2. Doubling.
    effective_days = inp.days
    if inp.doubled_reason:
        effective_days = inp.days * 2
        steps.append(
            Step(
                "Prazo em dobro",
                f"{inp.days} dias em dobro = {effective_days} dias: "
                f"{DOUBLING_REASONS[inp.doubled_reason]}. Confira se a lei não fixa prazo próprio "
                f"para o ente, caso em que não há dobra.",
            )
        )

    # 3. Counting.
    if procedural:
        # The day of the event is excluded and counting starts on the next business day.
        start = next_business_day(reference, is_business_day)
        steps.append(
            Step(
                "Início da contagem",
                f"Exclui-se o dia do começo; a contagem inicia no primeiro dia útil seguinte: "
                f"{fmt(start)} ({start_basis}).",
            )
        )
        steps.append(
            Step(
                "Contagem",
                f"{effective_days} dias úteis ({rules.business_days_basis}), incluindo o dia do "
                f"vencimento.",
            )
        )
        current, counted = start, 1
        while counted < effective_days:
            current += timedelta(days=1)
            if is_business_day(current, count_skips=True):
                counted += 1
        due = current
    else:
        start = reference + timedelta(days=1)
        steps.append(
            Step(
                "Início da contagem",
                f"Exclui-se o dia do começo; a contagem inicia em {fmt(start)} (Código Civil, "
                f"art. 132, caput).",
            )
        )
        steps.append(
            Step(
                "Contagem",
                f"{effective_days} dias corridos (prazo não processual: sem suspensão no recesso "
                f"e sem exclusão de fins de semana).",
            )
        )
        due = reference + timedelta(days=effective_days)
        if not is_business_day(due):
            moved = next_business_day(due, is_business_day)
            steps.append(
                Step(
                    "Prorrogação",
                    f"O vencimento cairia em {fmt(due)}, dia sem expediente; prorroga-se para o "
                    f"dia útil seguinte (Código Civil, art. 132, § 1º).",
                )
            )
            due = moved

    # 4. What was not counted, so the lawyer can check it.
    if procedural:
        parts = [f"{counters['weekend']} sábado(s)/domingo(s)"]
        if skipped:
            names = "; ".join(f"{h.day.strftime('%d/%m/%Y')} {h.name}" for h in skipped)
            parts.append(f"feriados/dias sem expediente cadastrados: {names}")
        if counters["recess"]:
            parts.append(
                f"{counters['recess']} dia(s) útil(eis) no recesso de 20/12 a 20/01 "
                f"({rules.recess_basis})"
            )
        steps.append(Step("Dias não contados", "; ".join(parts) + "."))

    steps.append(Step("Vencimento proposto", fmt(due) + "."))
    steps.append(
        Step(
            "Atenção",
            "Esta é uma proposta. Confira o calendário do tribunal e da comarca: feriados "
            "locais, pontos facultativos e suspensões de expediente não cadastrados alteram a "
            "data. A base legal indicada ainda não foi revisada por advogado.",
        )
    )
    return DeadlineResult(
        proposed_date=due,
        counting_start=start,
        effective_days=effective_days,
        steps=steps,
        skipped_holidays=skipped,
        recess_days_skipped=counters["recess"],
        weekend_days_skipped=counters["weekend"],
    )
