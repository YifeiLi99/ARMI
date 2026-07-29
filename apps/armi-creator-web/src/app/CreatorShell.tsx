export function CreatorShell() {
  return (
    <main className="creator-shell">
      <section className="status-card" aria-labelledby="creator-title">
        <p className="eyebrow">本机静态界面</p>
        <h1 id="creator-title">ARMI Creator</h1>
        <div className="runtime-status" role="status" aria-live="polite">
          <span className="status-marker" aria-hidden="true" />
          Runtime 尚未连接
        </div>
        <p className="boundary-note">
          当前页面只证明 Creator 静态构建链成立，不表示
          Runtime、主体资料或业务能力可用。
        </p>
      </section>
    </main>
  );
}
