"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { OutputCard } from "@/components/AiAnalysis";
import { ErrorText } from "@/components/ErrorText";
import { type LegalSource, SourceCard } from "@/components/Research";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { fill, formatDate, label } from "@/lib/format";
import { t } from "@/lib/i18n";

type Detail = components["schemas"]["ResearchDetail"];
type Segment = { text: string; kind: "text" | "gap"; unverified: boolean };

export default function PesquisaDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [highlighted, setHighlighted] = useState<number | null>(null);

  const fetchDetail = useCallback(async () => {
    const { data } = await api.GET("/api/research/{run_id}", {
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

  const pending = detail?.status === "queued" || detail?.status === "running";
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => fetchDetail().then(apply), 2000);
    return () => clearInterval(timer);
  }, [pending, fetchDetail, apply]);

  if (notFound) return <p>{t.errors.research_not_found}</p>;
  if (!detail) return <p className="muted">{t.common.loading}</p>;

  const output = detail.output;
  const sources = (output?.content.sources ?? []) as LegalSource[];
  const segments = (output?.content.segments ?? []) as Segment[];
  const sourceNumber = (unitVersionId: string | null | undefined) =>
    sources.findIndex((s) => s.unit_version_id === unitVersionId) + 1;

  function showSource(n: number) {
    setHighlighted(n);
    document.getElementById(`fonte-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  return (
    <>
      <p>
        <Link href="/pesquisa">← {t.pesquisa.back}</Link>
        {detail.matter_id && (
          <>
            {" · "}
            <Link href={`/processos/${detail.matter_id}`}>{t.pesquisa.matter}</Link>
          </>
        )}
      </p>
      <h1>{detail.question}</h1>
      <p className="muted small">
        {fill(t.pesquisa.usedDate, { date: formatDate(detail.on_date) })}
      </p>
      {detail.provider === "demo" && <p className="warning small">{t.common.demo}</p>}
      {pending && <p className="muted">{t.pesquisa.running}</p>}
      {detail.status === "failed" && (
        <ErrorText
          message={`${t.pesquisa.failed} ${label(t.ia.errors, detail.error_code)}`.trim()}
        />
      )}

      {output && (
        <div className="side-by-side">
          <section className="card ai-panel pane">
            <OutputCard
              output={output}
              title={t.pesquisa.answer}
              onChange={() => fetchDetail().then(apply)}
            >
              {(selected, toggle) => (
                <div className="summary">
                  {segments.map((s, i) => {
                    const text = s.text.trim();
                    if (!text) return null;
                    const citations = output.citations.filter((c) => c.item_index === i);
                    const isHeading =
                      text.length < 40 && !s.unverified && !/[.:]$/.test(text) && !citations.length;
                    if (isHeading) {
                      return (
                        <h4 key={i} className="summary-heading">
                          {text}
                        </h4>
                      );
                    }
                    return (
                      <p
                        key={i}
                        className={`segment${s.unverified ? " unverified" : ""}${
                          selected.has(i) ? " selected" : ""
                        }`}
                        onClick={() => toggle(i)}
                      >
                        {text}{" "}
                        {citations.map((c, j) => {
                          const n = sourceNumber(c.legal_unit_version_id);
                          if (!n) return null;
                          return (
                            <button
                              key={j}
                              type="button"
                              className="cite"
                              title={`${fill(t.pesquisa.citeSource, { n })}: “${c.quoted_text}”`}
                              onClick={(e) => {
                                e.stopPropagation();
                                showSource(n);
                              }}
                            >
                              {n}
                            </button>
                          );
                        })}
                        {s.unverified && (
                          <span className="badge danger" title={t.ia.unverifiedHelp}>
                            {t.ia.unverified}
                          </span>
                        )}
                      </p>
                    );
                  })}
                </div>
              )}
            </OutputCard>
          </section>
          <section className="card pane">
            <h2>{t.pesquisa.sources}</h2>
            {sources.length === 0 ? (
              <p className="muted">{t.acervo.noResults}</p>
            ) : (
              sources.map((s, i) => (
                <SourceCard
                  key={s.unit_version_id}
                  source={s}
                  number={i + 1}
                  highlighted={highlighted === i + 1}
                />
              ))
            )}
          </section>
        </div>
      )}
    </>
  );
}
