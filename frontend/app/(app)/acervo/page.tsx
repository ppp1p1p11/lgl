"use client";

import { useEffect, useState } from "react";

import { type LegalSource, SourceCard } from "@/components/Research";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { todayIso } from "@/lib/format";
import { t } from "@/lib/i18n";

type CorpusDocument = components["schemas"]["CorpusDocumentOut"];
type Hit = components["schemas"]["CorpusHitOut"];

export default function AcervoPage() {
  const [documents, setDocuments] = useState<CorpusDocument[] | null>(null);
  const [hits, setHits] = useState<Hit[] | null>(null);

  useEffect(() => {
    api.GET("/api/corpus/documents").then(({ data }) => setDocuments(data ?? []));
  }, []);

  async function onSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const q = String(form.get("q")).trim();
    if (q.length < 2) return;
    const { data } = await api.GET("/api/corpus/search", {
      params: { query: { q, on_date: String(form.get("on_date") ?? "") || undefined } },
    });
    setHits(data ?? []);
  }

  return (
    <>
      <h1>{t.acervo.title}</h1>
      <p className="muted">{t.acervo.intro}</p>

      <section className="card">
        <h2>{t.acervo.documents}</h2>
        {documents === null ? (
          <p className="muted">{t.common.loading}</p>
        ) : documents.length === 0 ? (
          <p className="muted">{t.acervo.empty}</p>
        ) : (
          <ul className="plain-list">
            {documents.map((d) => (
              <li key={d.id}>
                <strong>{d.short_name}</strong> — {d.title}{" "}
                <span className="badge">{t.pesquisa.docTypes[d.doc_type]}</span>{" "}
                <span className={`badge${d.review_status === "oficial" ? " doc-ready" : " warn"}`}>
                  {t.acervo.reviewStatus[d.review_status]}
                </span>
                <span className="muted small">
                  {" "}
                  {d.identifier} · {d.units} {t.acervo.units}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>{t.acervo.search}</h2>
        <form className="inline" onSubmit={onSearch}>
          <input name="q" type="search" minLength={2} placeholder={t.acervo.searchPlaceholder} />
          <label>
            {t.pesquisa.onDate}
            <input name="on_date" type="date" defaultValue={todayIso()} />
          </label>
          <button type="submit">{t.common.search}</button>
        </form>
        {hits !== null &&
          (hits.length === 0 ? (
            <p className="muted">{t.acervo.noResults}</p>
          ) : (
            hits.map((h) => <SourceCard key={h.unit_version_id} source={h as LegalSource} />)
          ))}
      </section>
    </>
  );
}
