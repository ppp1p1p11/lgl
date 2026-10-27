"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/errors";
import { t } from "@/lib/i18n";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError(null);
    const { data, error: apiError } = await api.POST("/api/auth/login", {
      body: { email: String(form.get("email")), password: String(form.get("password")) },
    });
    setSubmitting(false);
    if (!data) {
      setError(errorMessage(apiError));
      return;
    }
    const step = data.next_step === "mfa_setup" ? "configurar" : "verificar";
    router.push(`/entrar/mfa?etapa=${step}`);
  }

  return (
    <main className="auth">
      <div className="card">
        <h1>{t.app.name}</h1>
        <p className="muted">{t.app.tagline}</p>
        <h2>{t.login.title}</h2>
        <form onSubmit={onSubmit}>
          <label>
            {t.login.email}
            <input name="email" type="email" autoComplete="username" required />
          </label>
          <label>
            {t.login.password}
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={submitting}>
            {submitting ? t.login.submitting : t.login.submit}
          </button>
        </form>
      </div>
    </main>
  );
}
