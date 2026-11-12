"""Human review of AI outputs (brief rule 2).

- Anyone who may draft AI work can send a draft for review or remove items it got wrong
  (which creates a new version).
- Only roles with APPROVE_AI_OUTPUTS (sócio, advogado) can approve or reject, and the
  decision is tied to a specific version: approving version 2 says nothing about 3.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from legalos.ai.models import AiApproval, AiCitation, AiOutput, AiOutputVersion
from legalos.audit.service import record
from legalos.matters.service import add_event

ITEM_LISTS = {"facts": "facts", "summary": "segments", "research_answer": "segments"}


KIND_LABELS = {
    "facts": "Fatos extraídos por IA",
    "summary": "Resumo por IA",
    "research_answer": "Pesquisa jurídica",
    "draft": "Minuta",
}


def _event(db: Session, output: AiOutput, *, kind: str, summary: str, **kwargs: Any) -> None:
    """Timeline entry for outputs linked to a processo (general research has none)."""
    if output.matter_id is not None:
        add_event(
            db,
            tenant_id=output.tenant_id,
            matter_id=output.matter_id,
            kind=kind,
            summary=summary,
            **kwargs,
        )


class ReviewError(Exception):
    def __init__(self, code: str, status_code: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def current_version(db: Session, output: AiOutput) -> AiOutputVersion:
    version = db.scalar(
        select(AiOutputVersion).where(
            AiOutputVersion.ai_output_id == output.id,
            AiOutputVersion.version_no == output.current_version_no,
        )
    )
    assert version is not None
    return version


def _check_base(output: AiOutput, version_no: int) -> None:
    if version_no != output.current_version_no:
        raise ReviewError("stale_version")


def submit_for_review(
    db: Session, *, user_id: uuid.UUID, output: AiOutput, version_no: int
) -> None:
    _check_base(output, version_no)
    if output.status != "rascunho":
        raise ReviewError("invalid_status")
    output.status = "em_revisao"
    _event(
        db,
        output,
        kind="ia_enviada_revisao",
        summary=f"{KIND_LABELS[output.kind]}: enviado(a) para revisão",
        actor_user_id=user_id,
        source="manual",
        payload={"ai_output_id": str(output.id), "version_no": version_no},
    )


def decide(
    db: Session,
    *,
    user_id: uuid.UUID,
    output: AiOutput,
    version_no: int,
    decision: str,
    comment: str | None,
    ip: str | None,
) -> AiApproval:
    _check_base(output, version_no)
    if output.status in ("aprovado", "rejeitado"):
        raise ReviewError("already_decided")
    version = current_version(db, output)
    approval = AiApproval(
        tenant_id=output.tenant_id,
        ai_output_version_id=version.id,
        approver_user_id=user_id,
        decision=decision,
        comment=comment,
    )
    db.add(approval)
    output.status = decision
    db.flush()
    label = "aprovado(a)" if decision == "aprovado" else "rejeitado(a)"
    _event(
        db,
        output,
        kind=f"ia_{decision}",
        summary=f"{KIND_LABELS[output.kind]}: {label} (versão {version_no})",
        actor_user_id=user_id,
        source="manual",
        payload={"ai_output_id": str(output.id), "version_no": version_no},
    )
    record(
        db,
        f"ai_output.{decision}",
        tenant_id=output.tenant_id,
        actor_user_id=user_id,
        entity_type="ai_output_version",
        entity_id=str(version.id),
        ip=ip,
    )
    return approval


def remove_items(
    db: Session,
    *,
    user_id: uuid.UUID,
    output: AiOutput,
    base_version_no: int,
    remove: list[int],
    note: str | None,
) -> AiOutputVersion:
    """New version without the given facts/segments. Citations follow the kept items."""
    _check_base(output, base_version_no)
    base = current_version(db, output)
    key = ITEM_LISTS[output.kind]
    items: list[Any] = base.content[key]
    if not remove or any(i < 0 or i >= len(items) for i in remove):
        raise ReviewError("invalid_items", 400)
    removed = set(remove)
    new_index = {}
    kept: list[Any] = []
    for i, item in enumerate(items):
        if i not in removed:
            new_index[i] = len(kept)
            kept.append(item)
    new_version = AiOutputVersion(
        id=uuid.uuid4(),
        tenant_id=output.tenant_id,
        ai_output_id=output.id,
        version_no=base.version_no + 1,
        content={**base.content, key: kept},
        created_by_ai=False,
        created_by=user_id,
        note=note,
    )
    db.add(new_version)
    db.flush()
    for citation in db.scalars(
        select(AiCitation).where(AiCitation.ai_output_version_id == base.id)
    ):
        if citation.item_index in new_index:
            db.add(
                AiCitation(
                    tenant_id=citation.tenant_id,
                    ai_output_version_id=new_version.id,
                    item_index=new_index[citation.item_index],
                    document_version_id=citation.document_version_id,
                    legal_unit_version_id=citation.legal_unit_version_id,
                    page_number=citation.page_number,
                    char_start=citation.char_start,
                    char_end=citation.char_end,
                    quoted_text=citation.quoted_text,
                    verification=citation.verification,
                )
            )
    output.current_version_no = new_version.version_no
    output.status = "rascunho"  # a changed output needs a new decision
    db.flush()
    return new_version
