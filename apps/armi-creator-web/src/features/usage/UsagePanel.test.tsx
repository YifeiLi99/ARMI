import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { UsagePanel, money, usageRange } from "./UsagePanel";

const totals = {
  billable_calls: 0,
  auxiliary_requests: 0,
  known_microyuan: null,
  incomplete_calls: 0,
  usage_unconfirmed_calls: 0,
  unpriced_calls: 0,
  historical_incomplete_calls: 0,
};
function response(value: object, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function show() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <UsagePanel
        token="test-session"
        onUnauthorized={vi.fn()}
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
