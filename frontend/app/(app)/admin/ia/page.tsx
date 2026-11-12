"use client";

import { useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { fill, label } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Usage = components["schemas"]["AiUsageOut"];
type Report = components["schemas"]["AiReportOut"];

const usd = (value: string) => Number(value).toFixed(2).replace(".", ",");

export default function AdminIaPage() {
  const allowed = useCan("manage_firm");
  const [usage, setUsage] = useState<Usage | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!allowed) return;
    api.GET("/api/firm/ai-usage").then(({ data }) => setUsage(data ?? null));
    api.GET("/api/firm/ai-report").then(({ data }) => setReport(data ?? null));
  }, [allowed]);

  async function onSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const { data, error: apiError } = await api.PATCH("/api/firm/ai-settings", {
      body: {
        monthly_budget_usd: String(form.get("budget")).replace(",", "."),
        redaction_enabled: form.get("redaction") === "on",
      },
    });
    setError(data ? null : errorMessage(apiError));
    setSaved(Boolean(data));
    if (data) setUsage(data);
  }

  if (!allowed) return <p>{t.errors.forbidden}</p>;
  if (!usage) return <p className="muted">{t.common.loading}</p>;
  return (
    <>
      <section className="card">
        <h2>{t.admin.ia}</h2>
        <p className="muted small">{t.admin.ai.intro}</p>
        <dl className="facts">
          <div>
            <dt>{t.admin.ai.spend}</dt>
            <dd>US$ {usd(usage.month_spend_usd)}</dd>
          </div>
          <div>
            <dt>{t.admin.ai.calls}</dt>
            <dd>{usage.calls_this_month}</dd>
          </div>
        </dl>
        <form onSubmit={onSave} className="subform">
          <label>
            {t.admin.ai.budget}
            <input
              name="budget"
              required
              inputMode="decimal"
              pattern="[0-9]+([.,][0-9]{1,2})?"
              defaultValue={usd(usage.monthly_budget_usd)}
            />
          </label>
          <label className="checkbox">
            <input type="checkbox" name="redaction" defaultChecked={usage.redaction_enabled} />{" "}
            {t.admin.ai.redaction}
          </label>
          <p className="muted small">{t.admin.ai.redactionHint}</p>
          <ErrorText message={error} />
          {saved && <p className="small">{t.admin.ai.saved}</p>}
          <div className="actions">
            <button type="submit">{t.common.save}</button>
          </div>
        </form>
      </section>
      {report && (
        <section className="card">
          <h2>{fill(t.admin.ai.report, { month: report.month })}</h2>
          {report.rows.length === 0 ? (
            <p className="muted">{t.admin.ai.empty}</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t.admin.ai.purpose}</th>
                    <th>{t.admin.ai.calls}</th>
                    <th>{t.admin.ai.inputTokens}</th>
                    <th>{t.admin.ai.outputTokens}</th>
                    <th>{t.admin.ai.cost}</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((r) => (
                    <tr key={r.purpose}>
                      <td>{label(t.admin.ai.purposes, r.purpose)}</td>
                      <td>{r.calls}</td>
                      <td>{r.input_tokens.toLocaleString("pt-BR")}</td>
                      <td>{r.output_tokens.toLocaleString("pt-BR")}</td>
                      <td>{usd(r.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
