"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { formatDate, formatDateTime, label, todayIso } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Summary = components["schemas"]["ResearchSummary"];
export type LegalSource = {
  unit_version_id: string;
  doc_type: keyof typeof t.pesquisa.docTypes;
  identifier: string;
  short_name: string;
  label: string;
  heading_path: string | null;
  text: string;
  status: keyof typeof t.pesquisa.unitStatus;
  valid_from: string | null;
  amendment_note: string | null;
  review_status: keyof typeof t.acervo.reviewStatus;
  source_url: string | null;
};

/** One provision of the legal corpus, with its type, validity and review status. */
export function SourceCard({
  source,
  number,
  highlighted = false,
}: {
  source: LegalSource;
  number?: number;
  highlighted?: boolean;
}) {
  return (
    <article
      className={`source${highlighted ? " highlighted" : ""}`}
      id={number ? `fonte-${number}` : undefined}
    >
      <header>
        {number && <span className="source-number">{number}</span>}
        <strong>
          {source.short_name}, {source.label}
        </strong>{" "}
        <span className="badge">{label(t.pesquisa.docTypes, source.doc_type)}</span>{" "}
        <span className={`badge unit-${source.status}`}>
          {label(t.pesquisa.unitStatus, source.status)}
        </span>
        {source.valid_from && (
          <span className="muted small">
            {" "}
            {t.pesquisa.validFrom.replace("{date}", formatDate(source.valid_from))}
          </span>
        )}
      </header>
      {source.heading_path && <p className="muted small">{source.heading_path}</p>}
      <p className="source-text">{source.text}</p>
      {source.amendment_note && <p className="muted small">{source.amendment_note}</p>}
      {source.review_status !== "oficial" && (
        <p className="warning small">{t.pesquisa.unreviewed}</p>
      )}
      {source.source_url && (
        <p className="small">
          <a href={source.source_url} target="_blank" rel="noreferrer noopener">
            {t.pesquisa.officialLink}
          </a>
        </p>
      )}
    </article>
  );
}

/** Ask a legal research question and list earlier ones (of a processo, or of the firm). */
export function ResearchPanel({ matterId, title }: { matterId?: string; title: string }) {
  const canAsk = useCan("draft_ai_outputs");
  const canView = useCan("view_ai_outputs");
  const [runs, setRuns] = useState<Summary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const fetchRuns = useCallback(async () => {
    const { data } = await api.GET("/api/research", {
      params: { query: { matter_id: matterId } },
    });
    return data ?? [];
  }, [matterId]);

  useEffect(() => {
    if (canView) fetchRuns().then(setRuns);
  }, [canView, fetchRuns]);

  const pending = runs?.some((r) => r.status === "queued" || r.status === "running") ?? false;
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => fetchRuns().then(setRuns), 2000);
    return () => clearInterval(timer);
  }, [pending, fetchRuns]);

  async function onAsk(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setSending(true);
    const { error: apiError } = await api.POST("/api/research", {
      body: {
        question: String(form.get("question")),
        on_date: String(form.get("on_date") ?? "") || null,
        matter_id: matterId ?? null,
      },
    });
    setSending(false);
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    formElement.reset();
    setRuns(await fetchRuns());
  }

  if (!canView) return null;
  return (
    <section className="card">
      <h2>{title}</h2>
      <p className="muted small">{t.pesquisa.intro}</p>
      {canAsk && (
        <form onSubmit={onAsk} className="subform">
          <label>
            {t.pesquisa.question}
            <textarea
              name="question"
              required
              minLength={5}
              maxLength={2000}
              rows={2}
              placeholder={t.pesquisa.questionPlaceholder}
            />
          </label>
          <div className="inline">
            <label>
              {t.pesquisa.onDate}
              <input name="on_date" type="date" defaultValue={todayIso()} />
            </label>
            <button type="submit" disabled={sending}>
              {t.pesquisa.ask}
            </button>
          </div>
          <ErrorText message={error} />
        </form>
      )}
      {runs === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : runs.length === 0 ? (
        <p className="muted">{t.pesquisa.empty}</p>
      ) : (
        <ul className="plain-list">
          {runs.map((r) => (
            <li key={r.run_id}>
              <Link href={`/pesquisa/${r.run_id}`}>{r.question}</Link>{" "}
              {r.output_status ? (
                <span className={`badge ai-${r.output_status}`}>
                  {t.ia.status[r.output_status]}
                </span>
              ) : (
                <span className={`badge${r.status === "failed" ? " danger" : ""}`}>
                  {t.pesquisa.runStatus[r.status]}
                </span>
              )}
              <span className="muted small"> {formatDateTime(r.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
