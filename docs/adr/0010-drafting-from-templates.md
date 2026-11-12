# ADR-0010: Drafts are assembled from templates, section by section

- Status: Accepted
- Date: 2026-11-12

## Context
Phase 4 asks for drafts (petição inicial, contestação, notificação extrajudicial,
contrato de honorários) that are grounded in the processo's documents and in the legal
corpus, and that a lawyer can edit and approve.

## Decision
- A template is a list of sections of four kinds: fixed text with variables from the
  processo; facts written by the AI from the processo's documents; legal grounds written
  by the AI from the legal corpus; and sections left for the lawyer with a
  `[PREENCHER: …]` marker.
- The AI only writes the two AI sections, and each sentence must carry a citation that
  `ai.verify.locate` finds in the cited document page or legal unit. Sentences that fail
  are kept but flagged "não verificado"; the pointer is dropped.
- The result is an `ai_outputs` row of kind `draft`, so the existing versioning and
  approval apply unchanged. Editing a section creates a new version (marked as edited by
  a person, without citations for that section) and needs a new approval.
- Word export is generated on demand. Unapproved versions carry a "RASCUNHO — NÃO
  APROVADO" banner; every export ends with a review report (pending fields, unverified
  passages) on a separate page.
- Templates live in code for now and have not been reviewed by a lawyer (VERIFY DRAFT-1).

## Consequences
- The model cannot change the structure of a piece or invent parties: those come from
  the processo.
- Firm-specific templates (editable in the app) are a later step; the data model
  (`ai_runs.input.template_id`) does not block it.

## Alternatives considered
- One free-form generation of the whole document: harder to verify and to edit safely.
