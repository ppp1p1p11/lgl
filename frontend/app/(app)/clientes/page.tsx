"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Client = components["schemas"]["ClientOut"];

export default function ClientesPage() {
  const canManage = useCan("manage_clients");
  const [clients, setClients] = useState<Client[] | null>(null);
  const [query, setQuery] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (q: string) => {
    const { data } = await api.GET("/api/clients", { params: { query: { q: q || undefined } } });
    return data ?? [];
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => load(query).then(setClients), 250);
    return () => clearTimeout(timer);
  }, [query, load]);

  async function onCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const optional = (name: string) => String(form.get(name) ?? "").trim() || null;
    const { error: apiError } = await api.POST("/api/clients", {
      body: {
        kind: form.get("kind") as "PF" | "PJ",
        name: String(form.get("name")),
        document_number: optional("document_number"),
        email: optional("email"),
        phone: optional("phone"),
      },
    });
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    setShowForm(false);
    setClients(await load(query));
  }

  return (
    <>
      <div className="page-header">
        <h1>{t.clientes.title}</h1>
        {canManage && !showForm && (
          <button type="button" onClick={() => setShowForm(true)}>
            {t.clientes.new}
          </button>
        )}
      </div>

      {showForm && (
        <form className="card" onSubmit={onCreate}>
          <h2>{t.clientes.new}</h2>
          <div className="grid">
            <label>
              {t.clientes.kind}
              <select name="kind" defaultValue="PF">
                <option value="PF">{t.clientes.kinds.PF}</option>
                <option value="PJ">{t.clientes.kinds.PJ}</option>
              </select>
            </label>
            <label>
              {t.clientes.name}
              <input name="name" required minLength={2} maxLength={300} />
            </label>
            <label>
              {t.clientes.documentNumber} <span className="muted">({t.common.optional})</span>
              <input name="document_number" maxLength={30} />
            </label>
            <label>
              {t.clientes.email} <span className="muted">({t.common.optional})</span>
              <input name="email" type="email" />
            </label>
            <label>
              {t.clientes.phone} <span className="muted">({t.common.optional})</span>
              <input name="phone" maxLength={40} />
            </label>
          </div>
          <ErrorText message={error} />
          <div className="actions">
            <button type="submit">{t.common.save}</button>
            <button type="button" className="secondary" onClick={() => setShowForm(false)}>
              {t.common.cancel}
            </button>
          </div>
        </form>
      )}

      <input
        type="search"
        className="search"
        placeholder={t.clientes.searchPlaceholder}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {clients === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : clients.length === 0 ? (
        <p className="muted">{t.clientes.empty}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.clientes.name}</th>
                <th>{t.clientes.kind}</th>
                <th>{t.clientes.documentNumber}</th>
                <th>{t.clientes.email}</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>{t.clientes.kinds[c.kind]}</td>
                  <td>{c.document_number ?? t.common.none}</td>
                  <td>{c.email ?? t.common.none}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
