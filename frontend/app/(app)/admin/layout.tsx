"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { t } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { permissions } = useSession();
  const tabs = [
    { href: "/admin/equipe", label: t.admin.equipe, show: permissions.includes("view_members") },
    {
      href: "/admin/auditoria",
      label: t.admin.auditoria,
      show: permissions.includes("view_audit_log"),
    },
    { href: "/admin/ia", label: t.admin.ia, show: permissions.includes("manage_firm") },
  ].filter((tab) => tab.show);

  return (
    <>
      <h1>{t.admin.title}</h1>
      <nav className="tabs">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className={pathname.startsWith(tab.href) ? "active" : ""}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
      {children}
    </>
  );
}
