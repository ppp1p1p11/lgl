"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { formatDateTime, label } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type AuditEvent = components["schemas"]["AuditEventOut"];

export default function AuditoriaPage() {
  const allowed = useCan("view_audit_log");
  const [events, setEvents] = useState<AuditEvent[] | null>(null);

  useEffect(() => {
    if (!allowed) return;
    api
      .GET("/api/audit-log", { params: { query: { limit: 200 } } })
      .then(({ data }) => setEvents(data ?? []));
  }, [allowed]);

  if (!allowed) return <p>{t.errors.forbidden}</p>;
  return (
    <section className="card">
      <h2>{t.admin.auditoria}</h2>
      <p className="muted small">{t.admin.audit.intro}</p>
      {events === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : events.length === 0 ? (
        <p className="muted">{t.admin.audit.empty}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.admin.audit.when}</th>
                <th>{t.admin.audit.who}</th>
                <th>{t.admin.audit.action}</th>
                <th>{t.admin.audit.entity}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td className="small">{formatDateTime(e.occurred_at)}</td>
                  <td>{e.actor_name ?? t.admin.audit.system}</td>
                  <td>
                    {label(t.admin.audit.actions, e.action)}
                    {e.action in t.admin.audit.actions && (
                      <div className="muted small mono">{e.action}</div>
                    )}
                  </td>
                  <td className="small mono">{e.entity_type ?? t.common.none}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
