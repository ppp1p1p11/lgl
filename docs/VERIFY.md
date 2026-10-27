# VERIFY.md — facts we must confirm before relying on them

Rule (brief §0): we never assume facts about Brazilian law, court APIs or
vendor capabilities. Each item below lists **what** to check, **where** to
check it, **who** checks it, and **which phase** depends on it. When an item
is confirmed, fill in the result, date, and the person or link that confirmed
it — don't delete the row.

Owner key: **F** = founder · **L** = Brazilian lawyer (compliance review) ·
**C** = Claude Code during the phase (reading public docs; the result still
needs a human to sign off when it affects legal or contractual matters).

Status key: ⬜ open · 🟨 partially checked · ✅ confirmed · ❌ rejected / not possible

---

## 1. AI models and data residency

| # | Question | Where to check | Owner | Needed by | Status |
|---|---|---|---|---|---|
| AI-1 | Can the model we want (e.g. a current Claude model) run with **inference inside the São Paulo region** (e.g. AWS Bedrock `sa-east-1`)? Is it in-region only, or is a "cross-region inference profile" used that may route outside Brazil? | AWS Bedrock docs: "Supported models by Region" and "Cross-region inference"; Google Vertex AI and Azure equivalents | C, then F confirms with the cloud account | Phase 2 | ⬜ |
| AI-2 | Data-use terms: does the provider train on our inputs/outputs? What is its retention period, and is zero-data-retention available? | Anthropic commercial terms + data retention docs; AWS Bedrock data-protection page | F (contract), C (summary) | Phase 2 | ⬜ |
| AI-3 | Which **embedding model** has strong Portuguese quality *and* can run in Brazil? Candidates: an embedding model hosted on a cloud's São Paulo region, or an open-source multilingual model (e.g. BGE-M3, multilingual-E5) self-hosted in Brazil. Check licence, dimensions, cost | Model cards and licences; cloud region model lists; our own eval in Phase 3 | C | Phase 3 (ADR) | ⬜ |
| AI-4 | Does the re-ranking model (if hosted) run in Brazil? | Same as AI-3 | C | Phase 3 | ⬜ |
| AI-5 | Per-token prices in the chosen region, so the cost log uses BRL figures that are right | Provider pricing pages | C | Phase 2 | ⬜ |

## 2. Infrastructure in Brazil

| # | Question | Where to check | Owner | Needed by | Status |
|---|---|---|---|---|---|
| INF-1 | Which cloud? Confirm that the São Paulo region of the chosen provider offers: managed PostgreSQL **with the pgvector extension** (which version?), S3-compatible storage with encryption at rest, backups kept in-region, a container service, and log storage | Provider region service lists; managed Postgres "supported extensions" page | C, F decides | Phase 1 end / Phase 6 | ⬜ |
| INF-2 | pgvector: does the version we get support filtered approximate search that still returns enough results when filtered by tenant under RLS (e.g. "iterative index scans")? | pgvector changelog / README | C | Phase 1 | ⬜ |
| INF-3 | OCR: is a managed OCR service (e.g. AWS Textract) available in São Paulo with good Portuguese support, or do we self-host (e.g. Tesseract with the `por` model, or OCRmyPDF)? Compare accuracy on real scanned court PDFs | Provider region list + language support page; a test on 10 real anonymized PDFs | C + F supplies sample PDFs | Phase 2 | ⬜ |
| INF-4 | Error tracking / observability: where does the vendor store data? Is a Brazil or self-hosted option available? (e.g. Sentry SaaS data regions vs self-hosted Sentry/GlitchTip) | Vendor data-residency docs | C, F decides | Phase 1 (local), Phase 6 (prod) | ⬜ |
| INF-5 | Transactional email (invites, MFA recovery): which provider can send from Brazil, and does it store message content? | Provider docs | C | Phase 1 end | ⬜ |

## 3. Legal sources — terms and technical access

For each source: is there an official API or bulk download? What do the
terms of use allow (automated access, rate limits, reuse in a commercial
product, attribution)? Does robots.txt allow it? Never scrape in a way the
terms prohibit (brief §4).

| # | Source | What to verify | Where to check | Owner | Needed by | Status |
|---|---|---|---|---|---|---|
| SRC-1 | **LexML Brasil** | Current API (SRU search? bulk XML?), URN format for norms and units (article level?), terms of reuse, update frequency | lexml.gov.br documentation pages | C | Phase 3 | ⬜ |
| SRC-2 | **Planalto** | Whether there is any API or bulk download; terms/robots for automated retrieval; how amendments and repealed text are marked in the consolidated HTML (strikethrough etc.) so we can derive versions | planalto.gov.br; robots.txt | C, L for terms | Phase 3 | ⬜ |
| SRC-3 | **STF** | Official access to súmulas vinculantes, súmulas, temas de repercussão geral and decisions; open data portal; terms | portal.stf.jus.br | C | Phase 3 | ⬜ |
| SRC-4 | **STJ** | Súmulas, temas repetitivos, IAC, decisions; open data portal and its licence | stj.jus.br, STJ open data portal | C | Phase 3 | ⬜ |
| SRC-5 | **TST** | Súmulas, OJs, precedentes normativos, IRR; access and terms | tst.jus.br | C | Phase 3 | ⬜ |
| SRC-6 | **CNJ DataJud public API** | Current authentication (public API key?), rate limits, which tribunals are covered, which fields come back, update delay, terms of use for commercial products. Confirm it excludes sigilo cases and full case files | CNJ DataJud wiki / API docs | C, L for terms | Phase 5 | ⬜ |
| SRC-7 | Copyright / reuse of **ementas and court decisions** in a paid product | Lei 9.610/1998 (art. 8, IV, on official texts) and each court's terms | L | Phase 3 | ⬜ |
| SRC-8 | Doutrina: we will **not** ingest copyrighted books/articles without a licence. Confirm whether there is any source we may legally use | — | F, L | Later | ⬜ |

