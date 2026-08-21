import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QQChannelHealthCard } from "./QQChannelHealthCard";

function response(state: string, reasonCodes: string[] = []): Response {
  return new Response(
    JSON.stringify({
      contract_version: "1.0",
      projection_version: "creator-channel-health.v2",
      channel: "qq",
      driver: "napcat",
      configured: true,
      enabled: true,
      state,
      ingress_ready: state !== "disabled",
      api_reachable: state === "ready" || state === "login_required",
      account_online: state === "ready",
      account_matches: state === "ready",
      webui_url: "http://127.0.0.1:6099/webui/",
      observed_at: "2026-08-14T08:00:00.000000Z",
      reason_codes: reasonCodes,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function renderCard(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <QQChannelHealthCard
        token="browser-token"
        onUnauthorized={() => undefined}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("QQ channel health card", () => {
  it.each([
    ["disabled", "未启用"],
    ["starting", "正在启动"],
    ["login_required", "等待 QQ 登录"],
    ["ready", "可用"],
    ["unavailable", "暂不可用"],
    ["misconfigured", "配置不一致"],
  ])("renders %s without exposing account details", async (state, label) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(state)),
    );
    renderCard();
    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.queryByText(/QQ号|昵称|token/i)).not.toBeInTheDocument();
  });

  it("explains stable reasons and supports manual refresh", async () => {
    const fetchMock = vi.fn(async () =>
      response("login_required", ["NAPCAT_LOGIN_REQUIRED"]),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderCard();
    expect(
      await screen.findByText("需要在 QQ 窗口完成登录或扫码。"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "刷新" }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("links to the local WebUI without putting its credential in the URL", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response("ready")),
    );
    renderCard();

    const link = await screen.findByRole("link", { name: "打开 NapCat" });
    expect(link).toHaveAttribute("href", "http://127.0.0.1:6099/webui/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(link.getAttribute("href")).not.toContain("token");
  });

  it("uses the switch to pause QQ admission", async () => {
    const fetchMock = vi.fn(async () => response("ready"));
    vi.stubGlobal("fetch", fetchMock);
    renderCard();

    await userEvent.click(
      await screen.findByRole("switch", { name: "QQ 渠道" }),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/v1/channels/qq/stop",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
