"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, type Me } from "@/lib/api/client";
import { t } from "@/lib/i18n";

/** Shell for signed-in pages: checks the session, shows the firm switcher and logout. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  /** Returns the signed-in user, or redirects to login / MFA and returns null. */
  const fetchMe = useCallback(async (): Promise<Me | null> => {
    const { data } = await api.GET("/api/auth/me");
    if (!data) {
      router.replace("/entrar");
      return null;
    }
    if (!data.mfa_verified) {
      router.replace("/entrar/mfa?etapa=verificar");
      return null;
    }
    return data;
  }, [router]);

  useEffect(() => {
    fetchMe().then(setMe);
  }, [fetchMe]);

  async function switchFirm(tenantId: string) {
    await api.POST("/api/auth/switch-firm", { body: { tenant_id: tenantId } });
    setMe(await fetchMe());
    router.refresh();
  }

  async function logout() {
    await api.POST("/api/auth/logout");
    router.replace("/entrar");
  }

  if (!me) return null;

  return (
    <>
      <header className="topbar">
        <nav>
          <strong>{t.app.name}</strong>
          <Link href="/processos">{t.shell.processos}</Link>
        </nav>
        <nav>
          {me.firms.length > 0 && (
            <label>
              <span className="muted">{t.shell.firm}</span>
              <select
                value={me.current_firm?.id ?? ""}
                onChange={(e) => switchFirm(e.target.value)}
              >
                {me.firms.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} — {t.roles[f.role]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <span>{me.user.name}</span>
          <button type="button" onClick={logout}>
            {t.shell.logout}
          </button>
        </nav>
      </header>
      <main>{me.current_firm ? children : <p>{t.shell.noFirm}</p>}</main>
    </>
  );
}
