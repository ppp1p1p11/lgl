"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, type Me } from "@/lib/api/client";
import { t } from "@/lib/i18n";
import { SessionProvider } from "@/lib/session";

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
    // Pages announce account changes (e.g. a new password) so the shell re-reads them.
    const onAccountChanged = () => fetchMe().then(setMe);
    window.addEventListener("legalos:account-changed", onAccountChanged);
    return () => window.removeEventListener("legalos:account-changed", onAccountChanged);
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
  const can = (permission: Me["permissions"][number]) => me.permissions.includes(permission);

  return (
    <>
      <header className="topbar">
        <nav>
          <strong>{t.app.name}</strong>
          <Link href="/processos">{t.shell.processos}</Link>
          <Link href="/clientes">{t.shell.clientes}</Link>
          <Link href="/agenda">{t.shell.agenda}</Link>
          {can("view_ai_outputs") && <Link href="/pesquisa">{t.shell.pesquisa}</Link>}
          {can("view_ai_outputs") && <Link href="/acervo">{t.shell.acervo}</Link>}
          {can("view_members") && <Link href="/admin">{t.shell.admin}</Link>}
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
          <Link href="/conta" title={t.shell.conta}>
            {me.user.name}
          </Link>
          <button type="button" onClick={logout}>
            {t.shell.logout}
          </button>
        </nav>
      </header>
      <main>
        {me.must_change_password && (
          <p className="warning">
            {t.shell.mustChangePassword} <Link href="/conta">{t.shell.conta}</Link>
          </p>
        )}
        {me.current_firm ? (
          // Remount pages when the firm changes, so no data from the previous firm lingers.
          <SessionProvider value={me} key={me.current_firm.id}>
            {children}
          </SessionProvider>
        ) : (
          <p>{t.shell.noFirm}</p>
        )}
      </main>
    </>
  );
}
