import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CreatorShell } from "./app/CreatorShell";
import { installDiagnostics } from "./api/diagnostics";
import "./styles/global.css";

const root = document.getElementById("root");
installDiagnostics();
if (root !== null) {
  createRoot(root).render(
    <StrictMode>
      <CreatorShell />
    </StrictMode>,
  );
}
