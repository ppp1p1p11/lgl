# Architecture (Phase 0 proposal)

Plain-language summary: the lawyer uses a web app. The web app talks to one
backend API. Slow work (OCR, AI summaries, corpus ingestion) runs in a
background worker. Everything is stored in one PostgreSQL database and one
file store, both in Brazil. Every call to an AI model passes through a single
"AI gateway" that strips personal data, logs the call, and picks the provider.

## 1. System overview

```mermaid
flowchart LR
    subgraph User["Escritório (browser)"]
        WEB["Next.js web app<br/>pt-BR UI"]
    end

    subgraph BR["Brazilian cloud region (all data at rest)"]
        API["FastAPI backend<br/>auth · MFA · RBAC · audit"]
        WORKER["Worker<br/>(Postgres job queue)"]
        DB[("PostgreSQL + pgvector<br/>RLS per tenant")]
        S3[("Object storage<br/>encrypted, signed URLs")]
        OCR["OCR engine"]
        GW["AI gateway<br/>redaction · minimization ·<br/>call log · policy routing"]
        LOGS[("Logs + error tracking<br/>PII-scrubbed")]
    end

    subgraph EXT["External (read-only sources)"]
        LEXML["LexML"]
        PLAN["Planalto"]
        COURTS["STF · STJ · TST"]
        DATAJUD["CNJ DataJud<br/>public metadata"]
    end

    subgraph AI["AI providers (via gateway only)"]
        P1["Provider A<br/>(e.g. Bedrock São Paulo — to verify)"]
        P2["Provider B<br/>(e.g. Anthropic API)"]
    end

    WEB -- HTTPS --> API
    API --> DB
    API -- signed URLs --> S3
    API -- enqueue --> DB
    WORKER -- dequeue --> DB
    WORKER --> S3
    WORKER --> OCR
    WORKER --> GW
    API --> GW
    GW --> P1
    GW --> P2
    WORKER -- ingestion --> LEXML
    WORKER -- ingestion --> PLAN
    WORKER -- ingestion --> COURTS
    WORKER -- registered processos only --> DATAJUD
    API --> LOGS
    WORKER --> LOGS
```

Notes:
- There is **no path** from an agent to send email, file at court, or call any
  external write API (brief §4). External connectors are read-only ingestion.
- Whether the AI model can run in São Paulo is open (`docs/VERIFY.md` §AI). If
  it cannot, gateway calls are an international data transfer under LGPD and
  the redaction + SCC work in Phase 6 becomes mandatory before pilot.

## 2. Document intelligence flow (Phase 2)

```mermaid
sequenceDiagram
    actor L as Advogado
    participant W as Web
    participant A as API
    participant Q as Job queue
    participant K as Worker
    participant G as AI gateway

    L->>W: Upload PDF to processo
    W->>A: request upload URL
    A-->>W: signed PUT URL (tenant-scoped key)
    W->>A: upload complete
    A->>Q: enqueue ocr_and_index(document_version)
    K->>Q: claim job
    K->>K: OCR → page text (stored, never executed)
    K->>K: chunk + embed (tenant_id on every chunk)
    K->>G: classify + extract facts (excerpts only, PII redacted)
    G-->>K: facts with source spans
    K->>G: cited summary
    G-->>K: summary + citations
    K->>K: citation verifier (spans must exist in this document)
    K->>A: ai_output status = rascunho
    L->>W: review side-by-side, approve
    W->>A: approval(user, timestamp, output_version)
```

## 3. Research with verified citations (Phase 3)

```mermaid
flowchart TD
    Q["Pergunta do advogado"] --> R["Hybrid retrieval<br/>FTS 'portuguese' + pgvector"]
    R --> RR["Re-rank + apply source hierarchy<br/>+ temporal filter (vigente on date X)"]
    RR --> GEN["Generate answer via gateway<br/>(only retrieved passages in context)"]
    GEN --> V{"Citation verifier<br/>each cite exists in index?<br/>quoted text matches?"}
    V -- yes --> OK["Citation kept, linked to exact passage + version"]
    V -- no --> BAD["Removed or marked 'não verificado'"]
    OK --> OUT["Answer: sources, gaps, status = rascunho"]
    BAD --> OUT
```

## 4. Tenant isolation

```mermaid
flowchart LR
    REQ["Request with session"] --> MW["Auth middleware<br/>resolves user + tenant"]
    MW --> TX["DB transaction:<br/>SET LOCAL app.tenant_id = …"]
    TX --> RLS["RLS policies on every tenant table<br/>incl. document_chunks (vectors)"]
    RLS --> DATA[("Only this tenant's rows")]
    TX -.-> CORPUS[("Legal corpus<br/>global, read-only")]
```

- The application connects with a database role that **does not own** the
  tables and has no `BYPASSRLS`, so a forgotten `WHERE tenant_id = …` cannot
  leak data.
- Vector search runs on the same RLS-protected table; Phase 1 includes a test
  proving tenant A's similarity search never returns tenant B's chunks.
- Object storage keys are prefixed by tenant; the API only signs URLs for keys
  belonging to the caller's tenant.
- Cache keys and log records carry the tenant id; logs never contain document
  text or raw prompts by default.

## 5. AI gateway responsibilities

| Responsibility | How |
|---|---|
| Minimization | Callers pass only the excerpts a task needs; gateway enforces a max context per purpose |
| Redaction | Detect CPF, CNPJ, RG, OAB nº, CEP/addresses, phone, email, health terms; replace with stable placeholders; re-insert on the way back. Per-firm policy |
| Logging | provider, model, purpose, tenant, matter, token counts, cost, latency — **no raw prompt** unless the firm opts in for debugging |
| Routing | Provider abstraction; policy chooses provider/model per purpose and per firm (e.g. "in-Brazil only") |
| Limits | Per-firm cost and rate limits (hardened in Phase 6) |
| Injection defense | Document text is wrapped as quoted data; system prompts state it is untrusted; agents have scoped tools only |
