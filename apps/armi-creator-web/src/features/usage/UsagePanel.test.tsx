import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import type { UsageCall } from "../../api/client";
import { UsagePanel, money, usageRange } from "./UsagePanel";

const totals = {
  billable_calls: 0,
  auxiliary_requests: 0,
  known_microyuan: null,
  incomplete_calls: 0,
  usage_unconfirmed_calls: 0,
  unpriced_calls: 0,
};
function response(value: object, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function show(onUnauthorized = vi.fn()) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <UsagePanel
        token="test-session"
        onUnauthorized={onUnauthorized}
        onOperation={vi.fn()}
      />
    </QueryClientProvider>,
  );
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("keeps small amounts visible and computes periods in Beijing", () => {
  expect(money(1)).toBe("¥0.000001");
  expect(money(null)).toBe("未确认");
  expect(usageRange("month", new Date("2026-08-31T17:00:00Z"))).toEqual({
    start: "2026-09-01",
    end: "2026-09-01",
  });
  expect(usageRange("week", new Date("2026-09-06T17:00:00Z"))).toEqual({
    start: "2026-09-01",
    end: "2026-09-07",
  });
});

it("shares range and filters between summary and paginated calls", async () => {
  const requests: URL[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), "http://localhost");
      requests.push(url);
      return url.pathname.endsWith("summary")
        ? response({
            currency: "CNY",
            price_label: "official_list_price_estimate",
            timezone: "Asia/Shanghai",
            coverage: "test",
            totals: {
              ...totals,
              billable_calls: 26,
              known_microyuan: 1,
              incomplete_calls: 2,
              usage_unconfirmed_calls: 1,
              unpriced_calls: 1,
            },
            units: {},
            daily: [],
            groups: [],
          })
        : response({ total: 26, items: [] });
    }),
  );
  show();
  expect(await screen.findByText("¥0.000001")).toBeInTheDocument();
  expect(screen.getByText(/另有 2 项未完整确认/)).toBeInTheDocument();
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText("服务"), "asr");
  await screen.findByText("共 26 条 · 第 1 页");
  await user.click(screen.getByRole("button", { name: "下一页" }));
  await screen.findByText("共 26 条 · 第 2 页");
  const lastList = requests
    .filter((url) => url.pathname.endsWith("calls"))
    .at(-1)!;
  const lastSummary = requests
    .filter((url) => url.pathname.endsWith("summary"))
    .at(-1)!;
  expect(lastList.searchParams.get("offset")).toBe("25");
  for (const key of ["start", "end", "service"]) {
    expect(lastList.searchParams.get(key)).toBe(
      lastSummary.searchParams.get(key),
    );
  }
  expect(lastList.searchParams.get("service")).toBe("asr");
});

it("shows an empty range without inventing a zero price", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) =>
      String(input).includes("summary")
        ? response({
            currency: "CNY",
            price_label: "official_list_price_estimate",
            timezone: "Asia/Shanghai",
            coverage: "test",
            totals,
            units: {},
            daily: [],
            groups: [],
          })
        : response({ total: 0, items: [] }),
    ),
  );
  show();
  expect(
    await screen.findByText("所选范围暂无收费调用记录。"),
  ).toBeInTheDocument();
  expect(screen.queryByText("¥0.000000")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
});

it("distinguishes denied access from an empty result", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => response({ detail: "denied" }, 403)),
  );
  show();
  expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent(
    "没有权限读取用量记录",
  );
  expect(
    screen.queryByText("所选范围暂无收费调用记录。"),
  ).not.toBeInTheDocument();
});

it.each([200, 401, 403, 503])(
  "handles a %s response when opening and refreshing call details",
  async (status) => {
    const call: UsageCall = {
      attempt_id: "attempt-1",
      business_result: null,
      operation_id: null,
      owner: "cognition",
      reference_kind: "inference",
      reference_id: "inference-1",
      receipt: {
        schema_kind: "armi.provider-call",
        call_id: "call-1",
        billable: true,
        provider: "deepseek",
        service: "text_generation",
        model: "deepseek-flash",
        purpose: "conversation",
        started_at: "2026-10-03T01:00:00Z",
        finished_at: "2026-10-03T01:00:01Z",
        outcome: "failed",
        error_code: "PROVIDER-UNAVAILABLE",
        provider_request_id: null,
        response_model: null,
        quantities: [],
        raw_usage: null,
        price: null,
        cost: {
          status: "usage_unknown",
          known_microyuan: null,
          currency: "CNY",
          rounding: "ceil_microyuan_per_component",
          snapshot_id: null,
          components: [],
          missing_usage: ["input_tokens", "output_tokens"],
          missing_prices: [],
        },
      },
    };
    let updated = false;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === "/v1/usage/summary")
          return response({
            currency: "CNY",
            price_label: "official_list_price_estimate",
            timezone: "Asia/Shanghai",
            coverage: "test",
            totals: {
              ...totals,
              billable_calls: 1,
              incomplete_calls: 1,
              usage_unconfirmed_calls: 1,
            },
            units: {},
            daily: [],
            groups: [],
          });
        if (url.pathname === "/v1/usage/calls")
          return response({ total: 1, items: [call] });
        if (url.pathname === "/v1/usage/calls/call-1") {
          if (updated)
            return response({
              ...call,
              receipt: {
                ...call.receipt,
                provider_request_id: "provider-request-1",
              },
            });
          return status === 200
            ? response(call)
            : response({ detail: "unavailable" }, status);
        }
        throw new Error(`Unexpected request: ${url.pathname}`);
      }),
    );
    const onUnauthorized = vi.fn();
    show(onUnauthorized);
    const user = userEvent.setup();
    const detail = await screen.findByRole("button", { name: "调用详情" });
    expect(onUnauthorized).not.toHaveBeenCalled();
    await user.click(detail);
    if (status === 200)
      expect(await screen.findByText("尚未结算")).toBeInTheDocument();
    else
      expect(await screen.findByRole("alert")).toHaveTextContent(
        status === 503 ? "用量查询失败" : "没有权限读取用量记录",
      );
    expect(onUnauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
    if (status === 200 || status === 503) {
      updated = true;
      await user.click(screen.getByRole("button", { name: "刷新" }));
      expect(await screen.findByText("provider-request-1")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(detail).toHaveAttribute("aria-expanded", "true");
      expect(onUnauthorized).not.toHaveBeenCalled();
    }
  },
);
