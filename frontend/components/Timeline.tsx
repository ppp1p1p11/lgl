"use client";

import { useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { formatDateTime, todayIso } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Event = components["schemas"]["EventOut"];
type EventKind = components["schemas"]["EventIn"]["kind"];

const KINDS = Object.keys(t.processo.eventKinds) as EventKind[];

/** Timeline of a processo, with manual registration of movements and intimações. */
export function Timeline({
  matterId,
  events,
  onChange,
}: {
  matterId: string;
  events: Event[];
  onChange: () => void;
}) {
  const canAdd = useCan("manage_clients");
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onAdd(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const { error: apiError } = await api.POST("/api/matters/{matter_id}/events", {
      params: { path: { matter_id: matterId } },
      body: {
        kind: form.get("kind") as EventKind,
        summary: String(form.get("summary")),
        occurred_on: String(form.get("occurred_on")),
      },
    });
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    setShowForm(false);
    onChange();
  }

  return (
    <section className="card">
      <div className="page-header">
        <h2>{t.processo.timeline}</h2>
        {canAdd && !showForm && (
          <button type="button" className="secondary" onClick={() => setShowForm(true)}>
            {t.processo.addEvent}
          </button>
        )}
      </div>
      {showForm && (
        <form onSubmit={onAdd} className="subform">
          <p className="muted small">{t.processo.eventHint}</p>
          <div className="grid">
            <label>
              {t.processo.eventKind}
              <select name="kind" defaultValue="movimentacao">
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t.processo.eventKinds[k]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.processo.eventDate}
              <input name="occurred_on" type="date" required defaultValue={todayIso()} />
            </label>
          </div>
          <label>
            {t.processo.eventSummary}
            <input name="summary" required minLength={3} maxLength={500} />
          </label>
          <ErrorText message={error} />
          <div className="actions">
            <button type="submit">{t.common.add}</button>
            <button type="button" className="secondary" onClick={() => setShowForm(false)}>
              {t.common.cancel}
            </button>
          </div>
        </form>
      )}
      <ol className="timeline">
        {events.map((e) => (
          <li key={e.id}>
            <span className="muted small">{formatDateTime(e.occurred_at)}</span> {e.summary}
          </li>
        ))}
      </ol>
    </section>
  );
}
