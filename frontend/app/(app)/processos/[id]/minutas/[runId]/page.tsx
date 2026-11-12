"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { OutputCard } from "@/components/AiAnalysis";
import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { label } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Detail = components["schemas"]["DraftDetail"];
type Output = components["schemas"]["OutputOut"];
type Segment = { index: number; text: string; kind: string; unverified: boolean; edited?: boolean };
type Section = { heading: string | null; kind: string; segments: Segment[] };

/** Text with its [PREENCHER: …] markers highlighted. */
function WithMarkers({ text }: { text: string }) {
  const parts = text.split(/(\[PREENCHER:[^\]]*\])/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("[PREENCHER:") ? (
          <mark key={i} className="pending-field">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

export default function MinutaPage() {
  const { id, runId } = useParams<{ id: string; runId: string }>();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [notFound, setNotFound] = useState(false);

  const fetchDetail = useCallback(async () => {
    const { data } = await api.GET("/api/drafts/{run_id}", {
      params: { path: { run_id: runId } },
    });
    return data ?? null;
  }, [runId]);

  const apply = useCallback((d: Detail | null) => {
    if (d) setDetail(d);
    else setNotFound(true);
  }, []);

  useEffect(() => {
    fetchDetail().then(apply);
  }, [fetchDetail, apply]);

  const pending = detail?.run_status === "queued" || detail?.run_status === "running";
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => fetchDetail().then(apply), 2000);
    return () => clearInterval(timer);
  }, [pending, fetchDetail, apply]);

  if (notFound) return <p>{t.errors.draft_not_found}</p>;
  if (!detail) return <p className="muted">{t.common.loading}</p>;
  const output = detail.output;
  const refresh = () => fetchDetail().then(apply);

  return (
    <>
      <p>
        <Link href={`/processos/${id}`}>← {t.minutas.back}</Link>
      </p>
      <h1>{detail.title ?? detail.template_name}</h1>
      {detail.provider === "demo" && <p className="warning small">{t.common.demo}</p>}
      {pending && <p className="muted">{t.minutas.generating}</p>}
      {detail.run_status === "failed" && (
        <ErrorText
          message={`${t.minutas.failed} ${label(t.ia.errors, detail.error_code)}`.trim()}
        />
      )}
      {output && (
        <section className="card ai-panel">
          <OutputCard output={output} title={t.ia.draft} onChange={refresh} removable={false}>
            {() => <DraftBody output={output} onChange={refresh} />}
          </OutputCard>
          <p>
            <a className="button secondary" href={`/api/ai-outputs/${output.id}/export.docx`}>
              {t.minutas.download}
            </a>
          </p>
          <p className="muted small">{t.minutas.downloadHint}</p>
        </section>
      )}
    </>
  );
}

function DraftBody({ output, onChange }: { output: Output; onChange: () => void }) {
  const canEdit = useCan("draft_ai_outputs") && output.status !== "aprovado";
  const sections = (output.content.sections ?? []) as Section[];
  const pendingFields = (output.content.pending ?? []) as string[];
  const [editing, setEditing] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  function startEdit(index: number) {
    setEditing(index);
    setError(null);
    setText((sections[index]?.segments ?? []).map((s) => s.text.trim()).join("\n\n"));
  }

  async function save(index: number) {
    const { error: apiError } = await api.POST(
      "/api/ai-outputs/{output_id}/sections/{section_index}",
      {
        params: { path: { output_id: output.id, section_index: index } },
        body: { base_version_no: output.version_no, text },
      },
    );
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setEditing(null);
    onChange();
  }

  return (
    <>
      <div className="pending-box">
        <strong>{t.minutas.pending}</strong>
        {pendingFields.length === 0 ? (
          <span className="muted"> {t.minutas.noPending}</span>
        ) : (
          <ul>
            {pendingFields.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="draft">
        {sections.map((section, index) => (
          <section key={index} className="draft-section">
            <header className="page-header">
              <h4>{section.heading ?? ""}</h4>
              <span className="muted small">
                {label(t.minutas.sectionKinds, section.kind)}
                {canEdit && editing !== index && (
                  <>
                    {" · "}
                    <button type="button" className="link" onClick={() => startEdit(index)}>
                      {t.minutas.editSection}
                    </button>
                  </>
                )}
              </span>
            </header>
            {editing === index ? (
              <>
                <textarea
                  rows={Math.min(24, Math.max(6, text.split("\n").length + 2))}
                  value={text}
                  maxLength={50000}
                  onChange={(e) => setText(e.target.value)}
                />
                <ErrorText message={error} />
                <div className="actions">
                  <button type="button" onClick={() => save(index)} disabled={!text.trim()}>
                    {t.minutas.saveSection}
                  </button>
                  <button type="button" className="secondary" onClick={() => setEditing(null)}>
                    {t.common.cancel}
                  </button>
                </div>
              </>
            ) : (
              section.segments.map((segment) => {
                const citations = output.citations.filter(
                  (c) => c.item_index === segment.index && c.verification === "verificado",
                );
                return (
                  <div
                    key={segment.index}
                    className={`draft-segment${segment.unverified ? " unverified" : ""}`}
                  >
                    <p>
                      <WithMarkers text={segment.text.trim()} />{" "}
                      {segment.unverified && (
                        <span className="badge danger" title={t.ia.unverifiedHelp}>
                          {t.ia.unverified}
                        </span>
                      )}
                      {segment.edited && <span className="badge">{t.minutas.edited}</span>}
                    </p>
                    {citations.length > 0 && (
                      <details className="small">
                        <summary>
                          {t.minutas.citation} ({citations.length})
                        </summary>
                        <ul>
                          {citations.map((c, i) => (
                            <li key={i}>
                              “{c.quoted_text}”
                              {c.page_number != null && (
                                <span className="muted">
                                  {" "}
                                  — {t.processo.page} {c.page_number}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                );
              })
            )}
          </section>
        ))}
      </div>
    </>
  );
}
