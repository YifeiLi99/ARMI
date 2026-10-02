import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PromptPanel } from "./PromptPanel";

const TOKEN = `browser-v1.${"a".repeat(43)}`;
const ENVIRONMENT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6efa";
const CREATOR_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6efb";
const DOCUMENT_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6efc";
const FIRST_REVISION = "018f47a6-7b2d-7c35-8b18-684e38ab6efd";
const SECOND_REVISION = "018f47a6-7b2d-7c35-8b18-684e38ab6efe";
const THIRD_REVISION = "018f47a6-7b2d-7c35-8b18-684e38ab6eff";

function jsonResponse(value: object, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function promptResponse(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    projection_kind: "creator-prompt",
    prompt_document_id: DOCUMENT_ID,
    prompt_kind: "creator_guidance",
    status: "active",
    current_revision_id: null,
    revision_no: null,
    previous_revision_id: null,
    revision_kind: null,
    content: null,
    activated_at: null,
    ...overrides,
  };
}

function renderPanel(
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <PromptPanel
        token={TOKEN}
        environmentId={ENVIRONMENT_ID}
        creatorPartyId={CREATOR_ID}
        onUnauthorized={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Creator Prompt panel", () => {
  it.each(["revision", "deactivation"])(
    "keeps a newer projection after an unmounted %s succeeds",
    async (operation) => {
      let settle!: (value: Response) => void;
      const response = new Promise<Response>((resolve) => {
        settle = resolve;
      });
      let reads = 0;
      const latest = promptResponse({
        current_revision_id: THIRD_REVISION,
        previous_revision_id: SECOND_REVISION,
        revision_no: 3,
        revision_kind: "revised",
        content: "最新指导",
        activated_at: "2026-08-06T10:02:00.000000Z",
      });
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>(async (_input, init) => {
          if (init?.method === "PUT" || init?.method === "POST") {
            return response;
          }
          reads += 1;
          return jsonResponse(
            reads === 1
              ? promptResponse({
                  current_revision_id: FIRST_REVISION,
                  revision_no: 1,
                  revision_kind: "created",
                  content: "旧指导",
                  activated_at: "2026-08-06T10:00:00.000000Z",
                })
              : latest,
          );
        }),
      );
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      const user = userEvent.setup();
      const oldPanel = renderPanel(queryClient);
      const editor = await screen.findByLabelText("Creator Prompt 内容");
      if (operation === "revision") {
        await user.clear(editor);
        await user.type(editor, "本次指导");
        await user.click(screen.getByRole("button", { name: "提交新修订" }));
      } else {
        await user.click(screen.getByRole("button", { name: "停用" }));
      }
      const mutation = queryClient.getMutationCache().getAll()[0];
      expect(mutation?.state.status).toBe("pending");
      oldPanel.unmount();
      queryClient.clear();
      renderPanel(queryClient);
      await waitFor(() =>
        expect(screen.getByLabelText("Creator Prompt 内容")).toHaveValue(
          "最新指导",
        ),
      );
      await act(async () => {
        settle(
          jsonResponse(
            promptResponse({
              status: operation === "revision" ? "active" : "inactive",
              current_revision_id: SECOND_REVISION,
              previous_revision_id: FIRST_REVISION,
              revision_no: 2,
              revision_kind:
                operation === "revision" ? "revised" : "deactivated",
              content: operation === "revision" ? "本次指导" : "旧指导",
              activated_at: "2026-08-06T10:01:00.000000Z",
            }),
          ),
        );
      });
      await waitFor(() => expect(mutation?.state.status).toBe("success"));
      expect(
        queryClient.getQueryData([
          "creator-prompt",
          ENVIRONMENT_ID,
          CREATOR_ID,
        ]),
      ).toEqual(latest);
      expect(screen.getByLabelText("Creator Prompt 内容")).toHaveValue(
        "最新指导",
      );
      expect(screen.getByText("生效中")).toBeInTheDocument();
    },
  );

  it("creates and then deactivates immutable revisions with current CAS", async () => {
    const bodies: unknown[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method === "PUT") {
        bodies.push(JSON.parse(String(init.body)));
        return jsonResponse(
          promptResponse({
            current_revision_id: FIRST_REVISION,
            revision_no: 1,
            revision_kind: "created",
            content: "请区分事实与推测。",
            activated_at: "2026-08-06T10:00:00.000000Z",
          }),
        );
      }
      if (init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)));
        return jsonResponse(
          promptResponse({
            status: "inactive",
            current_revision_id: SECOND_REVISION,
            revision_no: 2,
            previous_revision_id: FIRST_REVISION,
            revision_kind: "deactivated",
            content: "请区分事实与推测。",
            activated_at: "2026-08-06T10:01:00.000000Z",
          }),
        );
      }
      return jsonResponse(promptResponse());
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    const editor = await screen.findByLabelText("Creator Prompt 内容");
    await user.type(editor, "请区分事实与推测。");
    await user.click(screen.getByRole("button", { name: "创建并生效" }));
    expect(
      await screen.findByText(/新修订已生效，只影响后续认知/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "停用" }));
    expect(
      await screen.findByText(/历史认知仍保留原 revision/),
    ).toBeInTheDocument();

    expect(bodies).toEqual([
      {
        expected_revision_id: null,
        content: "请区分事实与推测。",
      },
      {
        expected_revision_id: FIRST_REVISION,
      },
    ]);
    await waitFor(() => expect(screen.getByText("已停用")).toBeInTheDocument());
  });

  it("requires a refetch after a stale revision conflict", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse(
          promptResponse({
            current_revision_id: FIRST_REVISION,
            revision_no: 1,
            revision_kind: "created",
            content: "旧内容",
            activated_at: "2026-08-06T10:00:00.000000Z",
          }),
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel();

    const editor = await screen.findByLabelText("Creator Prompt 内容");
    await user.clear(editor);
    await user.type(editor, "新内容");
    await user.click(screen.getByRole("button", { name: "提交新修订" }));

    expect(await screen.findByText(/请重新读取后再提交/)).toBeInTheDocument();
  });
});
