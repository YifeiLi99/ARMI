import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RuntimeStatus } from "../../api/client";
import { RequiredComponentsCard } from "./RequiredComponentsCard";

const runtime: RuntimeStatus = {
  contract_version: "1.0",
  environment_id: "018f47a6-7b2d-7c35-8b18-684e38ab6ef7",
  runtime_state: "ready",
  readiness: "ready",
  reason_codes: [],
  components: [
    { component: "database", state: "ready", reason_codes: [] },
    { component: "runtime", state: "ready", reason_codes: [] },
    { component: "creator_web", state: "ready", reason_codes: [] },
  ],
  observed_at: "2026-08-21T08:00:00.000000Z",
};

afterEach(cleanup);

describe("required components card", () => {
  it("keeps required components on and refreshes their health", async () => {
    const onRefresh = vi.fn();
    render(<RequiredComponentsCard runtime={runtime} onRefresh={onRefresh} />);

    expect(screen.getAllByRole("switch")).toHaveLength(3);
    for (const control of screen.getAllByRole("switch")) {
      expect(control).toBeChecked();
      expect(control).toBeDisabled();
    }
    await userEvent.click(screen.getByRole("button", { name: "重新检测" }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});
