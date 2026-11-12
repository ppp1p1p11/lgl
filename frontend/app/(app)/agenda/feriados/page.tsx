"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { fill, formatDate, todayIso } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Holiday = components["schemas"]["HolidayOut"];
type HolidayIn = components["schemas"]["HolidayIn"];
type Kind = NonNullable<HolidayIn["kind"]>;

const KINDS = Object.keys(t.feriados.kinds) as Kind[];

export default function FeriadosPage() {
  const canEdit = useCan("confirm_deadlines");
  const thisYear = Number(todayIso().slice(0, 4));
  const [year, setYear] = useState(thisYear);
  const [holidays, setHolidays] = useState<Holiday[] | null>(null);
  const [suggestions, setSuggestions] = useState<Holiday[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const query = { params: { query: { year } } };
    const [h, s] = await Promise.all([
      api.GET("/api/holidays", query),
      api.GET("/api/holidays/suggestions", query),
    ]);
    return { holidays: h.data ?? [], suggestions: s.data ?? [] };
  }, [year]);

  const apply = useCallback((r: { holidays: Holiday[]; suggestions: Holiday[] }) => {
    setHolidays(r.holidays);
    setSuggestions(r.suggestions);
  }, []);

  useEffect(() => {
    load().then(apply);
  }, [load, apply]);

  async function add(body: HolidayIn) {
    const { error: apiError } = await api.POST("/api/holidays", { body });
    setError(apiError ? errorMessage(apiError) : null);
    load().then(apply);
    return !apiError;
  }

  async function onAdd(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const ok = await add({
      day: String(form.get("day")),
      name: String(form.get("name")),
      kind: form.get("kind") as Kind,
      scope: String(form.get("scope") ?? "").trim() || null,
      source: String(form.get("source") ?? "").trim() || null,
    });
    if (ok) formElement.reset();
  }

  async function remove(holiday: Holiday) {
    if (!holiday.id) return;
    await api.DELETE("/api/holidays/{holiday_id}", {
      params: { path: { holiday_id: holiday.id } },
    });
    load().then(apply);
  }

  const registered = new Set((holidays ?? []).map((h) => h.day));
  const openSuggestions = suggestions.filter((s) => !registered.has(s.day));

  return (
    <>
      <p>
        <Link href="/agenda">← {t.agenda.title}</Link>
      </p>
      <div className="page-header">
        <h1>{t.feriados.title}</h1>
        <label>
          {t.feriados.year}{" "}
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[thisYear - 1, thisYear, thisYear + 1, thisYear + 2].map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted">{t.feriados.intro}</p>
      <ErrorText message={error} />

      {openSuggestions.length > 0 && (
        <section className="card">
          <h2>{fill(t.feriados.suggestions, { year })}</h2>
          <p className="muted small">{t.feriados.suggestionsHint}</p>
          <ul className="plain-list">
            {openSuggestions.map((s) => (
              <li key={s.day}>
                <strong>{formatDate(s.day)}</strong> — {s.name}{" "}
                <span className="badge">{t.feriados.kinds[s.kind]}</span>{" "}
                {canEdit && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      add({
                        day: s.day,
                        name: s.name,
                        kind: s.kind,
                        scope: s.scope,
                        source: s.source,
                      })
                    }
                  >
                    {t.feriados.addSuggestion}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        {holidays === null ? (
          <p className="muted">{t.common.loading}</p>
        ) : holidays.length === 0 ? (
          <p className="muted">{t.feriados.empty}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t.common.date}</th>
                  <th>{t.feriados.name}</th>
                  <th>{t.feriados.kind}</th>
                  <th>{t.feriados.scope}</th>
                  <th>{t.feriados.source}</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {holidays.map((h) => (
                  <tr key={`${h.day}-${h.id ?? "system"}`}>
                    <td>{formatDate(h.day)}</td>
                    <td>{h.name}</td>
                    <td>{t.feriados.kinds[h.kind]}</td>
                    <td>{h.system ? t.feriados.system : (h.scope ?? t.feriados.firm)}</td>
                    <td className="small">{h.source ?? t.common.none}</td>
                    {canEdit && (
                      <td>
                        {!h.system && (
                          <button type="button" className="link" onClick={() => remove(h)}>
                            {t.common.remove}
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {canEdit && (
        <form className="card" onSubmit={onAdd}>
          <h2>{t.feriados.add}</h2>
          <div className="grid">
            <label>
              {t.common.date}
              <input name="day" type="date" required />
            </label>
            <label>
              {t.feriados.name}
              <input name="name" required minLength={2} maxLength={200} />
            </label>
            <label>
              {t.feriados.kind}
              <select name="kind" defaultValue="feriado">
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t.feriados.kinds[k]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.feriados.scope} <span className="muted">({t.common.optional})</span>
              <input name="scope" maxLength={120} placeholder={t.feriados.scopeHint} />
            </label>
            <label>
              {t.feriados.source} <span className="muted">({t.common.optional})</span>
              <input name="source" maxLength={300} placeholder={t.feriados.sourceHint} />
            </label>
          </div>
          <div className="actions">
            <button type="submit">{t.common.add}</button>
          </div>
        </form>
      )}
    </>
  );
}
