import { afterEach, describe, expect, it, vi } from "vitest";

import { createDecision, createUuidV7 } from "./decisionCommand";

afterEach(() => vi.restoreAllMocks());

describe("capability decision identity", () => {
  it("creates a canonical UUIDv7 with Web Crypto randomness", () => {
    vi.spyOn(crypto, "getRandomValues").mockImplementation((value) => {
      new Uint8Array(value.buffer).fill(0xab);
      return value;
    });
    expect(createUuidV7(0x0199_1234_5678)).toBe(
      "01991234-5678-7bab-abab-abababababab",
    );
  });

  it("keeps limit fields explicit and omits them for deny", () => {
    const limited = createDecision(3, "limit", {
      validForSeconds: 60,
      maxUses: 1,
    });
    expect(limited.expected_request_version).toBe(3);
    expect(limited.valid_for_seconds).toBe(60);
    const denied = createDecision(4, "deny");
    expect(denied).not.toHaveProperty("valid_for_seconds");
  });
});
