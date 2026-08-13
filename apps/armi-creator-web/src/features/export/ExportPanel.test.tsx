import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportPanel } from "./ExportPanel";

const TOKEN = `browser-v1.${"a".repeat(43)}`;

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ExportPanel token={TOKEN} onUnauthorized={vi.fn()} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator local export panel", () => {
  it("submits one restricted directory and exposes partial completeness", async () => {
    const requestKeys: string[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      expect(init?.headers).toMatchObject({
        Authorization: `Bearer ${TOKEN}`,
        "Idempotency-Key": expect.stringMatching(/^creator-export-/),
      });
      expect(JSON.parse(String(init?.body))).toEqual({
        contract_version: "1.0",
        directory_name: "creator-export-20260808",
      });
      const requestKey = (
        init?.headers as Record<string, string> | undefined
      )?.["Idempotency-Key"];
      if (requestKey === undefined) {
        throw new Error("Idempotency-Key is required");
      }
      requestKeys.push(requestKey);
      return new Response(
        JSON.stringify({
          contract_version: "1.0",
          projection_version: "creator-export.v2",
          export_id: "0198a000-0000-7000-8000-000000000001",
          status: "partial",
          directory_name: "creator-export-20260808",
          destination_path: "data/exports/creator-export-20260808",
          segment_count: 39,
          record_count: 120,
          artifact_count: 4,
          missing_artifacts: [`sha256:${"2".repeat(64)}`],
          error_code: null,
          created_at: "2026-08-08T05:00:00.000000Z",
          completed_at: "2026-08-08T05:00:01.000000Z",
          newly_created: true,
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    await user.type(
      screen.getByLabelText("导出目录名"),
      "creator-export-20260808",
    );
    await user.click(screen.getByRole("button", { name: "生成本地导出" }));

    expect(await screen.findByText(/它不是完整备份/)).toBeInTheDocument();
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(
      screen.getByText("data/exports/creator-export-20260808"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "生成本地导出" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(requestKeys[1]).toBe(requestKeys[0]);
  });
});
