"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { DocumentStatus, isPending } from "@/components/DocumentStatus";
import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";
import { uploadFile } from "@/lib/upload";

type DocumentDetail = components["schemas"]["DocumentDetail"];
type Page = components["schemas"]["PageOut"];

const METHOD_LABEL = {
  ocr: t.documento.ocr,
  text_layer: t.documento.textLayer,
  docx: t.documento.docx,
} as const;

function Viewer() {
  const { id: matterId, docId } = useParams<{ id: string; docId: string }>();
  const initialPage = Number(useSearchParams().get("pagina") ?? "1");
  const canUpload = useCan("manage_documents");
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [pages, setPages] = useState<Page[]>([]);
  const [file, setFile] = useState<{ url: string; type: string | null } | null>(null);
  const [pageNumber, setPageNumber] = useState(initialPage);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const pageRefs = useRef<Record<number, HTMLElement | null>>({});

  const fetchDoc = useCallback(async () => {
    const { data } = await api.GET("/api/documents/{document_id}", {
      params: { path: { document_id: docId } },
    });
    return data ?? null;
  }, [docId]);

  const applyDoc = useCallback((data: DocumentDetail | null) => {
    if (!data) return;
    setDoc(data);
    setVersionId((current) => current ?? data.current_version?.id ?? data.latest_version.id);
  }, []);

  const loadDoc = useCallback(() => fetchDoc().then(applyDoc), [fetchDoc, applyDoc]);

  useEffect(() => {
    fetchDoc().then(applyDoc);
  }, [fetchDoc, applyDoc]);

  const version = doc?.versions.find((v) => v.id === versionId) ?? null;
  const ready = version?.status === "ready";

  useEffect(() => {
    if (!isPending(doc?.latest_version)) return;
    const timer = setInterval(loadDoc, 2000);
    return () => clearInterval(timer);
  }, [doc, loadDoc]);

  useEffect(() => {
    if (!versionId || !ready) return;
    const path = { params: { path: { version_id: versionId } } };
    api.GET("/api/document-versions/{version_id}/pages", path).then(({ data }) => {
      setPages(data ?? []);
    });
    api.GET("/api/document-versions/{version_id}/file-url", path).then(({ data }) => {
      setFile(data ? { url: data.url, type: data.content_type } : null);
    });
  }, [versionId, ready]);

  useEffect(() => {
    if (pages.length) pageRefs.current[initialPage]?.scrollIntoView({ block: "start" });
  }, [pages, initialPage]);

  async function onNewVersion(files: FileList | null) {
    const selected = files?.[0];
    if (!selected) return;
    const error = await uploadFile(selected, { documentId: docId });
    setUploadError(error);
    setVersionId(null);
    loadDoc();
  }

  if (!doc) return <p className="muted">{t.common.loading}</p>;

  return (
    <>
      <p>
        <Link href={`/processos/${matterId}`}>← {t.common.back}</Link>
      </p>
      <div className="page-header">
        <h1>{doc.title}</h1>
        {canUpload && (
          <label className="button secondary">
            {t.documento.newVersion}
            <input
              type="file"
              hidden
              accept=".pdf,.docx,.jpg,.jpeg,.png"
              onChange={(e) => onNewVersion(e.target.files)}
            />
          </label>
        )}
      </div>
      <ErrorText message={uploadError} />
      <div className="toolbar">
        <label>
          {t.documento.version}{" "}
          <select value={versionId ?? ""} onChange={(e) => setVersionId(e.target.value)}>
            {doc.versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.version_no} — {v.original_filename} ({formatDateTime(v.created_at)})
              </option>
            ))}
          </select>
        </label>
        {version && <DocumentStatus version={version} />}
      </div>

      {version && !ready && isPending(version) && <p className="muted">{t.documento.processing}</p>}

      {ready && (
        <>
          {version?.low_ocr_confidence && <p className="warning">{t.documento.lowConfidence}</p>}
          <div className="side-by-side">
            <section className="pane">
              <h2>{t.documento.original}</h2>
              {file && <OriginalFile file={file} page={pageNumber} />}
            </section>
            <section className="pane text-pane">
              <h2>{t.documento.extracted}</h2>
              {pages.map((p) => (
                <article
                  key={p.page_number}
                  ref={(el) => {
                    pageRefs.current[p.page_number] = el;
                  }}
                  className={`page${p.page_number === pageNumber ? " current" : ""}`}
                  onClick={() => setPageNumber(p.page_number)}
                >
                  <header className="muted small">
                    {t.documento.page} {p.page_number} · {METHOD_LABEL[p.method]}
                    {p.ocr_confidence != null &&
                      ` · ${t.documento.confidence} ${Math.round(p.ocr_confidence)}%`}
                    {p.low_ocr_confidence && <span className="badge warn">OCR</span>}
                  </header>
                  <pre>{p.text}</pre>
                </article>
              ))}
            </section>
          </div>
        </>
      )}
    </>
  );
}

function OriginalFile({
  file,
  page,
}: {
  file: { url: string; type: string | null };
  page: number;
}) {
  if (file.type === "pdf") {
    return (
      <iframe
        key={page}
        className="original"
        src={`${file.url}#page=${page}`}
        title={t.documento.original}
      />
    );
  }
  if (file.type === "png" || file.type === "jpeg") {
    // eslint-disable-next-line @next/next/no-img-element -- signed storage URL
    return <img className="original" src={file.url} alt={t.documento.original} />;
  }
  return (
    <p>
      {t.documento.noPreview}{" "}
      <a href={file.url} target="_blank" rel="noreferrer">
        {t.documento.openOriginal}
      </a>
    </p>
  );
}

export default function DocumentoPage() {
  return (
    <Suspense>
      <Viewer />
    </Suspense>
  );
}
