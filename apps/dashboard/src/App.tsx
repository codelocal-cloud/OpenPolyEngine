import { useCallback, useEffect, useMemo, useState } from "react";

type Market = {
  slug: string;
  market_id: string;
  slot_start: string;
  slot_end: string;
  fetched_at: string;
  price_up: string | null;
  price_down: string | null;
  token_up: string;
  token_down: string;
  active: boolean;
  closed: boolean;
  accepting_orders: boolean;
  resolution_source: string | null;
  price_kind: string;
  data_source: string;
};

type MarketResponse = {
  mode: string;
  markets: Market[];
  count: number;
};

type Book = {
  book: { best_bid: string | null; best_ask: string | null; outcome: string };
  received_at: string;
  stale: boolean;
  age_seconds: number;
};
type BookResponse = {
  mode: "READ_ONLY";
  slug: string;
  books: { UP: Book | null; DOWN: Book | null };
};

type PaperPosition = {
  slug: string; outcome: "UP" | "DOWN"; token_id: string; quantity: string;
  cost_basis: string; source: string; created_at: string;
};
type PaperOrder = {
  order_id: string; side: "BUY" | "SELL"; outcome: "UP" | "DOWN"; slug: string;
  quantity: string; price: string; notional: string; fee: string;
  cash_delta: string; realized_pnl: string | null; source: string;
  executed_at: string;
};
type PaperState = {
  mode: "PAPER_ONLY"; account: "demo" | "clob"; cash_balance: string;
  starting_cash: string; realized_pnl: string; fee_rate_assumed: string;
  valuation_status: string; positions: PaperPosition[]; orders: PaperOrder[];
};
type PaperQuote = {
  slug: string; outcome: "UP" | "DOWN"; best_bid: string; best_ask: string;
  bid_size: string; ask_size: string; source: string; mode: "PAPER_ONLY";
};
type HealthResponse = {
  status: string;
  mode: string;
  trading_enabled: boolean;
};

type Filter = "all" | "real" | "demo";
const API = "http://127.0.0.1:8787";
const NO_LIVE_TRADING = true;

