"use client";

import { useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/errors";
import { t } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function ContaPage() {
  const me = useSession();
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const next = String(form.get("new"));
    setChanged(false);
    if (next !== String(form.get("repeat"))) {
      setError(t.conta.mismatch);
      return;
    }
    const { error: apiError } = await api.POST("/api/auth/password", {
      body: { current_password: String(form.get("current")), new_password: next },
    });
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    setChanged(true);
    formElement.reset();
    // Tell the shell to re-read the account (clears the temporary-password banner).
    window.dispatchEvent(new Event("legalos:account-changed"));
  }

  return (
    <>
      <h1>{t.conta.title}</h1>
      <p className="muted">
        {me.user.name} · {me.user.email}
      </p>
      <form className="card narrow" onSubmit={onSubmit}>
        <h2>{t.conta.password}</h2>
        <label>
          {t.conta.current}
          <input name="current" type="password" required autoComplete="current-password" />
        </label>
        <label>
          {t.conta.new}
          <input name="new" type="password" required minLength={12} autoComplete="new-password" />
        </label>
        <label>
          {t.conta.repeat}
          <input
            name="repeat"
            type="password"
            required
            minLength={12}
            autoComplete="new-password"
          />
        </label>
        <p className="muted small">{t.conta.hint}</p>
        <ErrorText message={error} />
        {changed && <p>{t.conta.changed}</p>}
        <div className="actions">
          <button type="submit">{t.conta.submit}</button>
        </div>
      </form>
    </>
  );
}
