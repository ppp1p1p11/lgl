# Before a real firm uses LegalOS

Everything in the app today runs on fictional data and a simulated AI. This is the list
of what stands between that and a pilot, in the order it makes sense to do it. Items in
**bold** need the founder; details and sources are in [`VERIFY.md`](VERIFY.md).

## 1. Things only a Brazilian lawyer can sign off

| What | Why | Where |
|---|---|---|
| **Deadline rules and preset deadlines** | A wrong date is the worst error the product can make. The rules were written from the brief and general knowledge, not checked against the official texts | VERIFY DL-1 to DL-12; `backend/src/legalos/deadlines/engine.py` |
| **Draft templates** | Wording and mandatory elements of each piece; fee-contract clauses | VERIFY DRAFT-1 |
| **LGPD basics and the international-transfer question** | The AI runs outside Brazil. No real client data until this is settled | VERIFY REG-1 to REG-4, AI-1, AI-2 |
| **OAB rules on AI use and advertising** | How the product and its customers may describe AI features | VERIFY REG-5 to REG-7 |
| Source weights in research | Which kind of source outranks which | VERIFY SRC-11 |

## 2. The real AI

1. **Create the Anthropic API key** and store it in the cloud environment's settings (or
   in `.local/env` on your computer). Never in chat, never in the repository.
2. Run `scripts/ai_eval.py --yes` (document analysis) and extend it to research and
   drafting (VERIFY AI-6, AI-7). Costs a few dollars.
3. Decide the monthly AI budget per firm (Administração → Uso da IA).

## 3. The real legal texts

1. Confirm how each official source may be used and downloaded (VERIFY SRC-1 to SRC-7).
2. Load the official consolidated texts for the pilot areas (CPC, CLT, CTN, CDC, Código
   Civil, súmulas) with `python -m legalos.corpus.ingest`, replacing the demonstration
   sample (VERIFY SRC-12).
3. Build the evaluation set from the brief (at least 50 questions with the provisions a
   correct answer must cite) and measure the research before anyone relies on it.
4. Choose an embedding model that can run in Brazil and add semantic search (VERIFY AI-3).

## 4. Outside services still to connect

| Service | Used for | Blocked by |
|---|---|---|
| DataJud (CNJ) | Automatic case movements, instead of typing them | VERIFY SRC-6 (access rules, key) |
| Transactional e-mail | Invitations, password reset, deadline reminders | VERIFY INF-5 |
| Cloud in Brazil (database, storage, secrets, backups) | Production deployment | VERIFY INF-1, INF-6 |
| Error tracking | Knowing when something breaks | VERIFY INF-4 |

## 5. Engineering work that remains

- Compliance features from the brief's Phase 6: retention periods, legal hold,
  data-subject requests, incident log, record of processing.
- Backups with a tested restore; scheduled housekeeping job; antivirus scan of uploads;
  API rate limiting; secrets in a key-management service.
- An external security review.
- Firm-editable templates, deadline reminders, a calendar view.

## 6. Already in place

Tenant isolation enforced by the database and tested; MFA; roles; audit log; AI gateway
with redaction, budget and cost log; immutable AI output versions with approval by a
named lawyer; verified citations; deadline proposals with visible reasoning; automated
tests and CI on every change.
