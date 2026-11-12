"""Draft templates (peças). Structure and boilerplate only: every template is a starting
point for a lawyer and has not been reviewed by one yet (docs/VERIFY.md DRAFT-1).

Section kinds:
- "fixed": text with {placeholders} filled from the processo;
- "ai_facts": written by the AI from the processo's documents, with citations;
- "ai_law": written by the AI from the indexed legal corpus, with citations;
- "manual": left for the lawyer, with a [PREENCHER: …] marker.
"""

from dataclasses import dataclass
from typing import Literal

SectionKind = Literal["fixed", "ai_facts", "ai_law", "manual"]


@dataclass(frozen=True)
class Section:
    kind: SectionKind
    heading: str | None
    body: str = ""


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    sections: tuple[Section, ...]


_FECHO = Section(
    "fixed",
    None,
    "Nestes termos, pede deferimento.\n\n{cidade}, {data}.\n\n{advogado_nome}\n{advogado_oab}",
)
_ENDERECAMENTO = Section(
    "fixed",
    None,
    "EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA {vara} DA COMARCA DE {comarca}",
)

TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in (
        Template(
            "peticao_inicial",
            "Petição inicial",
            "Endereçamento, qualificação, fatos, direito, pedidos e valor da causa.",
            (
                _ENDERECAMENTO,
                Section(
                    "fixed",
                    None,
                    "{cliente_qualificacao}, por seu advogado que esta subscreve, vem, "
                    "respeitosamente, à presença de Vossa Excelência, propor a presente "
                    "AÇÃO [PREENCHER: nome da ação] em face de {parte_contraria}, pelos "
                    "fatos e fundamentos a seguir expostos.",
                ),
                Section("ai_facts", "DOS FATOS"),
                Section("ai_law", "DO DIREITO"),
                Section(
                    "manual", "DOS PEDIDOS", "Diante do exposto, requer: [PREENCHER: pedidos]."
                ),
                Section(
                    "manual", "DO VALOR DA CAUSA", "Dá-se à causa o valor de R$ [PREENCHER: valor]."
                ),
                _FECHO,
            ),
        ),
        Template(
            "contestacao",
            "Contestação",
            "Endereçamento, síntese da inicial, mérito e pedidos.",
            (
                _ENDERECAMENTO,
                Section("fixed", None, "Processo nº {numero_processo}"),
                Section(
                    "fixed",
                    None,
                    "{cliente_nome}, já qualificado(a) nos autos da ação em epígrafe, que "
                    "lhe move {parte_contraria}, vem, por seu advogado, apresentar "
                    "CONTESTAÇÃO, pelas razões de fato e de direito a seguir expostas.",
                ),
                Section("ai_facts", "SÍNTESE DOS FATOS"),
                Section("ai_law", "DO MÉRITO"),
                Section(
                    "manual", "DOS PEDIDOS", "Diante do exposto, requer: [PREENCHER: pedidos]."
                ),
                _FECHO,
            ),
        ),
        Template(
            "notificacao_extrajudicial",
            "Notificação extrajudicial",
            "Identificação das partes, fatos e providência exigida.",
            (
                Section("fixed", None, "NOTIFICAÇÃO EXTRAJUDICIAL"),
                Section(
                    "fixed",
                    None,
                    "NOTIFICANTE: {cliente_qualificacao}.\nNOTIFICADO(A): {parte_contraria}.",
                ),
                Section("ai_facts", "DOS FATOS"),
                Section(
                    "manual",
                    "DA NOTIFICAÇÃO",
                    "Fica o(a) notificado(a) ciente de que [PREENCHER: providência exigida "
                    "e prazo para cumprimento].",
                ),
                Section("fixed", None, "{cidade}, {data}.\n\n{advogado_nome}\n{advogado_oab}"),
            ),
        ),
        Template(
            "contrato_honorarios",
            "Contrato de honorários advocatícios",
            "Partes e cláusulas a preencher (objeto, honorários, prazo, foro).",
            (
                Section("fixed", None, "CONTRATO DE PRESTAÇÃO DE SERVIÇOS ADVOCATÍCIOS"),
                Section(
                    "fixed", None, "CONTRATANTE: {cliente_qualificacao}.\nCONTRATADA: {escritorio}."
                ),
                Section(
                    "manual", "CLÁUSULA PRIMEIRA - DO OBJETO", "[PREENCHER: serviços contratados]."
                ),
                Section(
                    "manual",
                    "CLÁUSULA SEGUNDA - DOS HONORÁRIOS",
                    "[PREENCHER: valor, forma de pagamento e honorários de êxito].",
                ),
                Section(
                    "manual",
                    "CLÁUSULA TERCEIRA - DO PRAZO",
                    "[PREENCHER: vigência e condições de rescisão].",
                ),
                Section("manual", "CLÁUSULA QUARTA - DO FORO", "[PREENCHER: foro eleito]."),
                Section("fixed", None, "{cidade}, {data}.\n\nCONTRATANTE\n\nCONTRATADA"),
            ),
        ),
    )
}
