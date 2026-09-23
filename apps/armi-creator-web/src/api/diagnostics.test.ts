import { beforeEach, expect, it, vi } from "vitest";

const send = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ sendClientDiagnostics: send }));
vi.mock("../features/session/storage", () => ({
  loadStoredSession: () => ({ token: "test-session" }),
}));

beforeEach(() => {
  vi.resetModules();
  send.mockReset();
});

it("retains technical events offline and drains only after acknowledgement", async () => {
  const { reportDiagnostic, flushDiagnostics } = await import("./diagnostics");
  reportDiagnostic({
    event: "request_failed",
    message: "Request failed",
    http_status: 503,
  });
  send.mockRejectedValueOnce(new TypeError("offline"));
  await flushDiagnostics();
  send.mockResolvedValue({ ok: true });
  await flushDiagnostics();
  expect(send).toHaveBeenCalledTimes(2);
  expect(send.mock.calls[1][1]).toEqual(send.mock.calls[0][1]);
  await flushDiagnostics();
  expect(send).toHaveBeenCalledTimes(2);
});

it("reports bounded-buffer overflow and refused submissions", async () => {
  const { reportDiagnostic, flushDiagnostics } = await import("./diagnostics");
  reportDiagnostic({
    event: "request_failed",
    message: "x".repeat(1024 * 1024),
  });
  send.mockResolvedValueOnce({ ok: false });
  await flushDiagnostics();
  send.mockResolvedValue({ ok: true });
  await flushDiagnostics();
  expect(send.mock.calls[1][1]).toEqual([
    expect.objectContaining({
      event: "buffer_status",
      dropped: 1,
      rejected: 1,
    }),
  ]);
  expect(JSON.stringify(send.mock.calls)).not.toContain("x".repeat(100));
});
