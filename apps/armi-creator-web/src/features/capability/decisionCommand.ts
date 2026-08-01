import type { CapabilityDecision } from "../../api/client";

export function createUuidV7(now = Date.now()): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const timestamp = BigInt(now);
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = Number(timestamp >> BigInt((5 - index) * 8)) & 0xff;
  }
  bytes[6] = (bytes[6]! & 0x0f) | 0x70;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export function createDecision(
  expectedRequestVersion: number,
  decision: CapabilityDecision["decision"],
  limits?: {
    validForSeconds?: number;
    maxUses?: number;
    maxPayloadBytes?: number;
  },
): CapabilityDecision {
  return {
    contract_version: "1.0",
    decision_id: createUuidV7(),
    expected_request_version: expectedRequestVersion,
    decision,
    ...(limits?.validForSeconds === undefined
      ? {}
      : { valid_for_seconds: limits.validForSeconds }),
    ...(limits?.maxUses === undefined ? {} : { max_uses: limits.maxUses }),
    ...(limits?.maxPayloadBytes === undefined
      ? {}
      : { max_payload_bytes: limits.maxPayloadBytes }),
  };
}
