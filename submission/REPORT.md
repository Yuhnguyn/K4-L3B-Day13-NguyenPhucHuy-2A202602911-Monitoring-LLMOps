# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mọi số liệu là số đo thật, xác minh qua API Langfuse và `data/logs.jsonl`.

## 1. Thông tin học viên

- **Họ và tên:** Nguyễn Phúc Huy
- **MSSV:** 2A202602911
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/Yuhnguyn/K4-L3B-Day13-NguyenPhucHuy-2A202602911-Monitoring-LLMOps
- **Commit SHA cuối:** `3a5f22f` (commit chứa toàn bộ source và evidence; nếu sau đó còn commit bổ sung thì SHA nộp là **commit cuối của nhánh `main`**)
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602911`

## 2. Evidence index

| Evidence | Đường dẫn | Trạng thái |
|---|---|---|
| Pytest cuối | `evidence/01-pytest.png` (+ `01-pytest.txt`) | xong |
| Log validator | `evidence/02-log-validator.png` (+ `.txt`) | xong |
| Dashboard validator | `evidence/03-dashboard-validator.png` (+ `.txt`) | xong |
| Structured log | `evidence/04-structured-log.png` (+ `.txt`) | xong |
| PII redaction | `evidence/05-pii-redaction.png` (+ `.txt`) | xong |
| Trace list | `evidence/06-trace-list.png` | xong (chụp lại sau khi đổi tên project) |
| Trace waterfall | `evidence/07-trace-waterfall.png` | xong (chụp lại sau khi đổi tên project) |
| Trace metadata | `evidence/08-trace-metadata.png` | xong (đã bỏ dòng public key) |
| Prompt versions | `evidence/09-prompt-versions.png` + `09b-prompt-version-1.png` | xong (chụp lại sau khi đổi tên project) |
| Prompt rollback | `evidence/10-prompt-rollback.png` | **đang chụp** — xem mục 5 |
| Dashboard runtime | `evidence/11-dashboard-overview.png` (+ `dashboard-runtime.html`) | xong |
| Incident metric | `evidence/12-incident-metric.png` (+ `dashboard-incident-runtime.html`) | xong |
| Incident log | `evidence/13-incident-log.txt` | xong |
| Incident trace | `evidence/14-incident-trace.png` | xong (chụp lại sau khi đổi tên project) |

Nguồn của evidence 11 và 12 là hai file HTML sinh bằng `scripts/dashboard.py`, nên dashboard tái tạo được từ source.

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | **100/100** | baseline thiếu `correlation_id` và enrichment |
| `validate_dashboard.py` | 6/6 | 6/6 | contract cho sẵn, hợp lệ ngay từ đầu |
| `pytest` | 22 passed | **43 passed** | thêm 4 test correlation ID, 6 test PII, 11 test dashboard |
| Số traces hợp lệ | 0 | **88** | đếm qua API Langfuse, xem mục 5 |
| Số PII leak | 0 | 0 | 0 leak ở mọi lần đo |
| Latency P50 / P95 / P99 | 159 / 240 / 240 ms | 167 / 444 / 662 ms | lần đo 33 request rải 12 phút |
| TTFT P95 | 139 ms | 152 ms | ổn định |
| Retrieval success rate | 100 % | 100 % | 33/33 request có `tool_success = true` |

## 4. Logging và PII

- **Correlation ID:** middleware xoá context cũ, nhận `x-request-id` nếu là token hợp lệ (`[A-Za-z0-9._:-]{1,64}`, chặn log injection), ngược lại sinh `req-<8-hex>`; bind vào structlog contextvars và trả lại qua header `x-request-id` + `x-response-time-ms`.
- **Metadata trong log:** `user_id_hash` (sha256 12 ký tự, không ghi ID thô), `session_id`, `feature`, `model`, `env`, `correlation_id`, `service`; log response thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Vì sao bind ở hai chỗ:** middleware chỉ biết header nên bind `correlation_id`; endpoint `/chat` bind phần còn lại trước `request_received` vì `user_id`/`session_id`/`feature` chỉ có sau khi FastAPI parse body.
- **Thứ tự scrub:** `scrub_event` đăng ký **trước** `JsonlFileProcessor` (ghi file) và `JSONRenderer`, và redact đệ quy payload, nên dữ liệu được che trước khi serialize/ghi.
- **Rule PII:** email, điện thoại Việt Nam (5 kiểu viết), CCCD 12 số, thẻ thanh toán, CMND 9 số, hộ chiếu `1 chữ + 7 số`; pattern số dài xếp trước số ngắn.

## 5. Tracing và prompt versioning

- **Cây observation (xác minh qua API Langfuse, trace `8cd686ffde41dc7a55ff16dcab99cfd7`):**

| type | name | parent | model | usage | cost |
|---|---|---|---|---|---|
| AGENT | `lab-agent-run` | — (root) | | | |
| RETRIEVER | `retrieval` | `c724eda916c38980` | | | |
| GENERATION | `generation` | `c724eda916c38980` | `claude-sonnet-4-5` | `{input: 33, output: 90, total: 123}` | `{total: 0.001449}` |

- **Metadata:** `correlation_id`, `prompt_name`, `prompt_label`, `prompt_version`, `prompt_source`, `doc_count`, `query_preview`; `correlation_id` được propagate nên xuất hiện cả trên retrieval và generation.
- **Không capture raw:** root dùng `capture_input=False, capture_output=False`; child chỉ nhận preview đã qua `summarize_text()`.
- **Tổng trace:** 88 trace `lab-agent-run`, trong đó 83 (production, v1), 2 (baseline, v1), 2 (candidate, v2), 1 (production, v2 — sau promote).

| Bước | correlation_id | trace ID | label | version |
|---|---|---|---|---|
| baseline (v1) | `req-base0001` | `0149fbc8d29da4a80fda596e3fbd1693` | baseline | 1 |
| baseline (v1) | `req-base0002` | `25c434135b19c749af5fef234f593e53` | baseline | 1 |
| candidate (v2) | `req-cand0001` | `c365756d496d1e88abe9f87d7e498c3f` | candidate | 2 |
| candidate (v2) | `req-cand0002` | `2367da0245bc87ab5e9abd10284663dd` | candidate | 2 |
| sau PROMOTE | `req-prom0001` | `63cc66aa40ebbd2f2417f45e3734237a` | production | **2** |
| sau ROLLBACK | `req-roll0001` | `c94bf8c83151b0d2522383619f244992` | production | **1** |

- **Cách promote/rollback:** chỉ dời label `production` giữa hai version trên Langfuse, không sửa code. Sau promote, request `req-prom0001` chạy bằng version 2; sau rollback, `req-roll0001` quay lại version 1. Trạng thái label: v1 = `[production, baseline]`, v2 = `[candidate, latest]`.
- **Token chênh giữa v1 và v2:** v2 thêm một dòng 62 ký tự, mà `tokens_in = max(20, len(prompt) // 4)`, nên cùng một input thì v2 tốn thêm **14 token** (đã đo trực tiếp). Nội dung trả lời không đổi vì fake LLM trả câu cố định — đúng như `docs/PROMPT_VERSIONING.md` mô tả.

## 6. Dashboard, SLO và alerts

- **Dashboard:** `scripts/dashboard.py` đọc `data/logs.jsonl`, sinh HTML tự chứa (CSS + SVG inline, không CDN, không thêm dependency vào venv của API). Sáu panel: latency/TTFT, traffic, errors + retrieval success, cost, tokens, quality. Cửa sổ 60 phút, tự refresh 30 giây, mỗi panel có đơn vị và đường threshold.
- **Hai quyết định của dashboard:** (1) panel cost/tokens vẽ chuỗi tích luỹ vì threshold của contract áp cho tổng cả cửa sổ; (2) retrieval success tính trên **mọi** event có `tool_success` (cả `response_sent` và `request_failed`), nếu chỉ lấy `request_failed` thì luôn ra 0 %.
- **SLO:** `fast_successful_requests`, 99,5 % / 28 ngày, SLI = `response_sent` với `latency_ms <= 3000`. Giữ 3000 ms vì đó là đường SLO trên panel latency; baseline p95 = 444 ms nên còn khoảng 6,8 lần headroom.
- **Error budget:** nhịp 2,75 request/phút → 28 ngày ≈ 110.880 request → 0,5 % ≈ **554 request**; với 10.000 request thì là 50 request.
- **Ba alert:** `HighLatencyP95` (warning, 5m), `ElevatedErrorRate` (critical, 3m, cần ≥ 3 lỗi), `RetrievalSuccessDrop` (warning, 10m) — mỗi alert có condition, duration, severity, owner `student-2A202602911`, kênh Slack `#k4-l3b-alerts`, runbook trong `docs/alerts.md` theo ba bước Metrics → Logs → Traces.

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Khoảng thời gian:** 05:22:07 → 05:26:52 UTC ngày 2026-09-30 (baseline 10 request chạy ngay trước, không bật incident)
- **Triệu chứng từ metrics:**

| Chỉ số | Baseline (10 request) | Trong sự cố (30 request) |
|---|---|---|
| latency P50 | 173 ms | **2.672 ms** |
| latency P95 | 1.571 ms | **2.712 ms** |
| latency max | 1.571 ms | **2.864 ms** |
| TTFT P50 / P95 | 53 / 61 ms | **56 / 65 ms** |
| vượt ngưỡng challenge 2000 ms | 0/10 | **30/30 (100 %)** |
| error rate | 0 % | 0 % |
| retrieval success | 100 % | 100 % |

> Lưu ý về baseline: một request đạt 1.571 ms vì là request **đầu tiên sau khi restart**, phải tải prompt từ Langfuse lần đầu (cache miss). Các request còn lại khoảng 173 ms.

- **Log line và correlation ID:** `correlation_id = req-2abbd121`, `event = response_sent`, `latency_ms = 2864`, `ttft_ms = 166`, `tokens_in = 34`, `tokens_out = 162`, `cost_usd = 0.002532`, `tool_name = retrieval`, `tool_success = true`, `feature = monitoring`, `ts = 2026-09-30T05:26:41.884978Z`. Log gốc trong `evidence/13-incident-log.txt` (kèm sha256 hai dòng gốc).
- **Trace ID và span gây ảnh hưởng:** trace `8f4ed07f2549c65320789c235aac5cfa` (cùng `correlation_id`):

| type | name | thời lượng | tỉ lệ | model | usage | cost |
|---|---|---|---|---|---|---|
| AGENT | `lab-agent-run` | 2.880 ms | 100 % | | | |
| RETRIEVER | `retrieval` | **2.506 ms** | **87,0 %** | | | |
| GENERATION | `generation` | 361 ms | 12,5 % | `claude-sonnet-4-5` | `{input: 34, output: 162, total: 196}` | `0.002532` |

- **Root cause:** bước **retrieval** chậm bất thường. Không phải suy đoán: trace cho thấy span `retrieval` chiếm 2.506 ms trong tổng 2.880 ms (87 %), trong khi `generation` chỉ 361 ms. Kết luận này khớp với hai tín hiệu độc lập: (1) `ttft_ms` gần như không đổi vì nó chỉ đo bên trong lời gọi LLM; (2) mức tăng ~2,5 giây đúng bằng độ trễ nhân tạo của incident `rag_slow`.
- **Fix action:** đã tắt incident bằng `python scripts/inject_incident.py --scenario rag_slow --disable`; `/health` xác nhận cả ba incident `false`. Trong vận hành thật: kiểm tra nguồn tài liệu/vector store của bước retrieval, khôi phục cấu hình retrieval gần nhất nếu vừa thay đổi, bật fallback để request không bị treo.
- **Preventive measure:**
  1. **Đóng khoảng trống ngưỡng cảnh báo.** P95 trong sự cố là 2.712 ms, **không vượt** đường SLO 3000 ms, nên alert `HighLatencyP95` **sẽ không kêu** dù 100 % request đã vượt ngưỡng 2000 ms của challenge. Cần thêm alert theo **độ lệch so với baseline** (ví dụ `p50 > 3 × baseline p50` trong 5 phút), không chỉ dựa vào một ngưỡng tuyệt đối.
  2. **Cảnh báo theo span.** `retrieval success` vẫn 100 % và error rate vẫn 0 %, nên chỉ số trạng thái không phát hiện được gì; cần theo dõi thời lượng của riêng span `retrieval`.
  3. **Ngân sách lỗi bị ăn nhanh:** 30 request lỗi trong ~5 phút ≈ 5,4 % của error budget 554 request cho cả 28 ngày.
  4. Giữ panel latency và panel lỗi tách riêng để hai loại suy giảm không che nhau.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng:** dựng dashboard bằng HTML/SVG tự chứa thay vì Streamlit/Altair. Lý do: thư viện vẽ biểu đồ không có trong `requirements.txt` và cài chung sẽ hạ cấp dependency mà API đang dùng; HTML tự chứa vẫn đủ threshold line, đơn vị, time range 60 phút, tự refresh 30 giây, và render lại được bằng một lệnh nên bằng chứng tái tạo được.
- **Một lỗi/blocker đã gặp:** số đo phía client của `load_test.py --concurrency 5` là 13,4 giây trong khi `latency_ms` phía server chỉ 2,66 giây. Tôi đo lại để xác định nguyên nhân thay vì đoán: **1 request đơn lẻ** mất 2.761 ms phía client (server 2.666 ms), còn **5 request đồng thời** mất 13.597 ms phía client so với **tổng** 13.420 ms latency phía server. Chênh lệch chỉ xảy ra khi các request bị xử lý **tuần tự**, vì endpoint là `async def` nhưng gọi code blocking (`time.sleep`) nên chặn event loop.
- **Cách tìm nguyên nhân và xử lý:** chỉ dùng `latency_ms` ghi trong log/dashboard để kết luận, không dùng số phía client; ghi nhận đây là hạn chế của starter và là ứng viên cải tiến (`run_in_threadpool` hoặc async sleep).
- **Một va chạm API thật:** Langfuse Cloud trả `410 LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION` cho `GET /api/public/traces`; phải dùng `GET /api/public/v2/observations`. Ngoài ra endpoint v2 **không nhận** `parseIoAsJson=true` nữa (input/output luôn trả về dạng chuỗi) và mặc định **không** trả `model`/`usage`/`cost` — phải chỉ định tham số `fields`.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics cho biết *có* vấn đề và *khoảng thời gian*; log có `correlation_id` nên chọn được **một** request đại diện và biết nó chậm bao nhiêu; trace của đúng request đó chia nhỏ thời gian theo bước để chỉ ra bước nào gánh độ trễ. Ba lớp chỉ đủ tin khi cùng trỏ về một request/giai đoạn.
- **Vai trò của prompt version, token/cost, SLO và rollback:** prompt cần phiên bản và label để biết một request đã chạy prompt nào; label `production` là con trỏ nên đổi prompt không phải sửa code, rollback chỉ là dời con trỏ. Token/cost là chỉ số vận hành vì prompt dài hơn làm tăng cả hai. SLO kèm error budget biến "nhanh" từ cảm tính thành mức cam kết có số request cụ thể.
- **Điều quan trọng nhất đã học:** thứ tự trong processor chain là điều kiện sống còn — che PII sau khi đã ghi file thì vô nghĩa; và validator PASS không có nghĩa là yêu cầu đề bài đã thoả (baseline đã PASS mục PII dù chưa đăng ký `scrub_event`).
- **Hạn chế còn lại:** `quality_score` là heuristic so khớp từ khoá kiểu "chuỗi con" nên khá lỏng (ví dụ `is` khớp trong `this`), chỉ dùng để phát hiện xu hướng; request đầu tiên sau restart chịu thêm ~1,4 giây tải prompt và dễ bị đọc nhầm thành sự cố; ứng dụng vẫn chặn event loop khi xử lý đồng thời.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident metric → log → trace nối đúng một `correlation_id` (`req-2abbd121` → `8f4ed07f2549c65320789c235aac5cfa`).
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và không lộ key. [CHỜ CHỤP]
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] `config/challenge.json` và `.env` không bị commit (đã kiểm tra `.gitignore` và `git status`).
- [ ] URL repo và commit SHA cuối đã nộp trên LMS/Codelabs.
