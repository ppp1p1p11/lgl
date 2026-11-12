"use client";

import { useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api, type Role } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { fill } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan, useSession } from "@/lib/session";

type Member = components["schemas"]["legalos__tenancy__router__MemberOut"];

const ROLES = Object.keys(t.roles) as Role[];
const fetchMembers = async () => (await api.GET("/api/firm/members")).data ?? [];

export default function EquipePage() {
  const me = useSession();
  const canManage = useCan("manage_members");
  const [members, setMembers] = useState<Member[] | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<{ name: string; password: string | null } | null>(null);

  useEffect(() => {
    fetchMembers().then(setMembers);
  }, []);

  async function onAdd(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name"));
    const { data, error: apiError } = await api.POST("/api/firm/members", {
      body: {
        name,
        email: String(form.get("email")),
        role: form.get("role") as Role,
        oab_number: String(form.get("oab_number") ?? "").trim() || null,
        oab_uf: String(form.get("oab_uf") ?? "").trim() || null,
      },
    });
    if (!data) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    setShowForm(false);
    setAdded({ name, password: data.temporary_password });
    setMembers(await fetchMembers());
  }

  async function changeRole(member: Member, role: Role) {
    const { error: apiError } = await api.PATCH("/api/firm/members/{user_id}", {
      params: { path: { user_id: member.user_id } },
      body: { role },
    });
    setError(apiError ? errorMessage(apiError) : null);
    setMembers(await fetchMembers());
  }

  async function remove(member: Member) {
    if (!window.confirm(fill(t.admin.team.confirmRemove, { name: member.name }))) return;
    const { error: apiError } = await api.DELETE("/api/firm/members/{user_id}", {
      params: { path: { user_id: member.user_id } },
    });
    setError(apiError ? errorMessage(apiError) : null);
    setMembers(await fetchMembers());
  }

  return (
    <>
      {added && (
        <section className="card notice">
          {added.password ? (
            <>
              <h2>{fill(t.admin.team.temporaryTitle, { name: added.name })}</h2>
              <p>
                <code className="secret">{added.password}</code>
              </p>
              <p className="muted">{t.admin.team.temporaryBody}</p>
            </>
          ) : (
            <p>{t.admin.team.existingAccount}</p>
          )}
          <button type="button" className="secondary" onClick={() => setAdded(null)}>
            {t.common.close}
          </button>
        </section>
      )}
      <section className="card">
        <div className="page-header">
          <h2>{t.admin.equipe}</h2>
          {canManage && !showForm && (
            <button type="button" onClick={() => setShowForm(true)}>
              {t.admin.team.add}
            </button>
          )}
        </div>
        <p className="muted small">{t.admin.team.rolesHelp}</p>
        <ErrorText message={error} />
        {showForm && (
          <form onSubmit={onAdd} className="subform">
            <div className="grid">
              <label>
                {t.admin.team.name}
                <input name="name" required minLength={2} maxLength={200} />
              </label>
              <label>
                {t.admin.team.email}
                <input name="email" type="email" required maxLength={254} />
              </label>
              <label>
                {t.admin.team.role}
                <select name="role" defaultValue="advogado">
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t.roles[r]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t.admin.team.oabNumber} <span className="muted">({t.common.optional})</span>
                <input name="oab_number" maxLength={20} />
              </label>
              <label>
                {t.admin.team.oabUf} <span className="muted">({t.common.optional})</span>
                <input name="oab_uf" minLength={2} maxLength={2} />
              </label>
            </div>
            <div className="actions">
              <button type="submit">{t.common.add}</button>
              <button type="button" className="secondary" onClick={() => setShowForm(false)}>
                {t.common.cancel}
              </button>
            </div>
          </form>
        )}
        {members === null ? (
          <p className="muted">{t.common.loading}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t.admin.team.name}</th>
                  <th>{t.admin.team.email}</th>
                  <th>{t.admin.team.oab}</th>
                  <th>{t.admin.team.role}</th>
                  {canManage && <th />}
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.user_id}>
                    <td>
                      {m.name}
                      {m.user_id === me.user.id && (
                        <span className="muted"> ({t.admin.team.you})</span>
                      )}
                    </td>
                    <td>{m.email}</td>
                    <td>{m.oab ?? t.common.none}</td>
                    <td>
                      {canManage ? (
                        <select
                          value={m.role}
                          onChange={(e) => changeRole(m, e.target.value as Role)}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {t.roles[r]}
                            </option>
                          ))}
                        </select>
                      ) : (
                        t.roles[m.role]
                      )}
                    </td>
                    {canManage && (
                      <td>
                        {m.user_id !== me.user.id && (
                          <button type="button" className="link" onClick={() => remove(m)}>
                            {t.admin.team.remove}
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
    </>
  );
}
