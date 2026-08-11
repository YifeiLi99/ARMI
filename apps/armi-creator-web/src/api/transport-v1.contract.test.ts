import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const vectorPath = resolve(
  process.cwd(),
  "../../tests/contracts/fixtures/transport-v1.json",
);
const vector: unknown = JSON.parse(readFileSync(vectorPath, "utf8"));

const statuses = [
  "accepted",
  "applied",
  "waiting",
  "rejected",
  "unavailable",
  "failed",
  "unknown",
  "completed",
] as const;

const commonFields = [
  "contract_version",
  "message",
  "occurred_at",
  "status",
  "trace_id",
];

const variantFields: Record<(typeof statuses)[number], readonly string[]> = {
  accepted: ["custodian", "details", "result_ref"],
  applied: ["result_ref", "state_version"],
  waiting: ["result_ref", "resume_condition", "waiting_for"],
  rejected: ["error"],
  unavailable: ["error", "recovery_hint"],
  failed: ["error"],
  unknown: ["custodian", "result_ref", "verification_action"],
  completed: ["result_ref"],
};

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("vector object expected");
  }
  return value as Record<string, unknown>;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error("vector array expected");
  }
  return value;
}

function rejectionCode(kind: unknown, value: unknown): string | null {
  if (kind === "contract_version") {
    return value === "1.0" ? null : "CON-VERSION";
  }
  if (kind === "uuid") {
    return typeof value === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
        value,
      )
      ? null
      : "CON-ID";
  }
  if (kind === "trace_id") {
    return typeof value === "string" &&
      /^[0-9a-f]{32}$/.test(value) &&
      value !== "0".repeat(32)
      ? null
      : "CON-TRACE";
  }
  if (kind === "digest") {
    return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value)
      ? null
      : "CON-DIGEST";
  }
  if (kind === "instant") {
    return typeof value === "string" &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?!00:00)\d{2}:\d{2})$/.test(
        value,
      )
      ? null
      : "CON-TIME";
  }
  if (kind === "outcome_status") {
    return statuses.includes(value as (typeof statuses)[number])
      ? null
      : "CON-OUTCOME";
  }
  if (kind === "cursor") {
    return typeof value === "string" &&
      value.length <= 2048 &&
      /^v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value)
      ? null
      : "CON-PAGE";
  }
  if (kind === "limit") {
    return typeof value === "number" &&
      Number.isInteger(value) &&
      value >= 1 &&
      value <= 100
      ? null
      : "CON-PAGE";
  }
  throw new Error(`unknown invalid-vector kind: ${String(kind)}`);
}

describe("transport v1 shared contract vector", () => {
  it("exhausts the eight statuses with exact variant fields", () => {
    const root = record(vector);
    expect(root.contract_version).toBe("1.0");
    const valid = record(root.valid);
    const outcomes = list(valid.outcomes).map(record);
    expect(outcomes.map((outcome) => outcome.status)).toEqual(statuses);

    for (const outcome of outcomes) {
      const status = outcome.status as (typeof statuses)[number];
      expect(Object.keys(outcome).sort()).toEqual(
        [...commonFields, ...variantFields[status]].sort(),
      );
      expect(outcome.contract_version).toBe("1.0");
    }
  });

  it("agrees on stable rejection codes for every invalid vector", () => {
    const root = record(vector);
    for (const item of list(root.invalid).map(record)) {
      expect(rejectionCode(item.kind, item.value), String(item.id)).toBe(
        item.expected_code,
      );
    }
  });

  it("keeps conflict as rejected plus an error descriptor", () => {
    const root = record(vector);
    const outcomes = list(record(root.valid).outcomes).map(record);
    expect(outcomes.some((outcome) => outcome.status === "conflict")).toBe(
      false,
    );
    const rejected = outcomes.find((outcome) => outcome.status === "rejected");
    expect(record(rejected?.error).code).toBe("CONFLICT_SUBJECT_VERSION");
  });
});
