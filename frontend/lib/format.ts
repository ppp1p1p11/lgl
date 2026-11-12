const TZ = "America/Sao_Paulo";

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", {
    timeZone: TZ,
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** A calendar date ("2026-03-09") as dd/mm/aaaa, without time-zone shifts. */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

/** Today in São Paulo, as "aaaa-mm-dd" (the format date inputs and the API use). */
export function todayIso(): string {
  return new Date().toLocaleDateString("sv-SE", { timeZone: TZ });
}

/** Replace {name} placeholders in a message. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k: string) => String(values[k] ?? ""));
}

/** Translated label for a code, or the code itself when there is no translation. */
export function label<T extends Record<string, string>>(
  map: T,
  key: string | null | undefined,
): string {
  return (key != null ? map[key as keyof T] : undefined) ?? key ?? "";
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

const EXTENSION_TYPES: Record<string, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
};

/** Content type to declare for an upload. The server checks the real type anyway. */
export function uploadContentType(file: { name: string; type: string }): string {
  if (Object.values(EXTENSION_TYPES).includes(file.type)) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSION_TYPES[ext] ?? file.type ?? "application/octet-stream";
}

/** Split a search snippet into plain and highlighted parts (markers U+0002 / U+0003). */
export function snippetParts(snippet: string): { text: string; match: boolean }[] {
  const parts: { text: string; match: boolean }[] = [];
  let match = false;
  let current = "";
  for (const ch of snippet) {
    if (ch === "\u0002" || ch === "\u0003") {
      if (current) parts.push({ text: current, match });
      current = "";
      match = ch === "\u0002";
    } else {
      current += ch;
    }
  }
  if (current) parts.push({ text: current, match });
  return parts;
}
