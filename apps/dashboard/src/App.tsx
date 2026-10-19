import { useCallback, useEffect, useRef, useState } from "react";
import "./styles.css";

type Market = {
  slug: string; slot_start: string; slot_end: string; fetched_at: string;
  active: boolean; closed: boolean; accepting_orders: boolean; data_source: string;
};
type PaperPosition = {
  slug: string; outcome: "UP" | "DOWN"; quantity: string; cost_basis: string;
  created_at: string; source: string;
};
type PaperOrder = {
  order_id: string; side: "BUY" | "SELL"; outcome: "UP" | "DOWN";
  slug: string; quantity: string; price: string; cash_delta: string;
  realized_pnl: string | null; executed_at: string; source: string;
};
type PaperState = {
  mode: "PAPER_ONLY"; account: "clob"; cash_balance: string;
  realized_pnl: string; positions: PaperPosition[]; orders: PaperOrder[];
};
type Quote = {
  mode: "PAPER_ONLY"; source: "polymarket_clob_ws"; slug: string;
  outcome: "UP" | "DOWN"; best_bid: string; best_ask: string;
  bid_size: string; ask_size: string; received_at: string;
  fee_rate: string;
};
type Pending = {
  request_id: string; side: "BUY" | "SELL"; outcome: "UP" | "DOWN";
  slug: string; spend_usd?: string;
};
const API = "http://127.0.0.1:8787";

