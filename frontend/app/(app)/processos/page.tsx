"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Matter = components["schemas"]["MatterSummary"];

export default function ProcessosPage() {
  const canManage = useCan("manage_clients");
  const [matters, setMatters] = useState<Matter[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const timer = setTimeout(async () => {
      const { data } = await api.GET("/api/matters", {
        params: { query: { q: query || undefined } },
      });
      setMatters(data ?? []);
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <>
      <div className="page-header">
        <h1>{t.processos.title}</h1>
        {canManage && (
          <Link className="button" href="/processos/novo">
            {t.processos.new}
          </Link>
        )}
      </div>
      <input
        type="search"
        className="search"
        placeholder={t.processos.searchPlaceholder}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {matters === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : matters.length === 0 ? (
        <div className="card">
          <h2>{t.processos.empty}</h2>
          {!query && <p className="muted">{t.processos.emptyBody}</p>}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.processos.fields.title}</th>
                <th>{t.processos.fields.cnj}</th>
                <th>{t.processos.fields.client}</th>
                <th>{t.processos.fields.area}</th>
                <th>{t.processos.fields.status}</th>
              </tr>
            </thead>
            <tbody>
              {matters.map((m) => (
                <tr key={m.id}>
                  <td>
                    <Link href={`/processos/${m.id}`}>{m.title}</Link>
                  </td>
                  <td className="mono">{m.cnj_number ?? t.common.none}</td>
                  <td>{m.client_name}</td>
                  <td>{t.processos.areas[m.area]}</td>
                  <td>
                    <span className={`badge status-${m.status}`}>
                      {t.processos.statuses[m.status]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
