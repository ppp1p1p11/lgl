import { t } from "@/lib/i18n";

export default function ProcessosPage() {
  return (
    <>
      <h1>{t.processos.title}</h1>
      <div className="card">
        <h2>{t.processos.emptyTitle}</h2>
        <p className="muted">{t.processos.emptyBody}</p>
      </div>
    </>
  );
}