## 4. Deadline engine — legal rules

Each rule must be checked against the **official current text** (Planalto) and
the article cited in the code. The article numbers below are what the brief
or our draft plan refers to; **they are not yet verified**.

| # | Rule | Provision to verify | Owner | Needed by | Status |
|---|---|---|---|---|---|
| DL-1 | Procedural deadlines in days count only dias úteis | CPC (Lei 13.105/2015) art. 219 | C, L | Phase 5 | ⬜ |
| DL-2 | Exclude start day, include end day; start/end moved when there is no court business or it closes early / opens late | CPC art. 224 and its paragraphs | C, L | Phase 5 | ⬜ |
| DL-3 | Suspension of deadlines from 20 December to 20 January | CPC art. 220 | C, L | Phase 5 | ⬜ |
| DL-4 | Doubled deadlines: Fazenda Pública, Ministério Público, Defensoria Pública, and litisconsortes with different lawyers from different firms (and the exception for electronic records) | CPC arts. 180, 183, 186, 229 — confirm numbers and exceptions | C, L | Phase 5 | ⬜ |
| DL-5 | When an electronic publication/intimação counts as made, and when counting starts (DJe availability vs publication; 10-day tacit consultation rule for electronic intimação) | Lei 11.419/2006 arts. 4 and 5; CPC arts. 230–231 | C, L | Phase 5 | ⬜ |
| DL-6 | Current CNJ rules on electronic communications (Domicílio Judicial Eletrônico, DJEN) and how they change the trigger date | CNJ resolutions — confirm the current numbers and text | C, L | Phase 5 | ⬜ |
| DL-7 | Labor deadlines under the CLT (counting in dias úteis after the 2017 labor reform; recesso; doubled deadlines in labor courts) | CLT art. 775 and related; Lei 13.467/2017; TST rules | C, L | Phase 5 | ⬜ |
| DL-8 | Juizados Especiais counting rules | Lei 9.099/1995 (incl. any later amendment on dias úteis); Lei 10.259/2001; Lei 12.153/2009 | C, L | Phase 5 | ⬜ |
| DL-9 | National holidays and each court's holiday / suspension calendar: where each tribunal publishes it, and in what format | Federal holiday laws; each TJ/TRF/TRT's annual calendar resolution | C (collect), F/L (choose pilot courts) | Phase 5 | ⬜ |

## 5. Regulation, LGPD, OAB, AI governance

| # | Question | Where to check | Owner | Needed by | Status |
|---|---|---|---|---|---|
| REG-1 | LGPD roles: firm = controller and platform = operator for matter data — confirm and draft the data processing agreement | Lei 13.709/2018; ANPD guidance on controller/operator | L | Before pilot | ⬜ |
| REG-2 | International transfer: if AI inference happens outside Brazil, what is required? Confirm the content and the compliance deadline of the standard contractual clauses | LGPD art. 33; Resolução CD/ANPD nº 19/2024 | L | Phase 2 (design), before pilot | ⬜ |
| REG-3 | Sensitive personal data in case files (health, criminal records, union membership…): legal basis and extra safeguards | LGPD arts. 11 and 7 (incl. exercise of rights in legal proceedings) | L | Before pilot | ⬜ |
| REG-4 | ANPD rules for small processing agents, incident reporting deadlines and DPO (encarregado) obligations that apply to us | ANPD resolutions on small agents and on security incidents — confirm current numbers | L | Before pilot | ⬜ |
| REG-5 | OAB Código de Ética e Disciplina: professional secrecy, and whether AI-assisted work raises duty-of-care issues | Código de Ética e Disciplina da OAB | L | Before pilot | ⬜ |
| REG-6 | OAB Provimento 205/2021 (advertising): limits on how we and our customer firms may market AI features | Provimento 205/2021 current text | L | Before marketing | ⬜ |
| REG-7 | OAB Federal Council recommendations on lawyers' use of generative AI — current text and what it requires of tools (transparency to clients, human review, confidentiality) | OAB Conselho Federal website | L | Phase 2 (UX), before pilot | ⬜ |
| REG-8 | Current status of the AI bill **PL 2338/2023** (which house, latest text), and whether a product sold to private law firms would be "high risk" under it | Câmara/Senado bill pages | L, C (status summary) | Before pilot | ⬜ |
| REG-9 | CNJ resolutions on AI use in the judiciary — confirm the one currently in force and whether any part applies to private tools used by lawyers (likely not, but confirm) | CNJ resolutions page | L | Before pilot | ⬜ |
| REG-10 | Default retention periods for case documents and logs that a firm can reasonably expect (professional and legal record-keeping duties) | OAB rules, Código Civil prescription periods, firm practice | L | Phase 6 | ⬜ |
| REG-11 | Consumer/B2B contract terms (terms of service, SLA, liability cap for AI output errors) | — | L | Before pilot | ⬜ |
| REG-12 | MFA and identity: is any specific standard expected by firms or required by OAB for storing case files? | OAB, client contracts | L, F | Phase 1 end | ⬜ |
