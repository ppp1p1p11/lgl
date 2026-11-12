"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { fill, formatDateTime, label } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Analysis = components["schemas"]["AnalysisOut"];
type Output = components["schemas"]["OutputOut"];
type CitationRef = components["schemas"]["CitationOut"];

export type Highlight = { page: number; start: number; end: number };

type Segment = { text: string; kind: "text" | "gap"; unverified: boolean };
type Fact = { type: string; value: string; quote: string; page_number: number };

/** AI analysis of one document version: type, facts, cited summary and review. */
export function AiAnalysis({
  versionId,
  onHighlight,
}: {
  versionId: string;
  onHighlight: (h: Highlight) => void;
}) {
  const canDraft = useCan("draft_ai_outputs");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAnalysis = useCallback(async () => {
    const { data } = await api.GET("/api/document-versions/{version_id}/analysis", {
      params: { path: { version_id: versionId } },
    });
    return data ?? null;
  }, [versionId]);

  useEffect(() => {
    fetchAnalysis().then(setAnalysis);
  }, [fetchAnalysis]);

  const pending = analysis?.run?.status === "queued" || analysis?.run?.status === "running";
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => fetchAnalysis().then(setAnalysis), 2500);
    return () => clearInterval(timer);
  }, [pending, fetchAnalysis]);

  async function start() {
    setError(null);
    const { error: apiError } = await api.POST("/api/document-versions/{version_id}/analysis", {
      params: { path: { version_id: versionId } },
    });
    if (apiError) setError(errorMessage(apiError));
    setAnalysis(await fetchAnalysis());
  }

  if (!analysis) return null;
  const run = analysis.run;
  const outputs = Object.fromEntries(analysis.outputs.map((o) => [o.kind, o])) as Partial<
    Record<Output["kind"], Output>
  >;
  const runError = run?.status === "failed" ? label(t.ia.errors, run.error_code) : null;

  return (
    <section className="card ai-panel">
      <div className="page-header">
        <h2>{t.ia.title}</h2>
        {canDraft && analysis.provider !== "none" && !pending && (
          <button type="button" className={run ? "secondary" : ""} onClick={start}>
            {run ? t.ia.reanalyze : t.ia.analyze}
          </button>
        )}
      </div>
      {analysis.provider === "demo" && <p className="warning small">{t.ia.demo}</p>}
      {analysis.provider === "none" && <p className="muted">{t.ia.notConfigured}</p>}
      {!run && analysis.provider !== "none" && <p className="muted">{t.ia.intro}</p>}
      <ErrorText message={error} />
      {pending && <p className="muted">{run?.status === "queued" ? t.ia.queued : t.ia.running}</p>}
      <ErrorText message={runError} />

      {analysis.doc_class && (
        <p>
          <strong>{t.ia.docClass}:</strong> {label(t.ia.docClasses, analysis.doc_class)}{" "}
          {analysis.doc_class_source === "ai" && (
            <span className="muted small">({t.ia.suggestedByAi})</span>
          )}
        </p>
      )}

      {outputs.summary && (
        <OutputCard
          output={outputs.summary}
          title={t.ia.summary}
          onChange={() => fetchAnalysis().then(setAnalysis)}
        >
          {(selected, toggle) => (
            <SummaryBody
              output={outputs.summary!}
              selected={selected}
              toggle={toggle}
              onHighlight={onHighlight}
            />
          )}
        </OutputCard>
      )}
      {outputs.facts && (
        <OutputCard
          output={outputs.facts}
          title={t.ia.facts}
          onChange={() => fetchAnalysis().then(setAnalysis)}
        >
          {(selected, toggle) => (
            <FactsBody
              output={outputs.facts!}
              selected={selected}
              toggle={toggle}
              onHighlight={onHighlight}
            />
          )}
        </OutputCard>
      )}
    </section>
  );
}

