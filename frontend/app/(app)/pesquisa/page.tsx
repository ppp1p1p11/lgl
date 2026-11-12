"use client";

import Link from "next/link";

import { ResearchPanel } from "@/components/Research";
import { t } from "@/lib/i18n";

export default function PesquisaPage() {
  return (
    <>
      <div className="page-header">
        <h1>{t.pesquisa.title}</h1>
        <Link className="button secondary" href="/acervo">
          {t.shell.acervo}
        </Link>
      </div>
      <ResearchPanel title={t.pesquisa.history} />
    </>
  );
}
