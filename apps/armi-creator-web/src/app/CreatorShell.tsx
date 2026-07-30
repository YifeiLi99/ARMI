import { SessionPanel } from "../features/session/SessionPanel";

export function CreatorShell() {
  return (
    <main className="creator-shell">
      <section className="status-card" aria-labelledby="creator-title">
        <p className="eyebrow">安全 Loopback 入口</p>
        <h1 id="creator-title">ARMI Creator</h1>
        <SessionPanel />
      </section>
    </main>
  );
}
