import { describe, expect, it } from "vitest";

import { formatBytes, snippetParts, uploadContentType } from "@/lib/format";

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
