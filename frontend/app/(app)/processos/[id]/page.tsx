"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { DocumentStatus, isPending } from "@/components/DocumentStatus";
import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { formatBytes, formatDateTime, snippetParts } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";
import { uploadFile } from "@/lib/upload";

type Matter = components["schemas"]["MatterDetail"];
type Doc = components["schemas"]["DocumentOut"];
type Event = components["schemas"]["EventOut"];
type Hit = components["schemas"]["SearchHitOut"];
type PartyRole = components["schemas"]["PartyIn"]["role"];
type Status = components["schemas"]["MatterSummary"]["status"];

const PARTY_ROLES = Object.keys(t.processo.roles) as PartyRole[];
const STATUSES = Object.keys(t.processos.statuses) as Status[];

export default function ProcessoPage() {
  const { id } = useParams<{ id: string }>();
  const canManage = useCan("manage_clients");
  const canUpload = useCan("manage_documents");
  const [matter, setMatter] = useState<Matter | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const path = { params: { path: { matter_id: id } } };
    const [m, d, e] = await Promise.all([
      api.GET("/api/matters/{matter_id}", path),
      api.GET("/api/matters/{matter_id}/documents", path),
      api.GET("/api/matters/{matter_id}/events", path),
    ]);
    return { matter: m.data, docs: d.data ?? [], events: e.data ?? [] };
  }, [id]);

  const apply = useCallback((r: Awaited<ReturnType<typeof load>>) => {
    if (!r.matter) {
      setNotFound(true);
      return;
    }
    setMatter(r.matter);
    setDocs(r.docs);
    setEvents(r.events);
  }, []);

  const refresh = useCallback(() => load().then(apply), [load, apply]);

  useEffect(() => {
    load().then(apply);
  }, [load, apply]);

  // While any document is queued or processing, refresh every 2 seconds.
  const pending = docs.some((d) => isPending(d.latest_version));
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [pending, refresh]);

  async function onFiles(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      const error = await uploadFile(file, { matterId: id });
      if (error) errors.push(`${file.name}: ${error}`);
    }
    setUploadErrors(errors);
    setUploading(false);
    if (fileInput.current) fileInput.current.value = "";
    refresh();
  }

  async function changeStatus(status: Status) {
    const { data } = await api.PATCH("/api/matters/{matter_id}", {
      params: { path: { matter_id: id } },
      body: { status },
    });
    if (data) setMatter(data);
    refresh();
  }

  if (notFound) return <p>{t.errors.matter_not_found}</p>;
  if (!matter) return <p className="muted">{t.common.loading}</p>;

  return (
    <>
      <p>
        <Link href="/processos">← {t.processos.title}</Link>
      </p>
      <h1>{matter.title}</h1>
      <dl className="facts">
        <div>
          <dt>{t.processos.fields.cnj}</dt>
          <dd className="mono">{matter.cnj_number ?? t.common.none}</dd>
        </div>
        <div>
          <dt>{t.processos.fields.client}</dt>
          <dd>{matter.client_name}</dd>
        </div>
        <div>
          <dt>{t.processos.fields.area}</dt>
          <dd>{t.processos.areas[matter.area]}</dd>
        </div>
        <div>
          <dt>{t.processos.fields.court}</dt>
          <dd>
            {[matter.court, matter.comarca, matter.vara].filter(Boolean).join(" · ") ||
              t.common.none}
          </dd>
        </div>
        <div>
          <dt>{t.processos.fields.status}</dt>
          <dd>
            {canManage ? (
              <select
                value={matter.status}
                onChange={(e) => changeStatus(e.target.value as Status)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t.processos.statuses[s]}
                  </option>
                ))}
              </select>
            ) : (
              t.processos.statuses[matter.status]
            )}
          </dd>
        </div>
      </dl>
      {matter.description && <p>{matter.description}</p>}

      <section className="card">
        <div className="page-header">
          <h2>{t.processo.documents}</h2>
          {canUpload && (
            <label className="button">
              {uploading ? t.processo.uploading : t.processo.upload}
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                disabled={uploading}
                accept=".pdf,.docx,.jpg,.jpeg,.png"
                onChange={(e) => onFiles(e.target.files)}
              />
            </label>
          )}
        </div>
        <p className="muted small">{t.processo.uploadHint}</p>
        {uploadErrors.map((e) => (
          <ErrorText key={e} message={e} />
        ))}
        {docs.length === 0 ? (
          <p className="muted">{t.processo.noDocuments}</p>
        ) : (
          <ul className="doc-list">
            {docs.map((d) => (
              <li key={d.id}>
                <Link href={`/processos/${id}/documentos/${d.id}`}>{d.title}</Link>{" "}
                <DocumentStatus version={d.latest_version} />
                <span className="muted small">
                  {" "}
                  {d.latest_version.page_count != null &&
                    `${d.latest_version.page_count} ${
                      d.latest_version.page_count === 1
                        ? t.documento.pageSingular
                        : t.documento.pages
                    } · `}
                  {formatBytes(d.latest_version.size_bytes)}
                  {d.latest_version.version_no > 1 &&
                    ` · ${t.documento.version} ${d.latest_version.version_no}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <SearchSection matterId={id} />
      <PartiesSection matter={matter} canManage={canManage} onChange={setMatter} />

      <section className="card">
        <h2>{t.processo.team}</h2>
        <ul>
          {matter.members.map((m) => (
            <li key={m.user_id}>
              {m.name}{" "}
              <span className="muted">({t.processo.responsibility[m.responsibility]})</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>{t.processo.timeline}</h2>
        <ol className="timeline">
          {events.map((e) => (
            <li key={e.id}>
              <span className="muted small">{formatDateTime(e.occurred_at)}</span> {e.summary}
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function SearchSection({ matterId }: { matterId: string }) {
  const [hits, setHits] = useState<Hit[] | null>(null);

  async function onSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = String(new FormData(event.currentTarget).get("q")).trim();
    if (q.length < 2) return;
    const { data } = await api.GET("/api/matters/{matter_id}/search", {
      params: { path: { matter_id: matterId }, query: { q } },
    });
    setHits(data ?? []);
  }

  return (
    <section className="card">
      <h2>{t.processo.search}</h2>
      <form className="inline" onSubmit={onSearch}>
        <input name="q" type="search" placeholder={t.processo.searchPlaceholder} minLength={2} />
        <button type="submit">{t.common.search}</button>
      </form>
      {hits !== null &&
        (hits.length === 0 ? (
          <p className="muted">{t.processo.noResults}</p>
        ) : (
          <ul className="hits">
            {hits.map((h, i) => (
              <li key={`${h.version_id}-${h.page_number}-${i}`}>
                <Link
                  href={`/processos/${matterId}/documentos/${h.document_id}?pagina=${h.page_number}`}
                >
                  {h.document_title}, {t.processo.page} {h.page_number}
                </Link>
                <p className="snippet">
                  {snippetParts(h.snippet).map((p, j) =>
                    p.match ? <mark key={j}>{p.text}</mark> : <span key={j}>{p.text}</span>,
                  )}
                </p>
              </li>
            ))}
          </ul>
        ))}
    </section>
  );
}

function PartiesSection({
  matter,
  canManage,
  onChange,
}: {
  matter: Matter;
  canManage: boolean;
  onChange: (m: Matter) => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onAdd(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const documentNumber = String(form.get("document_number") ?? "").trim();
    const kind = String(form.get("kind") ?? "");
    const { data, error: apiError } = await api.POST("/api/matters/{matter_id}/parties", {
      params: { path: { matter_id: matter.id } },
      body: {
        name: String(form.get("name")),
        role: form.get("role") as PartyRole,
        kind: kind === "PF" || kind === "PJ" ? kind : null,
        is_client: form.get("is_client") === "on",
        document_number: documentNumber || null,
      },
    });
    if (!data) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    setShowForm(false);
    onChange(data);
  }

  return (
    <section className="card">
      <div className="page-header">
        <h2>{t.processo.parties}</h2>
        {canManage && !showForm && (
          <button type="button" className="secondary" onClick={() => setShowForm(true)}>
            {t.processo.addParty}
          </button>
        )}
      </div>
      {matter.parties.length === 0 ? (
        <p className="muted">{t.processo.noParties}</p>
      ) : (
        <ul>
          {matter.parties.map((p) => (
            <li key={p.id}>
              {p.name} <span className="muted">— {t.processo.roles[p.role]}</span>
              {p.document_number && <span className="muted mono"> · {p.document_number}</span>}
              {p.is_client && <span className="badge"> {t.processo.isClient}</span>}
            </li>
          ))}
        </ul>
      )}
      {showForm && (
        <form onSubmit={onAdd}>
          <div className="grid">
            <label>
              {t.processo.partyName}
              <input name="name" required minLength={2} maxLength={300} />
            </label>
            <label>
              {t.processo.partyRole}
              <select name="role" defaultValue="reu">
                {PARTY_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {t.processo.roles[r]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.clientes.kind}
              <select name="kind" defaultValue="">
                <option value="">{t.common.none}</option>
                <option value="PF">{t.clientes.kinds.PF}</option>
                <option value="PJ">{t.clientes.kinds.PJ}</option>
              </select>
            </label>
            <label>
              {t.clientes.documentNumber} <span className="muted">({t.common.optional})</span>
              <input name="document_number" maxLength={30} />
            </label>
          </div>
          <label className="checkbox">
            <input type="checkbox" name="is_client" /> {t.processo.isClient}
          </label>
          <ErrorText message={error} />
          <div className="actions">
            <button type="submit">{t.common.add}</button>
            <button type="button" className="secondary" onClick={() => setShowForm(false)}>
              {t.common.cancel}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
