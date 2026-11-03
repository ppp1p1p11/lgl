"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { t } from "@/lib/i18n";

type Client = components["schemas"]["ClientOut"];
type Area = components["schemas"]["MatterIn"]["area"];

const AREAS = Object.keys(t.processos.areas) as Area[];

export default function NovoProcessoPage() {
  const router = useRouter();
  const [clients, setClients] = useState<Client[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.GET("/api/clients").then(({ data }) => setClients(data ?? []));
  }, []);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const optional = (name: string) => String(form.get(name) ?? "").trim() || null;
    const { data, error: apiError } = await api.POST("/api/matters", {
      body: {
        client_id: String(form.get("client_id")),
        title: String(form.get("title")),
        cnj_number: optional("cnj_number"),
        area: form.get("area") as Area,
        court: optional("court"),
        comarca: optional("comarca"),
        vara: optional("vara"),
        description: optional("description"),
        opened_at: optional("opened_at"),
      },
    });
    if (!data) {
      setError(errorMessage(apiError));
      return;
    }
    router.push(`/processos/${data.id}`);
  }

  if (clients === null) return <p className="muted">{t.common.loading}</p>;

  return (
    <>
      <p>
        <Link href="/processos">← {t.common.back}</Link>
      </p>
      <h1>{t.processos.new}</h1>
      {clients.length === 0 ? (
        <div className="card">
          <p>{t.processos.noClients}</p>
          <Link href="/clientes">{t.clientes.new}</Link>
        </div>
      ) : (
        <form className="card" onSubmit={onSubmit}>
          <div className="grid">
            <label>
              {t.processos.fields.client}
              <select name="client_id" required defaultValue="">
                <option value="" disabled>
                  {t.processos.selectClient}
                </option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.processos.fields.title}
              <input name="title" required minLength={3} maxLength={300} />
            </label>
            <label>
              {t.processos.fields.cnj} <span className="muted">({t.common.optional})</span>
              <input name="cnj_number" placeholder="0000000-00.0000.0.00.0000" maxLength={30} />
              <span className="muted small">{t.processos.fields.cnjHint}</span>
            </label>
            <label>
              {t.processos.fields.area}
              <select name="area" required defaultValue="civel">
                {AREAS.map((a) => (
                  <option key={a} value={a}>
                    {t.processos.areas[a]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.processos.fields.court} <span className="muted">({t.common.optional})</span>
              <input name="court" placeholder="TJSP" maxLength={50} />
            </label>
            <label>
              {t.processos.fields.comarca} <span className="muted">({t.common.optional})</span>
              <input name="comarca" maxLength={120} />
            </label>
            <label>
              {t.processos.fields.vara} <span className="muted">({t.common.optional})</span>
              <input name="vara" maxLength={200} />
            </label>
            <label>
              {t.processos.fields.openedAt} <span className="muted">({t.common.optional})</span>
              <input name="opened_at" type="date" />
            </label>
          </div>
          <label>
            {t.processos.fields.description} <span className="muted">({t.common.optional})</span>
            <textarea name="description" rows={3} maxLength={5000} />
          </label>
          <ErrorText message={error} />
          <div className="actions">
            <button type="submit">{t.common.save}</button>
          </div>
        </form>
      )}
    </>
  );
}
