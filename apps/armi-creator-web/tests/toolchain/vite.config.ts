import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const fixtureRoot = fileURLToPath(new URL(".", import.meta.url));
const outputRoot = fileURLToPath(
  new URL("../../../../.tmp/quality/creator-dist/", import.meta.url),
);

export default defineConfig({
  root: fixtureRoot,
  plugins: [react()],
  build: {
    emptyOutDir: true,
    outDir: outputRoot,
    sourcemap: false,
  },
});
