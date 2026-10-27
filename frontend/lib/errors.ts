import { t } from "@/lib/i18n";

type ErrorCode = keyof typeof t.errors;

/** Turn an API error body ({ detail: "code" }) into a message for the user, in pt-BR. */
export function errorMessage(body: unknown): string {
  const detail =
    typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail: unknown }).detail
      : undefined;
  if (typeof detail === "string" && detail in t.errors) {
    return t.errors[detail as ErrorCode];
  }
  return t.errors.unknown;
}
