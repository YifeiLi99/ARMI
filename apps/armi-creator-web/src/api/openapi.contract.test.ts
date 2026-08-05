import type {
  CreatorProjectionEventResponse,
  LiveResponse,
  ReadyResponse,
  RejectedOutcome,
  RuntimeStatusResponse,
  UnavailableOutcome,
} from "./index";
import { describe, expectTypeOf, it } from "vitest";

describe("generated Creator OpenAPI types", () => {
  it("exposes only the frozen steel-frame responses", () => {
    expectTypeOf<LiveResponse["status"]>().toEqualTypeOf<"alive">();
    expectTypeOf<ReadyResponse["status"]>().toEqualTypeOf<
      "ready" | "not_ready"
    >();
    expectTypeOf<
      RuntimeStatusResponse["contract_version"]
    >().toEqualTypeOf<"1.0">();
    expectTypeOf<RuntimeStatusResponse["runtime_state"]>().toEqualTypeOf<
      | "unborn"
      | "starting"
      | "recovering"
      | "ready"
      | "degraded"
      | "draining"
      | "stopped"
      | "blocked"
    >();
    expectTypeOf<RejectedOutcome["status"]>().toEqualTypeOf<"rejected">();
    expectTypeOf<UnavailableOutcome["status"]>().toEqualTypeOf<"unavailable">();
    expectTypeOf<CreatorProjectionEventResponse["event_kind"]>().toEqualTypeOf<
      | "activity.invalidated"
      | "memory.invalidated"
      | "maintenance.invalidated"
      | "material.invalidated"
      | "relationship.invalidated"
      | "scene.timeline.invalidated"
      | "capability.request.invalidated"
      | "operation.invalidated"
      | "effect.invalidated"
      | "subject.summary.invalidated"
    >();
  });
});
