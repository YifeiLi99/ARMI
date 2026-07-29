import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CreatorShell } from "./app/CreatorShell";
import "./styles/global.css";

const root = document.getElementById("root");
if (root !== null) {
  createRoot(root).render(
    <StrictMode>
      <CreatorShell />
    </StrictMode>,
  );
}
