import { describe, expect, it, vi } from "vitest";

import { createCreatorInputKey, validateCreatorMessage } from "./messageIntent";

describe("Creator input intent", () => {
  it("preserves valid text and rejects unsafe or empty input", () => {
    expect(validateCreatorMessage("  exact\r\ntext  ")).toEqual({
      valid: true,
    });
    expect(validateCreatorMessage(" \r\n\t ")).toEqual({
      valid: false,
      message: "请输入至少一个非空白字符。",
    });
    expect(validateCreatorMessage("bad\u0000text").valid).toBe(false);
    expect(validateCreatorMessage("\ud800").valid).toBe(false);
  });

  it("applies the encoded 256 KiB request boundary", () => {
    expect(validateCreatorMessage("a".repeat(256 * 1024)).valid).toBe(false);
    expect(validateCreatorMessage("a".repeat(255 * 1024)).valid).toBe(true);
  });

  it("creates a fresh 128-bit browser-only idempotency identity", () => {
    vi.spyOn(crypto, "getRandomValues").mockImplementation((value) => {
      const bytes = value as Uint8Array;
      bytes.forEach((_, index) => {
        bytes[index] = index;
      });
      return value;
    });
    expect(createCreatorInputKey()).toBe(
      "creator-input-v1.AAECAwQFBgcICQoLDA0ODw",
    );
  });
});
