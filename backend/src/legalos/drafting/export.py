"""Export a draft to .docx (lawyers work in Word).

The file states its review status on the first line when it has not been approved, and
ends with a review report (not meant for filing) listing passages without a verified
source and fields still to fill in.
"""

import io
from typing import Any

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

STATUS_LABELS = {
    "rascunho": "RASCUNHO — NÃO APROVADO",
    "em_revisao": "EM REVISÃO — NÃO APROVADO",
    "rejeitado": "REJEITADO",
}


def render_docx(
    content: dict[str, Any], *, status: str, version_no: int, approval_line: str | None
) -> bytes:
    document = docx.Document()
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)

    if status != "aprovado":
        banner = document.add_paragraph()
        banner.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = banner.add_run(f"{STATUS_LABELS.get(status, status.upper())} (versão {version_no})")
        run.bold = True
        run.font.color.rgb = RGBColor(0xA4, 0x26, 0x2C)

    unverified: list[str] = []
    for section in content["sections"]:
        if section.get("heading"):
            heading = document.add_paragraph()
            heading.add_run(section["heading"]).bold = True
        for segment in section["segments"]:
            for block in segment["text"].split("\n"):
                if not block.strip():
                    continue
                paragraph = document.add_paragraph(block.strip())
                paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            if segment.get("unverified"):
                unverified.append(segment["text"].strip())

    document.add_page_break()  # type: ignore[no-untyped-call]
    title = document.add_paragraph()
    title.add_run("RELATÓRIO DE CONFERÊNCIA (não protocolar)").bold = True
    document.add_paragraph(
        approval_line or f"Situação: {STATUS_LABELS.get(status, status)} (versão {version_no})."
    )
    if content.get("provider") == "demo":
        document.add_paragraph(
            "Trechos de IA gerados pela IA simulada (demonstração), sem análise real."
        )
    document.add_paragraph("Campos a preencher:").runs[0].bold = True
    for marker in content.get("pending") or ["nenhum"]:
        document.add_paragraph(str(marker), style="List Bullet")
    document.add_paragraph("Trechos sem fonte verificada:").runs[0].bold = True
    for text in unverified or ["nenhum"]:
        document.add_paragraph(text, style="List Bullet")

    out = io.BytesIO()
    document.save(out)
    return out.getvalue()
