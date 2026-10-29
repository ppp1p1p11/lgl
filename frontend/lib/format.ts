const TZ = "America/Sao_Paulo";

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", {
    timeZone: TZ,
    dateStyle: "short",
    timeStyle: "short",
  });
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
