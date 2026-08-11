import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function requireRuntimeOrigin(): string {
  const origin = process.env.ARMI_CREATOR_RUNTIME_ORIGIN;
  if (origin === undefined || !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin)) {
    throw new Error(
      "ARMI_CREATOR_RUNTIME_ORIGIN must name the local Runtime origin",
    );
  }
  return origin;
}

export default defineConfig(({ command }) => {
  const runtimeOrigin =
    command === "serve" ? requireRuntimeOrigin() : undefined;
  return {
    base: "/ui/",
    plugins: [react()],
    ...(runtimeOrigin === undefined
      ? {}
      : {
          server: {
            host: "127.0.0.1",
            port: 5173,
            strictPort: true,
            proxy: {
              "/v1": {
                target: runtimeOrigin,
                changeOrigin: true,
                xfwd: false,
                configure(proxy) {
                  proxy.on("proxyReq", (proxyRequest, request) => {
                    if (MUTATING_METHODS.has(request.method ?? "")) {
                      proxyRequest.setHeader("Origin", runtimeOrigin);
                    }
                  });
                },
              },
            },
          },
        }),
    build: {
      manifest: true,
      sourcemap: false,
    },
  };
});
