# Phase 2 plan — Matters + documents

Status: approved 2026-10-29. **2a done** (awaiting founder review); 2b not started.

**Goal:** a lawyer creates a client and a processo, uploads PDFs, and gets:
- the extracted text, including from scanned pages
- a document type
- key facts, each pointing to the exact passage it came from
- a cited summary that a lawyer reviews and approves

Practice areas: trabalhista, cível, tributário. First court: TJSP.

## 1. How your answers shape this phase

| Answer | Consequence |
|---|---|
| Q8: "search for top firms' documents" | **We won't do that.** Firms' petitions and contracts are confidential and full of personal data (LGPD, sigilo profissional), even when the case itself is public. Collecting them without consent would put the company at legal risk before it launches. Instead: (a) **synthetic documents** we generate: realistic petições, contestações, sentenças, contratos and CTPS-style records for the three areas, with fictional people, printed to PDF, plus **scanned-looking copies** (rotated, noisy, low-resolution). Because we know their exact text, we can *measure* OCR and extraction accuracy. (b) A small set of **public TJSP decisions**, only after checking the court's terms (VERIFY SRC-9). Real anonymized PDFs from pilot firms remain the best test later |
| Q9: lawyer later | Legal lists (document types, fact types) are marked "não revisado por advogado". **No real client data** enters the system until a lawyer reviews the LGPD basics (VERIFY REG-1, REG-2) |
| Q10: best results | The AI model is **Claude Opus 5.5**, Anthropic's current default model, at $4 per million input tokens and $20 per million output tokens. Effort is tuned per task: low for classification, high for extraction and summaries. Every call's cost is logged, and there's a per-firm monthly cap you can raise |
| Q11: TJSP | Synthetic documents and public samples follow TJSP formats. Labor cases in SP go to TRT-2/TRT-15 and federal tax cases to the federal courts, which matters for Phase 5 calendars (VERIFY SRC-10) |

**Data residency:** Anthropic's API currently offers no Brazil inference region (VERIFY
AI-1), so calls to it are an international data transfer. That's fine for synthetic and
public test data. Before real client data, we either move to Bedrock São Paulo (if the
model is available there) or have a lawyer approve the transfer setup (REG-2).

## 2. Scope

Phase 2 is large, so I propose two checkpoints:

**2a — Matters and documents (no AI)**
- Clients (PF/PJ; CPF/CNPJ encrypted and validated) and processos (CNJ number validated, court, comarca, vara, area, parties, responsible lawyers)
- Matter page: documents and timeline
- Upload: PDF, DOCX, JPG/PNG up to 50 MB, sent directly to storage with signed URLs. The file type is checked by content (not by file name), a SHA-256 hash is stored, and new versions never overwrite old ones
- Text extraction in the worker:
  - the PDF's own text layer when it has one
  - OCR (Tesseract with the Portuguese model, via OCRmyPDF) for scanned pages
  - per-page text, with an OCR confidence score
- Chunking into passages with page and character positions. Portuguese full-text search within a processo
- Side-by-side viewer: the original file next to the extracted text, page by page
- Every document read recorded in the audit log
- Test corpus: synthetic generator plus scanned variants. OCR accuracy (character error rate) is reported in CI

**2b — AI on documents**
- AI gateway:
  - provider interface (Anthropic API first; Bedrock adapter once AI-1 is confirmed)
  - redaction of CPF, CNPJ, RG, OAB nº, CEP/addresses, phone and email, using placeholders that are restored in the answer
  - cost and usage log with no raw prompts
  - per-firm monthly cost cap
- Classification into a document-type list ("não revisado por advogado")
- Fact extraction (dates, amounts, parties, pedidos, deadlines mentioned, case numbers):
  - each fact carries a quote
  - a verifier checks that the quote exists word-for-word in that document
  - unverifiable facts are dropped
- Cited summary using Claude's built-in citations feature, which returns the exact cited passage:
  - our verifier double-checks each citation, and failures are marked "não verificado"
  - a "fatos faltantes" (missing facts) section is included
- Review flow: rascunho → em revisão → aprovado. Edits create a new version, and approval is tied to a version. Only sócio/advogado can approve
- Prompt-injection defenses:
  - document text is sent as quoted data
  - agents get no outbound tools
  - a CI suite of "malicious" documents must not change outputs

## 3. Data model changes

Phase 2a adds these tables, all with RLS and `tenant_id`:
- `clients`, `matters`, `matter_parties`, `matter_members`, `matter_events`
- `documents`, `document_versions`, `document_pages`

It also extends `document_chunks` with version, page and character positions and full-text search.

Phase 2b adds:
- `agent_runs`, `agent_steps`
- `ai_outputs`, `ai_output_versions`
- `citations`, `approvals`
- `extracted_facts`, `gateway_calls`

No embeddings yet: semantic search arrives with the legal corpus in Phase 3, when the embedding model is chosen (AI-3). This avoids deciding it twice.

## 4. New ADRs

- ADR-0005: OCR engine. Self-hosted Tesseract/OCRmyPDF keeps documents in our infrastructure; a managed OCR service is reconsidered only if accuracy on scans is poor (INF-3).
- ADR-0006: AI model and gateway design (Opus 5.5, effort per task, citations, cost caps).
- ADR-0007: Test-document policy (synthetic + verified public sources only).

## 5. Rough AI cost

A typical 20–30 page document is about 15–25 thousand tokens. Classification, extraction and summary together, with the document cached between calls, come to an **estimated US$0.30–0.60 per document**. This is an estimate, to be measured in 2b and reported per workflow.

## 6. Risks

- **OCR quality on bad scans** drives everything downstream. We measure it on the synthetic scans and set a confidence threshold. Below it, the UI warns "texto pode conter erros".
- **Synthetic documents are cleaner than real life.** Real anonymized PDFs from pilot firms are still needed before launch.
- **International transfer** (above). We use only synthetic and public data until it's resolved.
- **Scope.** If 2a takes longer than expected, 2b starts after your review of 2a.

## 7. What you need to do

1. **For 2b only:** create an Anthropic Console account (console.anthropic.com), add billing, set a monthly spend limit, and create an API key. Put it in your local `.env` as `ANTHROPIC_API_KEY`. Never paste it in chat or commit it.
2. Optional: ask 1–2 friendly firms whether they'd share a few anonymized PDFs later, with written consent.
3. Approve (or change) the plan, including the 2a/2b checkpoint and the "no collecting firms' documents" decision.
