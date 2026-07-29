import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CreatorShell } from "./CreatorShell";

describe("Creator static shell", () => {
  it("renders the honest disconnected state without future controls", () => {
    render(<CreatorShell />);

    expect(
      screen.getByRole("heading", { level: 1, name: "ARMI Creator" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Runtime 尚未连接");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("does not perform network activity", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<CreatorShell />);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
