# ADR-0006: AI model and gateway

- Status: Accepted (founder chose "best results" for Q10, 2026-10-29)
- Date: 2026-11-02

## Context
Phase 2b adds AI on documents: document type, key facts and a cited summary. The brief
requires (§2, §4):
- no ungrounded claims;
- lawyer approval of consequential outputs;
- documents treated as untrusted data;
- personal data redacted or minimized before leaving our systems;
- every AI call logged without raw prompts;
- per-firm cost limits.

## Decision
- **One gateway** (`legalos.gateway`) is the only code that calls an AI provider. A test
  fails if any other module imports the Anthropic SDK. For every call the gateway:
  - checks the firm's monthly budget,
  - redacts identifiers (CPF, CNPJ, RG, OAB nº, e-mail, phone, CEP) and restores them in
    the answer,
  - logs purpose, model, tokens, cost and latency (never prompts or answers),
  - turns refusals and truncated answers into explicit errors.
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`), configurable by `LEGALOS_AI_MODEL`.
  Effort is set per task: low for classification, high for extraction and summaries.
  Server-side fallback is enabled (`fallbacks: "default"`), so a safety-classifier false
  positive does not stop the workflow. The cost log uses the model that actually
  answered.
- **Grounding:**
  - Facts must come with a verbatim quote. A quote not found in the document's
    extracted text is discarded.
  - The summary uses Claude's citations to exact passages, and each citation is checked
    again against the text.
  - Passages that make a claim without a verified citation are marked "não verificado".
- **Injection defence:**
  - Document text is sent only inside document blocks.
  - The system prompt says that text is untrusted data.
  - The model has no tools, so it cannot send anything anywhere.
  - Verification rejects invented content.
- **Review:**
  - Outputs are versioned and immutable.
  - Removing wrong items creates a new version.
  - Only sócio/advogado can approve or reject, and the decision is tied to one specific
    version.
- **Demo provider:** without `ANTHROPIC_API_KEY` (outside production), a rule-based
  simulated AI follows the same contract, so the full flow can be tried locally. The UI
  labels it "IA simulada".

## Consequences
- **The Anthropic API currently offers no inference in Brazil** (geography options are
  "global" and "us"). Using it is an international data transfer under LGPD. Until a
  lawyer approves the transfer setup (VERIFY REG-2) or in-region inference is available
  (VERIFY AI-1), only synthetic or public documents may be analysed.
- Costs are visible per call and capped per firm (default US$ 50/month, set by a sócio).
- The real model has not been exercised in CI (no API key in CI); behaviour is tested with
  a scripted provider that also plays a misbehaving model. A live evaluation must be run
  once a key is configured.

## Alternatives considered
- **A cheaper model by default:** rejected per founder's "best results" choice. It can be
  switched by configuration after measuring quality.
- **Asking the model for block numbers instead of quotes for facts:** easier to fake.
  Verbatim quotes can be checked mechanically.
