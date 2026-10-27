import { describe, expect, it } from "vitest";

import { errorMessage } from "@/lib/errors";

describe("errorMessage", () => {
  it("maps known API error codes to Portuguese messages", () => {
    expect(errorMessage({ detail: "invalid_credentials" })).toBe("E-mail ou senha incorretos.");
  });

  it("falls back to a generic message for unknown or malformed errors", () => {
    const generic = "Ocorreu um erro inesperado. Tente novamente.";
    expect(errorMessage({ detail: "something_new" })).toBe(generic);
    expect(errorMessage({ detail: [{ msg: "validation" }] })).toBe(generic);
    expect(errorMessage(null)).toBe(generic);
  });
});
