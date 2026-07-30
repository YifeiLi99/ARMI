import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { SessionPanel } from "../features/session/SessionPanel";

export function CreatorShell() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, staleTime: 0 } },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <main className="creator-shell">
        <section className="status-card" aria-labelledby="creator-title">
          <p className="eyebrow">安全 Loopback 入口</p>
          <h1 id="creator-title">ARMI Creator</h1>
          <SessionPanel />
        </section>
      </main>
    </QueryClientProvider>
  );
}
