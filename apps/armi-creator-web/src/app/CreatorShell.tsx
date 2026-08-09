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
        <section className="creator-entry" aria-labelledby="creator-title">
          <div className="entry-brand">
            <div className="entry-mark" aria-hidden="true">
              A
            </div>
            <div>
              <p className="eyebrow">本机 Creator 工作台</p>
              <h1 id="creator-title">ARMI Creator</h1>
            </div>
          </div>
          <SessionPanel />
        </section>
      </main>
    </QueryClientProvider>
  );
}
