"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Draft = components["schemas"]["DraftSummary"];
type Template = components["schemas"]["TemplateOut"];

/** Drafts (minutas) of one processo: generate from a template and list earlier ones. */
export function Drafts({ matterId }: { matterId: string }) {
  const canDraft = useCan("draft_ai_outputs");
  const canView = useCan("view_ai_outputs");
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDrafts = useCallback(async () => {
    const { data } = await api.GET("/api/matters/{matter_id}/drafts", {
      params: { path: { matter_id: matterId } },
    });
    return data ?? [];
  }, [matterId]);

  useEffect(() => {
    if (!canView) return;
    fetchDrafts().then(setDrafts);
    api.GET("/api/draft-templates").then(({ data }) => {
      setTemplates(data ?? []);
      setTemplateId(data?.[0]?.id ?? "");
    });
  }, [canView, fetchDrafts]);

  const pending =
    drafts?.some((d) => d.run_status === "queued" || d.run_status === "running") ?? false;
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => fetchDrafts().then(setDrafts), 2000);
    return () => clearInterval(timer);
  }, [pending, fetchDrafts]);

  async function onCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const { error: apiError } = await api.POST("/api/matters/{matter_id}/drafts", {
      params: { path: { matter_id: matterId } },
      body: {
        template_id: templateId,
        instructions: String(form.get("instructions") ?? "").trim() || null,
        legal_topics: String(form.get("legal_topics") ?? "").trim() || null,
      },
    });
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    setShowForm(false);
    setDrafts(await fetchDrafts());
  }

  if (!canView) return null;
  const template = templates.find((x) => x.id === templateId);

  return (
    <section className="card">
      <div className="page-header">
        <h2>{t.minutas.title}</h2>
        {canDraft && !showForm && templates.length > 0 && (
          <button type="button" className="secondary" onClick={() => setShowForm(true)}>
            {t.minutas.new}
          </button>
        )}
      </div>
      <p className="muted small">{t.minutas.intro}</p>
      {showForm && (
        <form onSubmit={onCreate} className="subform">
          <label>
            {t.minutas.template}
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              {templates.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
            {template && (
              <span className="muted small">
                {template.description}
                {template.uses_documents && ` · ${t.minutas.usesDocuments}`}
                {template.uses_legal_corpus && ` · ${t.minutas.usesCorpus}`}
              </span>
            )}
          </label>
          <label>
            {t.minutas.instructions} <span className="muted">({t.common.optional})</span>
            <textarea
              name="instructions"
              rows={2}
              maxLength={4000}
              placeholder={t.minutas.instructionsHint}
            />
          </label>
          {template?.uses_legal_corpus && (
            <label>
              {t.minutas.legalTopics} <span className="muted">({t.common.optional})</span>
              <input name="legal_topics" maxLength={500} placeholder={t.minutas.legalTopicsHint} />
            </label>
          )}
          <p className="warning small">{t.minutas.templatesWarning}</p>
          <ErrorText message={error} />
          <div className="actions">
            <button type="submit">{t.minutas.create}</button>
            <button type="button" className="secondary" onClick={() => setShowForm(false)}>
              {t.common.cancel}
            </button>
          </div>
        </form>
      )}
      {drafts === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : drafts.length === 0 ? (
        <p className="muted">{t.minutas.empty}</p>
      ) : (
        <ul className="plain-list">
          {drafts.map((d) => (
            <li key={d.run_id}>
              <Link href={`/processos/${matterId}/minutas/${d.run_id}`}>
                {d.title ?? d.template_name}
              </Link>{" "}
              {d.status ? (
                <span className={`badge ai-${d.status}`}>{t.ia.status[d.status]}</span>
              ) : (
                <span className={`badge${d.run_status === "failed" ? " danger" : ""}`}>
                  {t.pesquisa.runStatus[d.run_status]}
                </span>
              )}
              <span className="muted small">
                {" "}
                {d.version_no != null && `${t.ia.version.replace("{n}", String(d.version_no))} · `}
                {formatDateTime(d.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