/** One AI output with its review controls: remove items, submit, approve or reject. */
export function OutputCard({
  output,
  title,
  onChange,
  removable = true,
  children,
}: {
  output: Output;
  title: string;
  onChange: () => void;
  /** Whether single items can be removed (drafts are edited per section instead). */
  removable?: boolean;
  children: (selected: Set<number>, toggle: (i: number) => void) => React.ReactNode;
}) {
  const canDraft = useCan("draft_ai_outputs");
  const canApprove = useCan("approve_ai_outputs");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const editable = removable && canDraft && output.status !== "aprovado";
  const decidable = canApprove && (output.status === "rascunho" || output.status === "em_revisao");
  const path = { params: { path: { output_id: output.id } } };

  function toggle(i: number) {
    const next = new Set(selected);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    setSelected(next);
  }

  async function act(request: Promise<{ error?: unknown }>) {
    const { error: apiError } = await request;
    setError(apiError ? errorMessage(apiError) : null);
    if (!apiError) {
      setSelected(new Set());
      setComment("");
    }
    onChange();
  }

  return (
    <article className="ai-output">
      <header className="page-header">
        <h3>
          {title} <span className={`badge ai-${output.status}`}>{t.ia.status[output.status]}</span>
        </h3>
        <span className="muted small">
          {fill(t.ia.version, { n: output.version_no })} ·{" "}
          {output.created_by_ai ? t.ia.aiDraft : t.ia.editedBy}
        </span>
      </header>
      {output.content.partial === true && <p className="muted small">{t.ia.partial}</p>}
      {editable && <p className="muted small">{t.ia.selectToRemove}</p>}
      {children(selected, editable ? toggle : () => {})}

      <ErrorText message={error} />
      <div className="actions">
        {editable && selected.size > 0 && (
          <button
            type="button"
            className="secondary"
            onClick={() =>
              act(
                api.POST("/api/ai-outputs/{output_id}/versions", {
                  ...path,
                  body: { base_version_no: output.version_no, remove: [...selected] },
                }),
              )
            }
          >
            {t.ia.removeSelected} ({selected.size})
          </button>
        )}
        {canDraft && output.status === "rascunho" && !canApprove && (
          <button
            type="button"
            onClick={() =>
              act(
                api.POST("/api/ai-outputs/{output_id}/submit", {
                  ...path,
                  body: { version_no: output.version_no },
                }),
              )
            }
          >
            {t.ia.submit}
          </button>
        )}
      </div>
      {decidable && (
        <div className="decision">
          <input
            placeholder={t.ia.comment}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={2000}
          />
          <button
            type="button"
            onClick={() =>
              act(
                api.POST("/api/ai-outputs/{output_id}/decision", {
                  ...path,
                  body: {
                    version_no: output.version_no,
                    decision: "aprovado",
                    comment: comment || null,
                  },
                }),
              )
            }
          >
            {t.ia.approve}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() =>
              act(
                api.POST("/api/ai-outputs/{output_id}/decision", {
                  ...path,
                  body: {
                    version_no: output.version_no,
                    decision: "rejeitado",
                    comment: comment || null,
                  },
                }),
              )
            }
          >
            {t.ia.reject}
          </button>
        </div>
      )}
      {output.approvals.map((a) => (
        <p key={`${a.version_no}-${a.decided_at}`} className="small approval">
          {fill(t.ia.decisionBy, {
            decision: a.decision === "aprovado" ? t.ia.approvedWord : t.ia.rejectedWord,
            name: a.approver_name,
            oab: a.approver_oab ? ` (${a.approver_oab})` : "",
            date: formatDateTime(a.decided_at),
            version: a.version_no,
          })}
          {a.comment && <>: “{a.comment}”</>}
        </p>
      ))}
    </article>
  );
}

function citationsFor(output: Output, index: number): CitationRef[] {
  return output.citations.filter((c) => c.item_index === index);
}

function CitationLinks({
  citations,
  onHighlight,
}: {
  citations: CitationRef[];
  onHighlight: (h: Highlight) => void;
}) {
  return (
    <>
      {citations
        .filter((c) => c.verification === "verificado" && c.page_number != null)
        .map((c, i) => (
          <button
            key={i}
            type="button"
            className="cite"
            title={fill(t.ia.citationGoTo, { page: c.page_number! })}
            onClick={(e) => {
              e.stopPropagation();
              onHighlight({ page: c.page_number!, start: c.char_start!, end: c.char_end! });
            }}
          >
            p.{c.page_number}
          </button>
        ))}
    </>
  );
}

function SummaryBody({
  output,
  selected,
  toggle,
  onHighlight,
}: {
  output: Output;
  selected: Set<number>;
  toggle: (i: number) => void;
  onHighlight: (h: Highlight) => void;
}) {
  const segments = (output.content.segments ?? []) as Segment[];
  return (
    <div className="summary">
      {segments.map((s, i) => {
        if (!s.text.trim()) return null;
        const isHeading =
          s.text.trim().length < 40 && !s.unverified && !/[.:]$/.test(s.text.trim());
        if (isHeading && !citationsFor(output, i).length) {
          return (
            <h4 key={i} className="summary-heading">
              {s.text.trim()}
            </h4>
          );
        }
        return (
          <p
            key={i}
            className={`segment${s.unverified ? " unverified" : ""}${selected.has(i) ? " selected" : ""}`}
            onClick={() => toggle(i)}
          >
            {s.text.trim()}{" "}
            <CitationLinks citations={citationsFor(output, i)} onHighlight={onHighlight} />
            {s.unverified && (
              <span className="badge danger" title={t.ia.unverifiedHelp}>
                {t.ia.unverified}
              </span>
            )}
          </p>
        );
      })}
    </div>
  );
}

function FactsBody({
  output,
  selected,
  toggle,
  onHighlight,
}: {
  output: Output;
  selected: Set<number>;
  toggle: (i: number) => void;
  onHighlight: (h: Highlight) => void;
}) {
  const facts = (output.content.facts ?? []) as Fact[];
  const discarded = Number(output.content.discarded ?? 0);
  return (
    <>
      {facts.length === 0 ? (
        <p className="muted">{t.ia.noFacts}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.ia.factType}</th>
                <th>{t.ia.factValue}</th>
                <th>{t.ia.factSource}</th>
              </tr>
            </thead>
            <tbody>
              {facts.map((f, i) => (
                <tr key={i} className={selected.has(i) ? "selected" : ""} onClick={() => toggle(i)}>
                  <td>{label(t.ia.factTypes, f.type)}</td>
                  <td>{f.value}</td>
                  <td className="small">
                    “{f.quote}”{" "}
                    <CitationLinks citations={citationsFor(output, i)} onHighlight={onHighlight} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {discarded > 0 && <p className="muted small">{fill(t.ia.discarded, { n: discarded })}</p>}
    </>
  );
}