function fmtTime(raw: string): string {
  const date = new Date(raw);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
function fmtPrice(raw: string | null): string {
  if (raw === null || !Number.isFinite(Number(raw))) return "—";
  return `${(Number(raw) * 100).toFixed(1)}¢`;
}
function labelSource(m: Market): string {
  return m.data_source === "offline_fixture" ? "DỮ LIỆU MẪU" : "GAMMA API";
}
function liveMarketState(m: Market, now: number): string {
  const start = Date.parse(m.slot_start);
  const end = Date.parse(m.slot_end);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "KHÔNG XÁC ĐỊNH";
  if (now >= end || m.closed) return "ĐÃ KẾT THÚC";
  if (now < start) return "SẮP DIỄN RA";
  return m.active && m.accepting_orders ? "ĐANG DIỄN RA" : "KHÔNG NHẬN LỆNH";
}
function shortToken(token: string): string {
  return token.length > 18 ? `${token.slice(0, 9)}…${token.slice(-6)}` : token;
}

export default function App() {
  const [items, setItems] = useState<Market[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [apiOk, setApiOk] = useState(false);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const [orderbook, setOrderbook] = useState<BookResponse | null>(null);
  const [paperAccount, setPaperAccount] = useState<"demo" | "clob">("demo");
  const [paper, setPaper] = useState<PaperState | null>(null);
  const [paperQuotes, setPaperQuotes] = useState<PaperQuote[]>([]);
  const [paperStake, setPaperStake] = useState("10");
  const [paperBusy, setPaperBusy] = useState(false);
  const [paperNotice, setPaperNotice] = useState("");
  const [paperError, setPaperError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [healthRes, marketsRes] = await Promise.all([
        fetch(`${API}/health`, { cache: "no-store" }),
        fetch(`${API}/api/markets?limit=50`, { cache: "no-store" })
      ]);
      if (!healthRes.ok || !marketsRes.ok) throw new Error("API không phản hồi thành công");
      const health: HealthResponse = await healthRes.json();
      const data: MarketResponse = await marketsRes.json();
      if (
        health.status !== "ok" ||
        health.mode !== "READ_ONLY" ||
        health.trading_enabled !== false ||
        data.mode !== "READ_ONLY" ||
        !Array.isArray(data.markets)
      ) throw new Error("API trả về trạng thái khác READ_ONLY; tạm ngừng hiển thị");
      setItems(data.markets);
      try {
        const paperRes = await fetch(`${API}/api/paper/state?account=${paperAccount}`, { cache: "no-store" });
        if (paperRes.ok) {
          const nextPaper: PaperState = await paperRes.json();
          setPaper(nextPaper.mode === "PAPER_ONLY" ? nextPaper : null);
        } else setPaper(null);
        const quotes = await Promise.all((["UP", "DOWN"] as const).map(async outcome => {
          const response = await fetch(`${API}/api/paper/quote?account=${paperAccount}&outcome=${outcome}`,
            { cache: "no-store" });
          return response.ok ? await response.json() as PaperQuote : null;
        }));
        setPaperQuotes(quotes.filter((v): v is PaperQuote => v !== null && v.mode === "PAPER_ONLY"));
      } catch {
        setPaper(null);
        setPaperQuotes([]);
      }
      const latest = data.markets
        .filter(m => m.data_source === "gamma_public")
        .sort((a,b) => Date.parse(b.fetched_at) - Date.parse(a.fetched_at))[0];
      if (latest) {
        try {
          const bookRes = await fetch(`${API}/api/orderbooks?slug=${encodeURIComponent(latest.slug)}`,
            { cache: "no-store" });
          if (bookRes.ok) {
            const books: BookResponse = await bookRes.json();
            setOrderbook(books.mode === "READ_ONLY" && books.slug === latest.slug ? books : null);
          } else {
            setOrderbook(null);
          }
        } catch {
          setOrderbook(null);
        }
      } else {
        setOrderbook(null);
      }
      setApiOk(true);
      setLastSync(Date.now());
      setError("");
    } catch (err) {
      setOrderbook(null);
      setApiOk(false);
      setPaper(null);
      setPaperQuotes([]);
      setError(err instanceof Error ? err.message : "Không thể kết nối API");
    } finally {
      setLoading(false);
    }
  }, [paperAccount]);

  const placePaper = async (side: "BUY" | "SELL", outcome: "UP" | "DOWN", slug?: string) => {
    if (paperBusy) return;
    setPaperBusy(true);
    setPaperError("");
    setPaperNotice("");
    try {
      const quote = paperQuotes.find(v => v.outcome === outcome);
      const request = {
        request_id: crypto.randomUUID(), side, outcome,
        ...(side === "BUY" ? {spend_usd: paperStake} : {}),
        slug: slug ?? quote?.slug,
      };
      const response = await fetch(`${API}/api/paper/orders?account=${paperAccount}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-OpenPoly-Paper": "1" },
        body: JSON.stringify(request),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.reason ?? result.error ?? "Paper order failed");
      setPaperNotice(`${side} ${outcome} đã ghi sổ (${result.source === "synthetic_demo" ? "DEMO giả lập" : "CLOB paper"}); giá ${fmtPrice(result.price)}, phí giả định ${result.fee} USD.`);
      await refresh();
    } catch (err) {
      setPaperError(err instanceof Error ? err.message : "Không ghi được lệnh ảo");
    } finally {
      setPaperBusy(false);
    }
  };

  useEffect(() => {
    void refresh();
    const refreshTimer = window.setInterval(() => void refresh(), 12_000);
    const clockTimer = window.setInterval(() => setClock(Date.now()), 1_000);
    return () => { window.clearInterval(refreshTimer); window.clearInterval(clockTimer); };
  }, [refresh]);

  const realMarkets = items.filter(m => m.data_source === "gamma_public");
  const demoMarkets = items.filter(m => m.data_source === "offline_fixture");
  const filtered = useMemo(() => {
    const source = filter === "real" ? realMarkets : filter === "demo" ? demoMarkets : items;
    return [...source].sort((a, b) => Date.parse(b.slot_start) - Date.parse(a.slot_start));
  }, [filter, realMarkets, demoMarkets, items]);
  const latestReal = [...realMarkets].sort((a,b) => Date.parse(b.fetched_at)-Date.parse(a.fetched_at))[0];
  const selected = filter === "all" && latestReal
    ? latestReal
    : [...filtered].sort((a,b) => Date.parse(b.fetched_at)-Date.parse(a.fetched_at))[0];
  const ageSeconds = latestReal ? Math.max(0, Math.floor((clock - Date.parse(latestReal.fetched_at))/1000)) : null;
  const feedFresh = ageSeconds !== null && ageSeconds < 30;
  const minutesToEnd = selected ? Math.max(0, Math.floor((Date.parse(selected.slot_end)-clock)/1000)) : null;
  const completion = selected
    ? Math.min(100, Math.max(0, ((clock - Date.parse(selected.slot_start))/300_000)*100))
    : 0;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-emblem">◈</div>
          <div className="brand-names">
            <strong>OpenPoly<span>Engine</span></strong>
            <small>TRADING RESEARCH OS</small>
          </div>
        </div>
        <div className="side-heading">WORKSPACE</div>
        <div className="nav-link current"><span className="nav-icon">▦</span> Tổng quan thị trường</div>
        <div className="nav-link soon"><span className="nav-icon">◌</span> Backtesting <span className="soon-badge">SOON</span></div>
        <div className="nav-link soon"><span className="nav-icon">⌁</span> AI Strategies <span className="soon-badge">SOON</span></div>
        <a className="nav-link current" href="#paper-trading"><span className="nav-icon">◫</span> Paper Trading <span className="soon-badge">DEMO</span></a>
        <div className="side-footer">
          <div className="protected">◉ SECURE RESEARCH MODE</div>
          <p>Hệ thống chỉ đọc dữ liệu. Không kết nối ví và không gửi lệnh giao dịch.</p>
          <div className="sidebar-version">VERSION 0.2.0 • LOCALHOST</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="breadcrumb">DASHBOARD <span>/</span> POLYMARKET <span>/</span> BTC 5M</div>
            <h1>Market Overview <span className="title-dot">.</span></h1>
            <p>Theo dõi thị trường BTC Up / Down khung 5 phút</p>
          </div>
          <div className="header-right">
            <div className="connection">
              <span className={apiOk ? "connection-dot connected" : "connection-dot"} />
              <span>{apiOk ? "Local API Online" : "API Offline"}</span>
            </div>
            <button className="refresh-button" onClick={() => void refresh()} disabled={loading} type="button">
              <span aria-hidden="true">↻</span> {loading ? "Đang tải..." : "Làm mới"}
            </button>
          </div>
        </header>

        <div className="security-bar">
          <span className="security-icon">🔒</span>
          <div><strong>NO LIVE ORDERS / PAPER TRADING ONLY</strong><small>Lệnh mua/bán chỉ ghi PostgreSQL bằng USD ảo. Không kết nối ví hoặc gửi lệnh Polymarket.</small></div>
          <span className="security-mode">{NO_LIVE_TRADING ? "SAFE MODE" : "UNEXPECTED MODE"}</span>
        </div>

        {error && <div className="error-card" role="alert">
          <strong>Không thể truy cập backend:</strong> {error}. Kiểm tra API tại <code>127.0.0.1:8787</code>.
        </div>}
        {!error && realMarkets.length > 0 && !feedFresh && <div className="warning-card" role="status">
          ⚠ Dữ liệu Gamma gần nhất đã cũ ({ageSeconds === null ? "không rõ" : `${ageSeconds} giây`}). Đây không phải báo giá realtime; tuyệt đối không sử dụng để ra quyết định giao dịch.
        </div>}
        {!error && realMarkets.length === 0 && <div className="warning-card">Không có dữ liệu Gamma thực trong database. Dữ liệu mẫu được gắn nhãn riêng, không phải giá thị trường.</div>}

        <div className="summary-cards">
          <div className="metric-card highlight">
            <div className="metric-top"><span>THỊ TRƯỜNG</span><span className="tag tag-indigo">BTC / 5 MIN</span></div>
            <div className="metric-value">UP / DOWN</div>
            <div className="metric-bottom">Polymarket Prediction Market</div>
          </div>
          <div className="metric-card">
            <div className="metric-top"><span>SNAPSHOT GAMMA</span><span className="mono">◉</span></div>
            <div className="metric-value">{realMarkets.length}<small> thị trường</small></div>
            <div className="metric-bottom">Đã lưu trong TimescaleDB</div>
          </div>
          <div className="metric-card">
            <div className="metric-top"><span>DỮ LIỆU MẪU</span><span className="mono">◇</span></div>
            <div className="metric-value">{demoMarkets.length}<small> bản ghi</small></div>
            <div className="metric-bottom">Fixture dùng cho kiểm thử</div>
          </div>
          <div className="metric-card">
            <div className="metric-top"><span>ĐỘ MỚI FEED</span><span className={feedFresh ? "tag tag-green" : "tag tag-amber"}>{feedFresh ? "FRESH" : "STALE"}</span></div>
            <div className="metric-value">{ageSeconds === null ? "—" : `${ageSeconds}s`}</div>
            <div className="metric-bottom">Kể từ snapshot Gamma gần nhất</div>
          </div>
        </div>

        <div className="content-grid">
          <section className="panel current-market">
            <div className="panel-heading"><div><div className="eyebrow">LATEST SAVED OBSERVATION</div><h2>BTC 5m Snapshot</h2></div>
              {selected && <span className={selected.data_source === "gamma_public" ? "tag tag-indigo" : "tag tag-amber"}>{labelSource(selected)}</span>}
            </div>
            {selected ? <>
              <div className="market-clock"><span>{fmtTime(selected.slot_start)}</span><span className="clock-separator">—</span><span>{fmtTime(selected.slot_end)}</span><span className="status-text">{liveMarketState(selected, clock)}</span></div>
              <div className="progress-track"><div className="progress-fill" style={{width: `${completion}%`}}/></div>
              <div className="market-timer">Thời gian còn lại: <strong>{minutesToEnd !== null ? `${Math.floor(minutesToEnd/60)}m ${String(minutesToEnd%60).padStart(2,"0")}s` : "—"}</strong></div>
              <div className="price-columns">
                <div className="price-box up"><span>▲ UP · GIÁ THAM KHẢO</span><strong>{fmtPrice(selected.price_up)}</strong><small>Gamma metadata — không phải giá đặt lệnh</small></div>
                <div className="price-box down"><span>▼ DOWN · GIÁ THAM KHẢO</span><strong>{fmtPrice(selected.price_down)}</strong><small>Gamma metadata — không phải giá đặt lệnh</small></div>
              </div>
            </> : <div className="empty-state">Chưa có dữ liệu. Hãy chạy scanner đọc-only để thu thập snapshot.</div>}
          </section>

          <section className="panel system-panel">
            <div className="panel-heading"><div><div className="eyebrow">ENGINE HEALTH</div><h2>Trạng thái hệ thống</h2></div><span className={apiOk ? "tag tag-green" : "tag tag-amber"}>{apiOk ? "RUNNING" : "OFFLINE"}</span></div>
            <div className="health-line"><span>Market API</span><strong className={apiOk ? "green" : "amber"}>{apiOk ? "● Connected" : "● Disconnected"}</strong></div>
            <div className="health-line"><span>Trading Engine</span><strong>● Disabled</strong></div>
            <div className="health-line"><span>Execution Mode</span><strong>READ_ONLY</strong></div>
            <div className="health-line"><span>Wallet / Signing</span><strong>Not configured</strong></div>
            <div className="health-line"><span>Persisted snapshots</span><strong>{items.length}</strong></div>
            <div className="health-line"><span>Lần làm mới</span><strong>{lastSync ? fmtTime(new Date(lastSync).toISOString()) : "—"}</strong></div>
            <div className="information-box"><div className="info-heading">Thông tin quan trọng</div><p>API chỉ xác nhận truy cập PostgreSQL khi đọc thành công. Giao diện chưa xác minh riêng trạng thái Redis hoặc kết nối WebSocket.</p></div>
          </section>
        </div>

        <section className="panel realtime-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">CLOB L2 · PUBLIC WEBSOCKET</div><h2>Order Book — Best Bid / Ask</h2></div>
            <span className="tag tag-indigo">SNAPSHOT ONLY</span>
          </div>
          <p className="realtime-caption">
            Hiển thị bid/ask lấy từ snapshot order book đầy đủ đã lưu trong TimescaleDB.
            Không dùng thay thế sổ lệnh realtime nếu feed mất kết nối.
          </p>
          <div className="book-cards">
            {(["UP","DOWN"] as const).map(outcome => {
              const item = orderbook?.books[outcome] ?? null;
              const age = item ? (clock - Date.parse(item.received_at)) / 1000 : Infinity;
              const stale = !item || item.stale || age > 20;
              return <div className="book-card" key={outcome}>
                <div className="book-card-top"><strong>{outcome === "UP" ? "▲ UP" : "▼ DOWN"}</strong>
                  <span className={stale ? "tag tag-amber" : "tag tag-green"}>{stale ? "CHƯA CÓ / STALE" : "FRESH"}</span></div>
                <div className="book-data">
                  <div><span>BEST BID</span><strong>{item ? fmtPrice(item.book.best_bid) : "—"}</strong></div>
                  <div><span>BEST ASK</span><strong>{item ? fmtPrice(item.book.best_ask) : "—"}</strong></div>
                </div>
                <small>{item ? `Nhận lúc ${fmtTime(item.received_at)} · ${Math.max(0,Math.round(age))}s trước` : "Đang chờ snapshot book thật từ CLOB"}</small>
              </div>;
            })}
          </div>
        </section>

        <section className="panel paper-panel" id="paper-trading">
          <div className="panel-heading">
            <div><div className="eyebrow">VIRTUAL CASH ONLY · LOCAL POSTGRES</div><h2>Paper Trading Simulator</h2></div>
            <span className="tag tag-green">PAPER ONLY</span>
          </div>
          <div className="paper-switch" role="group" aria-label="Chế độ tài khoản ảo">
            <button type="button" aria-pressed={paperAccount === "demo"}
              className={paperAccount === "demo" ? "active" : ""}
              onClick={() => {setPaperAccount("demo");setPaperNotice("");setPaperError("");}}>
              Demo offline (giá giả lập)
            </button>
            <button type="button" aria-pressed={paperAccount === "clob"}
              className={paperAccount === "clob" ? "active" : ""}
              onClick={() => {setPaperAccount("clob");setPaperNotice("");setPaperError("");}}>
              CLOB Paper (order book thật)
            </button>
          </div>
          <p className="paper-caption">
            {paperAccount === "demo"
              ? "DEMO: BID 48¢ / ASK 52¢ cố định cho cả UP và DOWN; không phản ánh bất kỳ thị trường hoặc lợi nhuận thực nào."
              : "CLOB: chỉ mô phỏng khớp lệnh từ snapshot order book thật dưới 10 giây, không khớp nếu feed chậm/thiếu."}
            {" "}Phí 0,5% là giả định để test, không phải phí chính thức của Polymarket.
          </p>
          <div className="paper-metrics">
            <div><span>TIỀN MẶT ẢO</span><strong>{paper ? Number(paper.cash_balance).toFixed(2) : "—"} USD</strong></div>
            <div><span>ĐANG ĐẦU TƯ (GIÁ VỐN)</span><strong>{paper ? paper.positions.reduce((s,p)=>s+Number(p.cost_basis),0).toFixed(2) : "—"} USD</strong></div>
            <div><span>P&L ĐÃ ĐÓNG</span><strong>{paper ? Number(paper.realized_pnl).toFixed(2) : "—"} USD</strong></div>
          </div>
          <div className="paper-trade-controls">
            <label htmlFor="paper-stake">Ngân sách mỗi lệnh (USD ảo)</label>
            <input id="paper-stake" aria-label="Ngân sách mỗi lệnh (USD ảo)" inputMode="decimal"
              value={paperStake} onChange={e=>setPaperStake(e.target.value)}
              placeholder="10" type="number" min="1" max="50" step="1"/>
            <span>Giới hạn 1–50 USD/lệnh; tổng vốn mở tối đa 250 USD.</span>
          </div>
          <div className="paper-trade-buttons">
            {(["UP", "DOWN"] as const).map(outcome => {
              const quote = paperQuotes.find(q => q.outcome === outcome);
              return <button key={outcome} type="button" disabled={paperBusy || !paper || !quote}
                className={outcome === "UP" ? "paper-buy-up" : "paper-buy-down"}
                onClick={()=>void placePaper("BUY",outcome)}>
                {paperBusy ? "Đang ghi lệnh..." : `BUY ${outcome} · ${quote ? fmtPrice(quote.best_ask) : "Không có quote"}`}
              </button>;
            })}
          </div>
          {paperNotice && <div className="paper-notice" role="status">{paperNotice}</div>}
          {paperError && <div className="paper-error" role="alert">{paperError}</div>}
          <div className="paper-holdings">
            <h3>Vị thế ảo đang giữ <span className="count-badge">{paper?.positions.length ?? 0}</span></h3>
            {paper && paper.positions.length === 0 && <p className="paper-empty">Chưa có vị thế. Bạn có thể thử mua bằng tiền ảo ở trên.</p>}
            {paper?.positions.map(position => <div className="paper-position" key={position.slug + position.outcome}>
              <div><strong>{position.outcome} · {position.quantity} shares</strong>
                <small>{position.slug} · Giá vốn {Number(position.cost_basis).toFixed(2)} USD</small></div>
              <button disabled={paperBusy || (paperAccount === "clob" && !paperQuotes.some(q => q.slug === position.slug && q.outcome === position.outcome))}
                type="button" onClick={() => void placePaper("SELL", position.outcome, position.slug)}>SELL ALL (ảo)</button>
            </div>)}
            <h3>Lịch sử lệnh ảo</h3>
            <div className="paper-history">
              {paper?.orders.slice(0,10).map(order => <div className="paper-history-row" key={order.order_id}>
                <span><strong>{order.side} {order.outcome}</strong> · {Number(order.quantity).toFixed(3)} shares
                  <small>{fmtTime(order.executed_at)} · {order.source === "synthetic_demo" ? "DEMO" : "CLOB"}</small></span>
                <span className={order.cash_delta.startsWith("-") ? "red" : "green"}>
                  {Number(order.cash_delta).toFixed(2)} USD
                  {order.realized_pnl !== null && <small>P&L {Number(order.realized_pnl).toFixed(2)} USD</small>}
                </span>
              </div>)}
              {(!paper || paper.orders.length === 0) && <p className="paper-empty">Chưa có lệnh ảo nào.</p>}
            </div>
            <p className="paper-disclaimer">Không định giá P&L chưa đóng, không tự thanh toán kết quả UP/DOWN khi đáo hạn; cần oracle xác minh riêng. Chức năng này không thể gửi lệnh thật.</p>
          </div>
        </section>

        <section className="panel table-panel">
          <div className="table-toolbar">
            <div><div className="eyebrow">PERSISTED MARKET DATA</div><h2>Lịch sử snapshot <span className="count-badge">{filtered.length}</span></h2></div>
            <div className="filter-buttons" role="group" aria-label="Lọc theo nguồn dữ liệu">
              <button type="button" aria-pressed={filter === "all"} className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>Tất cả</button>
              <button type="button" aria-pressed={filter === "real"} className={filter === "real" ? "active" : ""} onClick={() => setFilter("real")}>Gamma thật</button>
              <button type="button" aria-pressed={filter === "demo"} className={filter === "demo" ? "active" : ""} onClick={() => setFilter("demo")}>Dữ liệu mẫu</button>
            </div>
          </div>
          <div className="table-scroll"><table><thead><tr><th>THỜI GIAN (LOCAL)</th><th>TRẠNG THÁI</th><th>UP</th><th>DOWN</th><th>NGUỒN</th><th>THU THẬP LÚC</th><th>TOKEN UP</th></tr></thead>
            <tbody>{filtered.map((m) => <tr key={m.slug}>
              <td><strong>{fmtTime(m.slot_start)}</strong> <span className="table-muted">→ {fmtTime(m.slot_end)}</span></td>
              <td><span className="row-status">{liveMarketState(m, clock)}</span></td>
              <td className="green number">{fmtPrice(m.price_up)}</td>
              <td className="red number">{fmtPrice(m.price_down)}</td>
              <td><span className={m.data_source === "gamma_public" ? "source-real" : "source-demo"}>{labelSource(m)}</span></td>
              <td className="table-muted">{fmtTime(m.fetched_at)}</td>
              <td className="table-muted mono">{shortToken(m.token_up)}</td>
            </tr>)}
            {filtered.length === 0 && <tr><td colSpan={7} className="empty-row">Chưa có bản ghi phù hợp.</td></tr>}
            </tbody>
          </table></div>
          <div className="table-footnote">* Các mức giá lấy từ Gamma event metadata. Không phải best bid / best ask và không phản ánh xác suất thắng đã được kiểm định.</div>
        </section>
        <footer>OpenPolyEngine v0.2.0 <span>•</span> Local research environment <span>•</span> Not financial advice <span>•</span> No live order execution</footer>
      </main>
    </div>
  );
}
