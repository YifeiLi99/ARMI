import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { SceneSelector } from "./SceneSelector";

const SCENE_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7";

function scene(sceneKey: string, status: "open" | "closed", isDefault = false) {
  const suffix =
    sceneKey === "default" ? "7" : sceneKey === "night-talk" ? "8" : "9";
  return {
    projection_kind: "creator-scenes",
    scene_id: `018f47a6-7b2d-7c35-8b18-684e38ab6ef${suffix}`,
    scene_key: sceneKey,
    status,
    opened_at: "2026-08-06T09:00:00.000000Z",
    ...(status === "closed"
      ? { closed_at: "2026-08-06T10:00:00.000000Z" }
      : {}),
    is_default: isDefault,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it.each([
  ["create", "response"],
  ["transition", "response"],
  ["create", "refresh"],
  ["transition", "refresh"],
])(
  "does not select a scene when unmounted during %s %s",
  async (operation, stage) => {
    let settle!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      settle = resolve;
    });
    const result = scene(
      operation === "create" ? "ideas" : "night-talk",
      "open",
    );
    let reads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (_input, init) => {
        if (init?.method === "POST") {
          return stage === "response" ? pending : Response.json(result);
        }
        reads += 1;
        if (reads > 1 && stage === "refresh") return pending;
        return Response.json({
          projection_kind: "creator-scenes",
          scenes: [
            scene("default", "open", true),
            scene("night-talk", "closed"),
          ],
        });
      }),
    );
    const onSelected = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const user = userEvent.setup();
    const panel = render(
      <QueryClientProvider client={queryClient}>
        <SceneSelector
          token="token"
          environmentId={SCENE_ID}
          creatorPartyId={SCENE_ID}
          selectedSceneKey="night-talk"
          onSelected={onSelected}
          onUnauthorized={vi.fn()}
        />
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "管理场合" }));
    await screen.findByRole("button", { name: "重新打开" });
    if (operation === "create") {
      await user.type(screen.getByLabelText("新场合标识"), "ideas");
      await user.click(screen.getByRole("button", { name: "建立场合" }));
    } else {
      await user.click(screen.getByRole("button", { name: "重新打开" }));
    }
    if (stage === "refresh") await waitFor(() => expect(reads).toBe(2));
    const mutation = queryClient.getMutationCache().getAll()[0];
    expect(mutation?.state.status).toBe("pending");
    panel.unmount();
    queryClient.clear();
    await act(async () => {
      settle(Response.json(result));
    });
    await waitFor(() => expect(mutation?.state.status).toBe("success"));
    expect(onSelected).not.toHaveBeenCalled();
  },
);

it("loads, selects, reopens and creates stable Creator scenes", async () => {
  const selected = vi.fn();
  const scenes = [
    scene("default", "open", true),
    scene("night-talk", "closed"),
  ];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/v1/scenes" && init?.method === "POST") {
      const created = scene("ideas", "open");
      scenes.push(created);
      return Response.json(created, { status: 201 });
    }
    if (url === "/v1/scenes/night-talk/reopen" && init?.method === "POST") {
      scenes[1] = scene("night-talk", "open");
      return Response.json(scenes[1]);
    }
    if (url === "/v1/scenes") {
      return Response.json({
        projection_kind: "creator-scenes",
        scenes,
      });
    }
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <SceneSelector
        token="token"
        environmentId={SCENE_ID}
        creatorPartyId={SCENE_ID}
        selectedSceneKey="default"
        onSelected={selected}
        onUnauthorized={() => undefined}
      />
    </QueryClientProvider>,
  );

  await user.click(screen.getByRole("button", { name: "管理场合" }));
  await user.selectOptions(await screen.findByLabelText("场合"), "night-talk");
  expect(selected).toHaveBeenLastCalledWith("night-talk", "closed");

  cleanup();
  render(
    <QueryClientProvider client={queryClient}>
      <SceneSelector
        token="token"
        environmentId={SCENE_ID}
        creatorPartyId={SCENE_ID}
        selectedSceneKey="night-talk"
        onSelected={selected}
        onUnauthorized={() => undefined}
      />
    </QueryClientProvider>,
  );
  await user.click(screen.getByRole("button", { name: "管理场合" }));
  await user.click(await screen.findByRole("button", { name: "重新打开" }));
  await waitFor(() =>
    expect(selected).toHaveBeenLastCalledWith("night-talk", "open"),
  );

  await user.type(screen.getByLabelText("新场合标识"), "ideas");
  await user.click(screen.getByRole("button", { name: "建立场合" }));
  await waitFor(() =>
    expect(selected).toHaveBeenLastCalledWith("ideas", "open"),
  );
});

it.each([401, 503])("handles a %s when reading scenes", async (status) => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () =>
      Response.json(
        { status: "rejected", error: { code: "CREATOR-READ-FAILED" } },
        { status },
      ),
    ),
  );
  const onUnauthorized = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <SceneSelector
        token="token"
        environmentId={SCENE_ID}
        creatorPartyId={SCENE_ID}
        selectedSceneKey="default"
        onSelected={vi.fn()}
        onUnauthorized={onUnauthorized}
      />
    </QueryClientProvider>,
  );

  await user.click(screen.getByRole("button", { name: "管理场合" }));
  await screen.findByText("当前无法读取 Creator 场合。");
  expect(onUnauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
});
