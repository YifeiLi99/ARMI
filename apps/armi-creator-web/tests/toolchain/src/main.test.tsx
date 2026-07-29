import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ToolchainProbe } from "./main";

describe("Creator toolchain conformance", () => {
  it("renders React TSX in jsdom", () => {
    render(<ToolchainProbe />);
    expect(screen.getByText("toolchain-conformance")).toBeInTheDocument();
  });
});
