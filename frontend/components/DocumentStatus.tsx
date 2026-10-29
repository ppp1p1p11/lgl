import type { components } from "@/lib/api/schema";
import { t } from "@/lib/i18n";

type Version = components["schemas"]["VersionOut"];

export function isPending(v: Version | null | undefined): boolean {
  return !!v && (v.status === "uploaded" || v.status === "processing");
}

export function DocumentStatus({ version }: { version: Version }) {
  const errorText =
    version.error_code && version.error_code in t.documento.errors
      ? t.documento.errors[version.error_code as keyof typeof t.documento.errors]
      : null;
  return (
    <span>
      <span className={`badge doc-${version.status}`}>{t.documento.status[version.status]}</span>
      {version.status === "ready" && version.low_ocr_confidence && (
        <span className="badge warn" title={t.documento.lowConfidence}>
          OCR
        </span>
      )}
      {errorText && <span className="error small"> {errorText}</span>}
    </span>
  );
}