function currentSlug(now: number) {
  return `btc-updown-5m-${Math.floor(now / 300000) * 300}`;
}
function time(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" :
    date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", hour12: false });
}
function dollars(value: string | number) {
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function cents(value: string | null | undefined) {
  return value === null || value === undefined ? "—" : `${(Number(value) * 100).toFixed(2)}¢`;
}
async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(API + path, { cache: "no-store", signal: AbortSignal.timeout(9000) });
  if (!response.ok) throw new Error(`API HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

export default function App() {
  const [clock, setClock] = useState(Date.now());
  const [apiOnline, setApiOnline] = useState(false);
  const [market, setMarket] = useState<Market | null>(null);
  const [lastMarket, setLastMarket] = useState<Market | null>(null);
  const [paper, setPaper] = useState<PaperState | null>(null);
  const [quotes, setQuotes] = useState<Partial<Record<"UP" | "DOWN", Quote>>>({});
  const [amount, setAmount] = useState("10");
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const serial = useRef(0);
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const seq = ++serial.current;
    try {
      const [health, saved, portfolio] = await Promise.all([
        getJson<{ status: string; mode: string; trading_enabled: boolean }>("/health"),
        getJson<{ markets: Market[]; mode: string }>("/api/markets?limit=20"),
        getJson<PaperState>("/api/paper/state?account=clob"),
      ]);
      if (health.status !== "ok" || health.trading_enabled || health.mode !== "READ_ONLY" ||
          saved.mode !== "READ_ONLY" || portfolio.mode !== "PAPER_ONLY" || portfolio.account !== "clob") {
        throw new Error("API trả về chế độ không an toàn");
      }
      const real = saved.markets.filter(m => m.data_source === "gamma_public");
      const now = Date.now();
      const slug = currentSlug(now);
      const current = real.find(m => m.slug === slug) ?? null;
      const upToDate = current && (now - Date.parse(current.fetched_at)) >= 0 &&
        (now - Date.parse(current.fetched_at)) <= 45000 &&
        current.active && !current.closed && current.accepting_orders;
      const nextQuotes: Partial<Record<"UP" | "DOWN", Quote>> = {};
      if (upToDate) {
        const results = await Promise.allSettled((["UP", "DOWN"] as const).map(
          outcome => getJson<Quote>(`/api/paper/quote?account=clob&outcome=${outcome}`)
        ));
        (["UP", "DOWN"] as const).forEach((outcome, i) => {
          const result = results[i];
          if (result.status === "fulfilled" && result.value.mode === "PAPER_ONLY" &&
              result.value.source === "polymarket_clob_ws" &&
              result.value.slug === slug &&
              now - Date.parse(result.value.received_at) >= -2000 &&
              now - Date.parse(result.value.received_at) <= 10000) nextQuotes[outcome] = result.value;
        });
      }
      if (serial.current !== seq) return;
      setApiOnline(true);
      setMarket(current);
      setLastMarket(real[0] ?? null);
      setPaper(portfolio);
      setQuotes(nextQuotes);
      setError("");
    } catch (reason) {
      if (serial.current !== seq) return;
      setApiOnline(false);
      setQuotes({});
      setError(reason instanceof Error ? reason.message : "Không kết nối được API");
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void refresh();
    const sync = window.setInterval(() => { void refresh(); }, 5000);
    const ticker = window.setInterval(() => setClock(Date.now()), 1000);
    return () => { window.clearInterval(sync); window.clearInterval(ticker); serial.current++; };
  }, [refresh]);

  const sendPaper = async (request: Pending) => {
    if (busy) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const response = await fetch(API + "/api/paper/orders?account=clob", {
        method: "POST", signal: AbortSignal.timeout(10000),
        headers: { "Content-Type": "application/json", "X-OpenPoly-Paper": "1" },
        body: JSON.stringify(request),
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status < 500) {
          setPending(null);
          setError(data.reason ?? data.error ?? "Lệnh ảo bị từ chối");
          return;
        }
        throw new Error(data.error ?? "Phản hồi từ API chưa xác định");
      }
      setPending(null);
      setNotice(`${request.side} ${request.outcome} được ghi vào sổ Paper: ${cents(data.price)} · Nguồn CLOB.`);
      void refresh();
    } catch (reason) {
      setError(`Chưa xác nhận được lệnh. ${reason instanceof Error ? reason.message : "Mất kết nối"} — kiểm tra mã lệnh trước khi thử lại.`);
    } finally { setBusy(false); }
  };

  const submit = (side: "BUY" | "SELL", outcome: "UP" | "DOWN", slug?: string) => {
    if (busy || pending || !paper) return;
    const quote = quotes[outcome];
    if (!quote || (clock - Date.parse(quote.received_at)) > 10000 || quote.slug !== currentSlug(clock)) return;
    const request = {
      request_id: crypto.randomUUID(), side, outcome, slug: slug ?? quote.slug,
      ...(side === "BUY" ? { spend_usd: amount } : {}),
    };
    setPending(request);
    void sendPaper(request);
  };

  const checkPending = async () => {
    if (!pending || busy) return;
    setBusy(true);
    try {
      const data = await getJson<{ found: boolean; mode: string }>(
        `/api/paper/request?account=clob&request_id=${encodeURIComponent(pending.request_id)}`
      );
      if (data.mode !== "PAPER_ONLY") throw new Error("Chế độ phản hồi không hợp lệ");
      if (data.found) {
        setPending(null);
        setNotice("Đã tìm thấy lệnh Paper được ghi trước đó, không gửi thêm.");
        void refresh();
      } else {
        setNotice("Chưa tìm thấy lệnh; có thể thử lại cùng mã yêu cầu.");
      }
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không kiểm tra được lệnh");
    } finally { setBusy(false); }
  };

  const slug = currentSlug(clock);
  const slotStart = Math.floor(clock / 300000) * 300000;
  const slotEnd = slotStart + 300000;
  const remaining = Math.max(0, Math.ceil((slotEnd - clock) / 1000));
  const validMarket = market && market.slug === slug &&
    clock - Date.parse(market.fetched_at) >= 0 && clock - Date.parse(market.fetched_at) <= 45000 &&
    market.active && !market.closed && market.accepting_orders;
  const validQuote = (outcome: "UP" | "DOWN") => {
    const quote = quotes[outcome];
    return Boolean(validMarket && quote?.slug === slug &&
      clock - Date.parse(quote.received_at) >= -2000 && clock - Date.parse(quote.received_at) <= 10000);
  };
  const available = validQuote("UP") && validQuote("DOWN");
  const equityCost = paper?.positions.reduce((sum, pos) => sum + Number(pos.cost_basis), 0) ?? 0;
  const stakeValid = Number.isFinite(Number(amount)) && Number(amount) >= 1 && Number(amount) <= 50 &&
    /^\d+(?:\.\d{1,6})?$/.test(amount);

  return (
    <div className="terminal">
      <header className="header" id="top">
        <div className="brand"><span className="mark" aria-hidden="true">◈</span>
          <div><strong>OpenPoly<span>Engine</span></strong><small>BTC 5m · Research terminal</small></div>
        </div>
        <div className="header-right">
          <span className={apiOnline ? "status connected" : "status"}><i aria-hidden="true" />
            {apiOnline ? "API Local Online" : "API Offline"}
          </span>
          <span className="safety">PAPER ONLY</span>
          <button className="icon-button" onClick={() => void refresh()} aria-label="Làm mới dữ liệu" title="Làm mới dữ liệu">↻</button>
        </div>
      </header>

      <main className="workspace">
        <div className="intro">
          <div><p className="eyebrow">POLYMARKET / BITCOIN / UP OR DOWN</p>
            <h1>BTC <span>5 phút</span></h1>
            <p className="subheading">Dữ liệu CLOB thật · Không sử dụng báo giá giả lập</p>
          </div>
          <div className="session"><span>PHIÊN HIỆN TẠI (UTC)</span>
            <strong>{new Date(slotStart).toLocaleTimeString("en-GB", { timeZone: "UTC", hour:"2-digit", minute:"2-digit" })} – {new Date(slotEnd).toLocaleTimeString("en-GB", { timeZone: "UTC", hour:"2-digit", minute:"2-digit" })}</strong>
            <small>{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,"0")} còn lại</small>
          </div>
        </div>

        <div className={available ? "feed-alert ready" : "feed-alert"} role="status">
          <div><strong>{available ? "CLOB VERIFIED · DỮ LIỆU CÒN MỚI" : "CHƯA CÓ BÁO GIÁ CLOB HỢP LỆ"}</strong>
            <p>{available
              ? "Hai outcome có order book thật đã được xác minh; lệnh chỉ mô phỏng trên dữ liệu này."
              : "Không có snapshot đủ mới từ Polymarket. Nút đặt lệnh ảo được khóa, không thay thế bằng mock hoặc giá cũ."}</p>
          </div>
          <span className="feed-source">{available ? "SOURCE: POLYMARKET CLOB" : "SOURCE: UNAVAILABLE"}</span>
        </div>
        {error && <p className="error-line" role="alert">{error}</p>}

        <div className="trade-grid">
          <section className="surface market-panel" aria-labelledby="book-title">
            <div className="panel-title"><div><p className="eyebrow">REAL MARKET DATA</p><h2 id="book-title">Order Book · BTC 5m</h2></div>
              <span className={available ? "pill green" : "pill amber"}>{available ? "FRESH" : "OFFLINE / STALE"}</span>
            </div>
            <div className="market-meta">
              <span>{slug}</span>
              <a href={`https://polymarket.com/event/${slug}`} target="_blank" rel="noopener noreferrer">Xem nguồn ↗</a>
            </div>
            <div className="outcomes">
              {(["UP","DOWN"] as const).map(outcome => {
                const q = validQuote(outcome) ? quotes[outcome] : undefined;
                return <div className={outcome === "UP" ? "outcome up" : "outcome down"} key={outcome}>
                  <div className="outcome-title"><strong>{outcome === "UP" ? "↗ UP" : "↘ DOWN"}</strong>
                    <small>{q ? `CLOB · ${time(q.received_at)}` : "Không có giá hiện hành"}</small></div>
                  <div className="bbo"><div><span>BEST BID</span><strong>{cents(q?.best_bid)}</strong></div>
                    <div><span>BEST ASK</span><strong>{cents(q?.best_ask)}</strong></div></div>
                  <p>Thanh khoản ask: {q ? `${Number(q.ask_size).toFixed(2)} shares` : "—"}</p>
                </div>;
              })}
            </div>
            <div className="market-footer"><span>Không dùng Gamma outcomePrices làm giá khớp lệnh</span>
              <span>{validMarket ? `Gamma cập nhật ${time(market.fetched_at)}` : "Gamma: không có market hợp lệ"}</span></div>
          </section>

          <section className="surface order-panel" aria-labelledby="paper-title">
            <div className="panel-title"><div><p className="eyebrow">SIMULATED EXECUTION · REAL QUOTES</p>
              <h2 id="paper-title">Paper Trading</h2></div><span className="pill indigo">USD ẢO</span></div>
            <div className="balance"><span>TIỀN MẶT KHẢ DỤNG</span>
              <strong>{paper ? `$${dollars(paper.cash_balance)}` : "—"}</strong>
              <small>Đang mở: ${dollars(equityCost)} USD · P&L đã đóng: {paper ? `$${dollars(paper.realized_pnl)}` : "—"}</small>
            </div>
            <label className="field-label" htmlFor="paper-amount">Khối lượng lệnh (USD ảo)</label>
            <div className="amount-field"><span>$</span>
              <input id="paper-amount" type="number" min="1" max="50" step="1" inputMode="decimal"
                value={amount} onChange={event => setAmount(event.target.value)} /></div>
            <div className="quick-amounts">
              {["5","10","25","50"].map(value =>
                <button key={value} className={amount === value ? "selected" : ""} type="button"
                  onClick={() => setAmount(value)}>${value}</button>
              )}
            </div>
            <div className="action-row">
              <button type="button" className="buy up-buy"
                disabled={!validQuote("UP") || !paper || !!pending || busy || !stakeValid}
                onClick={() => submit("BUY","UP")}>BUY UP <small>{validQuote("UP") ? cents(quotes.UP?.best_ask) : "—"}</small></button>
              <button type="button" className="buy down-buy"
                disabled={!validQuote("DOWN") || !paper || !!pending || busy || !stakeValid}
                onClick={() => submit("BUY","DOWN")}>BUY DOWN <small>{validQuote("DOWN") ? cents(quotes.DOWN?.best_ask) : "—"}</small></button>
            </div>
            {pending && <div className="pending-box"><strong>Yêu cầu chưa xác nhận</strong>
              <small>{pending.side} {pending.outcome} · {pending.request_id}</small>
              <div><button disabled={busy} onClick={() => void checkPending()}>Kiểm tra lệnh</button>
                <button disabled={busy} onClick={() => void sendPaper(pending)}>Thử lại cùng mã</button></div>
            </div>}
            {notice && <p role="status" className="notice-line">{notice}</p>}
            <p className="fine-print">Chỉ mô phỏng tại giá bid/ask từ snapshot CLOB. Hạn mức $1–$50/lệnh. Phí mô phỏng tính theo <strong>feeSchedule chính thức từ Gamma</strong> khi có; thiếu metadata phí sẽ khóa lệnh. Không có giao dịch tiền thật.</p>
          </section>
        </div>

        <section className="surface ledger" id="positions">
          <div className="panel-title"><div><p className="eyebrow">POSTGRESQL · VIRTUAL ACCOUNT</p>
            <h2>Vị thế & lịch sử lệnh</h2></div><span className="pill indigo">{paper?.positions.length ?? 0} vị thế</span></div>
          <h3>Vị thế đang mở</h3>
          {paper?.positions.length ? paper.positions.map(position =>
            <div className="position" key={position.slug+position.outcome}>
              <div><strong>{position.outcome} · {Number(position.quantity).toFixed(3)} shares</strong>
                <small>{position.slug} · Giá vốn $${dollars(position.cost_basis)}</small></div>
              <button type="button" onClick={() => submit("SELL", position.outcome, position.slug)}
                disabled={busy || !!pending || !validQuote(position.outcome) || position.slug !== slug}>SELL ALL</button>
            </div>
          ) : <p className="empty">Chưa có vị thế sử dụng dữ liệu CLOB thật.</p>}
          <h3>5 lệnh gần nhất</h3>
          {paper?.orders.slice(0,5).map(order =>
            <div className="history" key={order.order_id}>
              <div><strong>{order.side} {order.outcome}</strong>
                <small>{time(order.executed_at)} · {order.slug} · ${cents(order.price)}</small></div>
              <span>{Number(order.cash_delta) > 0 ? "+" : ""}${dollars(order.cash_delta)} USD</span>
            </div>
          )}
          {!paper?.orders.length && <p className="empty">Chưa có lệnh Paper trên CLOB.</p>}
          <p className="fine-print">Không tính P&L chưa đóng hoặc kết quả thị trường khi chưa có nguồn settlement xác minh.</p>
        </section>

        <footer>OpenPolyEngine · Real-data-only research · {lastMarket ? `Snapshot Gamma cuối: ${time(lastMarket.fetched_at)}` : "Chưa có snapshot Gamma"} · Không giao dịch thật</footer>
      </main>
    </div>
  );
}
