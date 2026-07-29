export function CreatorShell() {
  return (
    <main className="creator-shell">
      <section className="status-card" aria-labelledby="creator-title">
        <p className="eyebrow">本机 Runtime 钢架</p>
        <h1 id="creator-title">ARMI Creator</h1>
        <div className="runtime-status" role="status" aria-live="polite">
          <span className="status-marker" aria-hidden="true" />
          Runtime 钢架已启动，业务尚未就绪
        </div>
        <p className="boundary-note">
          当前页面只证明 Creator 静态制品由本机 Runtime
          提供，不表示主体资料、会话或业务能力可用。
        </p>
      </section>
    </main>
  );
}
