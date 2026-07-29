import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

export function ToolchainProbe() {
  return <p>toolchain-conformance</p>;
}

const root = document.getElementById("root");
if (root !== null) {
  createRoot(root).render(
    <StrictMode>
      <ToolchainProbe />
    </StrictMode>,
  );
}
