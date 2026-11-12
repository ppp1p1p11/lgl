# ADR-0009: Legal corpus structure and search without embeddings (for now)

- Status: Accepted (embeddings deferred)
- Date: 2026-11-12

## Context
Research and drafting may only state law that is in an indexed, versioned source (brief
rules 1, 3, 4). Official sources (Planalto, LexML, court portals) and an embedding model
that runs in Brazil are not confirmed yet (VERIFY SRC-1 to SRC-5, AI-3), and the founder
asked to leave external APIs for last.

## Decision
- Global, read-only tables: `legal_documents` → `legal_units` (article, parágrafo,
  inciso, alínea) → `legal_unit_versions` (text, `valid_from`/`valid_to`, status). The
  application role can only SELECT them; ingestion runs as the owner role.
- Ingestion parses plain text structurally (one chunk = one legal unit, never a fixed
  token window) and is idempotent: unchanged text is skipped, changed text closes the
  old version and opens a new one.
- Search is Portuguese full-text search. Score = share of the question's distinct terms
  found in the unit, plus a small proximity bonus and a boost when the question names
  the article, multiplied by the source-type weight (legislação 1.0 … doutrina 0.4;
  VERIFY SRC-11). Only versions valid on the requested date are returned, and the answer
  states that date.
- The `embedding` column exists but is not filled. Semantic search and re-ranking are
  added once AI-3/AI-4 are settled.
- Until official texts are loaded, a small sample of CPC provisions about deadlines
  ships with `review_status = demonstracao_nao_conferida`. It was typed from memory, is
  labelled as unverified everywhere it appears, and is not served in production.

## Consequences
- Research works end to end without any external service, and every citation points to
  an exact unit and version.
- Keyword search misses paraphrases ("tempo para se defender" vs "contestação"). The
  evaluation set for Phase 3 must measure this before the pilot.
- Loading the real corpus is a data task (official text files + a lawyer's check), not a
  code change.

## Alternatives considered
- Calling an embedding API now: needs a provider decision and sends text abroad.
- Letting the model answer from its own knowledge with a disclaimer: violates rule 1.
