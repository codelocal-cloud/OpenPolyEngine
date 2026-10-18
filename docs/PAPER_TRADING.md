# OpenPolyEngine Paper Trading v0.3 — USD ảo, không có live orders

## Thiết kế và phạm vi

- **PostgreSQL 17** là nơi ghi duy nhất cho tài khoản, vị thế, lệnh, dòng tiền.
- Hai tài khoản độc lập: `demo` và `clob`, mỗi tài khoản bắt đầu bằng **1,000 USD ảo**. Không có số dư USDC thật, không có ví, ký lệnh, API đặt lệnh hay chuyển tiền.
- `demo` dùng báo giá **giả lập cố định** (UP và DOWN đều BID = 0.48, ASK = 0.52; thanh khoản giả định). Đây **không phải giá Polymarket**. Các phiên demo kết thúc sau 5 phút nhưng cho phép SELL lại vị thế cũ bằng mức giá demo tĩnh, **không mô phỏng kết quả thị trường**.
- `clob` chỉ đọc sự kiện CLOB book có thật đã lưu, với thị trường Gamma `gamma_public` xác thực chính xác token UP/DOWN và slot UTC đang hoạt động. Mỗi lần vào lệnh kiểm tra lại từ PostgreSQL và từ chối nếu snapshot quá 10 giây hoặc metadata quá 45 giây, market đóng, lệch timestamp, thiếu bid/ask hoặc thiếu thanh khoản tại mức giá tốt nhất.
- Tất cả lệnh mô phỏng đều dùng **full fill tại top-of-book**, hoặc từ chối toàn bộ. Chưa có khớp lệnh từng phần, order queue, phí chính thức, price impact, front running hay slippage thực tế. CLOB paper không thể thay thế backtest execution quality.
- **Phí 0.5% trên notional là giả định để thử mô hình kế toán**, không khẳng định giống phí Polymarket.
- `BUY` trừ vốn ảo + phí và ghi vị thế; `SELL ALL` đóng toàn bộ vị thế ở bid, trừ phí và cộng/giảm `realized_pnl`. Không cho bán khống.
- **Không tự settle phiên UP/DOWN** theo kết quả thị trường vì oracle và resolution rules chưa được xác minh. P&L chưa đóng không được hiển thị như đã kiếm được tiền.
- Giới hạn: **$1–$50/lệnh BUY**, tối đa **$250 giá vốn đang mở**, tối đa 6 vị thế. Từ chối nếu thiếu tiền mặt.
- Transaction account `SELECT FOR UPDATE`, request ID UUID v4, fingerprint chống reuse với payload khác, unique index và ledger append-only ngăn bấm hai lần làm trừ tiền hai lần.
- API chỉ bind `127.0.0.1`, tất cả POST yêu cầu `X-OpenPoly-Paper: 1`, Origin whitelist và Host localhost. Đây là tiện ích một người dùng **chưa có login/đa người dùng**; đừng mở công khai endpoint localhost qua reverse proxy.

## Chạy thử

```bash
cd ~/Documents/OpenPolyBtcEngine
docker compose up -d
.venv/bin/python -m services.market_data.migrate
.venv/bin/python -m services.api.server
# Ở terminal thứ hai:
cd apps/dashboard && npm ci && npm run dev
```

Mở **http://127.0.0.1:5173/** và chọn **Demo offline**. Nhập 1–50 USD ảo, nhấn BUY UP/DOWN, xem lệnh/vị thế, sau đó nhấn SELL ALL (ảo). Tab `CLOB Paper` sẽ bị khóa mua/bán cho đến khi có dữ liệu CLOB mới và hợp lệ.

Các endpoint:
- `GET /api/paper/state?account=demo|clob`
- `GET /api/paper/quote?account=demo|clob&outcome=UP|DOWN`
- `GET /api/paper/request?account=demo|clob&request_id=<UUID-v4>` — kiểm tra một yêu cầu đã ghi sổ sau khi POST không trả kết quả rõ ràng; kết quả được scoped theo tài khoản. UI cho phép thử lại **cùng UUID và payload** (không tự tạo lệnh mới).
- CLOB Paper từ chối khớp nếu có `price_change`, `tick_size_change` hoặc `best_bid_ask` mới hơn / cùng thời điểm receive với snapshot `book` mới nhất. Cần snapshot đầy đủ mới để ghi paper fills; **chưa có cơ chế tái dựng order book bằng delta**.
- `POST /api/paper/orders?account=demo|clob` — header `Content-Type: application/json`, `X-OpenPoly-Paper: 1`; JSON `{"request_id":"<UUID-v4>","side":"BUY","outcome":"UP","spend_usd":"10.00","slug":"<current-slug>"}`. SELL dùng `side: "SELL"`, `outcome`, `slug`, không có `spend_usd`.

Tests:
```bash
POLYBTC_RUN_DB_TESTS=1 POLYBTC_RUN_REDIS_TESTS=1 .venv/bin/python -m unittest discover -s tests -q
cd apps/dashboard && npm run build
```

Lưu ý: migration 004 **không tự đặt lệnh hay trừ số dư**; chỉ tạo tài khoản ảo ban đầu. Kịch bản kiểm thử PostgreSQL chạy trong transaction được rollback, không làm thay đổi số dư người dùng.
