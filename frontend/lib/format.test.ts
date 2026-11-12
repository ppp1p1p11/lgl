import { describe, expect, it } from "vitest";

import {
  fill,
  formatBytes,
  formatDate,
  label,
  snippetParts,
  uploadContentType,
} from "@/lib/format";

describe("snippetParts", () => {
  it("splits highlighted matches without interpreting HTML", () => {
    expect(snippetParts("as \u0002transferências\u0003 <b>bancárias</b>")).toEqual([
      { text: "as ", match: false },
      { text: "transferências", match: true },
      { text: " <b>bancárias</b>", match: false },
    ]);
  });
});

describe("uploadContentType", () => {
  it("trusts known browser types and falls back to the extension", () => {
    expect(uploadContentType({ name: "a.pdf", type: "application/pdf" })).toBe("application/pdf");
    expect(uploadContentType({ name: "FOTO.JPG", type: "" })).toBe("image/jpeg");
    expect(uploadContentType({ name: "x.exe", type: "application/x-msdownload" })).toBe(
      "application/x-msdownload",
    );
  });
});

describe("formatBytes", () => {
  it("uses Brazilian decimal separators", () => {
    expect(formatBytes(2.5 * 1024 * 1024)).toBe("2,5 MB");
    expect(formatBytes(100)).toBe("1 KB");
  });
});

describe("formatDate", () => {
  it("shows a calendar date as dd/mm/aaaa without shifting the day", () => {
    expect(formatDate("2026-03-09")).toBe("09/03/2026");
    expect(formatDate("2026-01-01T00:00:00Z")).toBe("01/01/2026");
  });
});

describe("fill and label", () => {
  it("fills placeholders and falls back to the code", () => {
    expect(fill("Versão {n} de {total}", { n: 2, total: 3 })).toBe("Versão 2 de 3");
    expect(label({ a: "Alfa" }, "a")).toBe("Alfa");
    expect(label({ a: "Alfa" }, "zzz")).toBe("zzz");
    expect(label({ a: "Alfa" }, null)).toBe("");
  });
});
