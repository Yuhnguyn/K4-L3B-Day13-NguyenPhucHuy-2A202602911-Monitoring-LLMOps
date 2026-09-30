# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: `fast_successful_requests` — latency P95 của `response_sent.latency_ms` ≤ 3000 ms (xem `config/slo.yaml`)
- Điều kiện và thời gian duy trì: `p95(latency_ms where event == "response_sent") > 3000ms` liên tục 5 phút
- Ảnh hưởng tới người dùng: mỗi câu trả lời chậm hơn ngưỡng SLO, người dùng phải chờ lâu; nếu kéo dài sẽ ăn vào error budget
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** mở panel `latency` trên dashboard, xác nhận P95/P99 và TTFT P95 tăng từ phút nào; ghi lại khoảng thời gian.
  2. **Logs:** lọc `data/logs.jsonl` theo `event == "response_sent"` trong khoảng đó, sắp xếp theo `latency_ms` giảm dần và lấy một `correlation_id` có latency cao bất thường.
  3. **Traces:** mở trace có đúng `correlation_id` đó trên Langfuse, so sánh độ dài của span `retrieval` và `generation` để xác định bước nào gây chậm.
- Mitigation tạm thời: nếu span chậm là `retrieval`, kiểm tra vector store/nguồn tài liệu và tạm tắt practice scenario `rag_slow`; nếu là `generation`, kiểm tra prompt version đang dùng và rollback `production` về version trước đó; nếu hệ thống quá tải, giảm concurrency của workload và giảm tải trong lúc demo.
- Owner: `student-2A202602911`

## Alert 2

- Tên: `ElevatedErrorRate`
- Severity: `critical`
- Duration: `3m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: `fast_successful_requests` — error rate ≤ 2 % (guardrail `error_rate_pct_max` trong `config/slo.yaml`)
- Điều kiện và thời gian duy trì: `error_rate_pct > 2%` **và** có ít nhất 3 `request_failed` trong 3 phút liên tục
- Ảnh hưởng tới người dùng: người dùng nhận lỗi 500 thay vì câu trả lời — đây là sự cố nặng nhất trong ba alert vì request không có kết quả nào
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** mở panel `errors`, đọc `error_rate_pct` và bảng `error_type` để biết đang lỗi loại gì (`RuntimeError` là retrieval fail) và khoảng thời gian.
  2. **Logs:** lọc `event == "request_failed"` trong khoảng đó, lấy `correlation_id` và đọc `error_type`, `tool_name`, `tool_success`; đồng thời kiểm tra `request_received` cùng `correlation_id` để biết request đi tới đâu.
  3. **Traces:** mở trace cùng `correlation_id`, xem span nào mang trạng thái lỗi (`level = ERROR`) và `status_message` để khoanh vùng điểm gãy.
- Mitigation tạm thời: tắt incident/practice scenario đang bật (`python scripts/inject_incident.py --scenario <name> --disable`) để khôi phục dịch vụ; nếu lỗi tới từ một prompt version mới, rollback `production`; nếu lỗi đến từ phụ thuộc ngoài (vector store, model provider), chuyển sang fallback và thông báo cho người dùng là hệ thống đang suy giảm.
- Owner: `student-2A202602911`

## Alert 3

- Tên: `RetrievalSuccessDrop`
- Severity: `warning`
- Duration: `10m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `retrieval_success_rate_pct_min: 90` trong `config/slo.yaml`, tính trên mọi event có field `tool_success`
- Điều kiện và thời gian duy trì: `retrieval_success_rate_pct < 90%` liên tục 10 phút
- Ảnh hưởng tới người dùng: RAG không lấy được context phù hợp nên câu trả lời kém chính xác dù hệ thống **không** báo lỗi — người dùng vẫn nhận 200 nhưng chất lượng giảm, khó nhận ra nếu chỉ nhìn error rate
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** mở panel `errors`, đọc chỉ số `retrieval success` và đối chiếu panel `quality` xem quality proxy có giảm cùng lúc không; xác định khoảng thời gian bắt đầu.
  2. **Logs:** lọc các bản ghi có `tool_success` (gồm cả `response_sent` và `request_failed`), đếm `tool_success is False`, lấy một `correlation_id` đại diện.
  3. **Traces:** mở trace cùng `correlation_id`, kiểm tra span `retrieval` — `doc_count` bằng 0 hoặc output rỗng nghĩa là không khớp tài liệu; nếu span báo lỗi thì xem `status_message`.
- Mitigation tạm thời: kiểm tra nguồn tài liệu và từ khoá truy vấn, khôi phục cấu hình retrieval gần nhất nếu vừa thay đổi, tắt scenario `tool_fail` đang bật; thêm cảnh báo phụ cho `quality_score` để không bỏ sót suy giảm chất lượng âm thầm.
- Owner: `student-2A202602911`
