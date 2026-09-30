"""Dựng dashboard 6 panel của Day 13 từ `data/logs.jsonl`.

Vì sao không dùng Streamlit/Altair: các thư viện đó không có trong requirements.txt
và cài chung sẽ hạ cấp dependency mà API đang chạy. Script này chỉ dùng stdlib, xuất
một file HTML tự chứa (CSS + SVG inline, không CDN), nên:

- không thêm dependency nào vào venv của API;
- có threshold line cho từng panel (SVG vẽ trực tiếp);
- tự refresh mỗi 30 giây bằng <meta http-equiv="refresh">;
- cửa sổ mặc định 60 phút, ghi rõ đơn vị và khoảng thời gian.

Sáu panel bám đúng contract trong `config/dashboard.yaml`:
latency, traffic, errors, cost, tokens, quality.

Ví dụ:
    python scripts/dashboard.py
    python scripts/dashboard.py --log data/logs.jsonl --out submission/evidence/dashboard-runtime.html
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

DEFAULT_LOG = REPO_ROOT / "data" / "logs.jsonl"
DEFAULT_OUT = REPO_ROOT / "submission" / "evidence" / "dashboard-runtime.html"

WINDOW_MINUTES = 60
REFRESH_SECONDS = 30

# Threshold lấy đúng theo config/dashboard.yaml
THRESHOLDS = {
    "latency": ("p95", "lte", 3000.0, "ms"),
    "traffic": ("rate_per_minute", "gte", 1.0, "req/phút"),
    "errors": ("error_rate_pct", "lte", 2.0, "%"),
    "cost": ("total", "lte", 2.5, "USD"),
    "tokens": ("sum_by_field", "lte", 50000.0, "token"),
    "quality": ("mean", "gte", 0.75, "0–1"),
}

COLORS = {
    "primary": "#2563eb",
    "secondary": "#f59e0b",
    "ok": "#16a34a",
    "bad": "#dc2626",
    "grid": "#e5e7eb",
    "ink": "#111827",
    "muted": "#6b7280",
}


def parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def window_of(records: list[dict]) -> tuple[datetime | None, datetime | None, list[dict]]:
    """Cửa sổ 60 phút kết thúc ở bản ghi mới nhất, trả về (start, end, records)."""
    stamped = [(parse_ts(record.get("ts")), record) for record in records]
    stamped = [(ts, record) for ts, record in stamped if ts is not None]
    if not stamped:
        return None, None, []
    end = max(ts for ts, _ in stamped).replace(second=0, microsecond=0) + timedelta(minutes=1)
    start = end - timedelta(minutes=WINDOW_MINUTES)
    inside = [record for ts, record in stamped if start <= ts < end]
    return start, end, inside


def minute_buckets(start: datetime, end: datetime) -> list[datetime]:
    buckets: list[datetime] = []
    cursor = start
    while cursor < end:
        buckets.append(cursor)
        cursor += timedelta(minutes=1)
    return buckets


def bucket_index(ts: datetime, start: datetime) -> int:
    return int((ts - start).total_seconds() // 60)


def events(records: list[dict], name: str) -> list[dict]:
    return [record for record in records if record.get("event") == name]


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{suffix}"


# --------------------------------------------------------------------------- SVG


def _fmt_num(value: float) -> str:
    """Định dạng số theo độ lớn, tránh làm tròn mất giá trị: 3000 → 3,000 · 2.5 → 2.5 · 0.75 → 0.75."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _nice_ceil(value: float) -> float:
    """Làm tròn trục y lên mốc 1/2/2.5/5 × 10^n để nhãn trục dễ đọc."""
    if value <= 0:
        return 1.0
    base = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 2.5, 5, 10):
        if value <= factor * base + 1e-9:
            return factor * base
    return 10 * base


def cumulative(points: list[float | None]) -> list[float | None]:
    """Chuyển chuỗi theo phút thành chuỗi tích luỹ (tổng dồn trong cửa sổ).

    Dùng cho panel mà threshold của contract là giá trị của **cả cửa sổ**
    (cost: total ≤ 2.5 USD, tokens: sum_by_field ≤ 50000 token), nên đường
    threshold mới so sánh được trực tiếp với dữ liệu.
    """
    running = 0.0
    out: list[float | None] = []
    for value in points:
        if value is not None:
            running += value
        out.append(round(running, 6))
    return out


def bar_chart(
    buckets: list[datetime],
    series: list[tuple[str, str, list[float | None]]],
    *,
    threshold: float | None,
    operator: str,
    unit: str,
    height: int = 150,
    mode: str = "per_minute",
    threshold_scope: str = "",
) -> str:
    """Vẽ biểu đồ cột kèm đường threshold (SVG thuần).

    viewBox cố ý hẹp (460 đơn vị) để khi SVG co vào cột ~490 px của lưới 3 cột
    thì chữ không bị nhỏ đi và vẫn đọc được trong ảnh chụp màn hình.
    """
    width, pad_l, pad_r, pad_t, pad_b = 460, 46, 10, 30, 24
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    # Giữ bản gốc trước khi cộng dồn: chuỗi tích luỹ đã lấp đầy các phút trống nên
    # không còn phản ánh đúng khoảng thời gian thật sự có request.
    observed = [points for _, _, points in series]

    if mode == "cumulative":
        series = [(label, color, cumulative(points)) for label, color, points in series]

    values = [v for _, _, points in series for v in points if v is not None]
    vmax = max(values) if values else 0.0
    if threshold is not None:
        vmax = max(vmax, threshold)
    vmax = _nice_ceil(vmax * 1.1) if vmax > 0 else 1.0

    def y_of(value: float) -> float:
        return pad_t + plot_h - (value / vmax) * plot_h

    count = max(len(buckets), 1)
    group_w = plot_w / count
    slot_w = max(group_w / max(len(series), 1) - 2, 1.5)

    # Vùng có dữ liệu thực tế được tô nền nhạt để phần trống của cửa sổ 60 phút
    # không bị hiểu nhầm là lỗi hiển thị. Dùng chuỗi GỐC (observed), không dùng
    # chuỗi tích luỹ.
    filled = [
        index
        for index in range(len(buckets))
        if any(index < len(points) and points[index] is not None for points in observed)
    ]

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">',
        f'<rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{plot_h}" fill="#fbfdff" stroke="{COLORS["grid"]}"/>',
    ]
    if filled:
        x1 = pad_l + filled[0] * group_w
        x2 = pad_l + (filled[-1] + 1) * group_w
        parts.append(
            f'<rect x="{x1:.1f}" y="{pad_t}" width="{max(x2 - x1, 2):.1f}" height="{plot_h}" fill="#eef4ff"/>'
        )
        # Chú thích đặt PHÍA TRÊN vùng vẽ (không nằm trong vùng vẽ) để không bao
        # giờ đè lên cột dữ liệu cao hoặc lên nhãn mốc thời gian của trục x.
        parts.append(
            f'<text x="{(x1 + x2) / 2:.1f}" y="{pad_t - 5}" text-anchor="middle" font-size="10" '
            f'fill="{COLORS["muted"]}">vùng có dữ liệu ({len(filled)} phút)</text>'
        )
    for frac in (0.25, 0.5, 0.75):
        y = pad_t + plot_h * frac
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" stroke="{COLORS["grid"]}"/>')
    parts.append(f'<text x="{pad_l - 6}" y="{pad_t + 4}" text-anchor="end" font-size="10" fill="{COLORS["muted"]}">{_fmt_num(vmax)}</text>')
    parts.append(f'<text x="{pad_l - 6}" y="{pad_t + plot_h + 3}" text-anchor="end" font-size="10" fill="{COLORS["muted"]}">0</text>')

    for index, minute in enumerate(buckets):
        for position, (_, color, points) in enumerate(series):
            value = points[index] if index < len(points) else None
            if value is None:
                continue
            bar_h = max((value / vmax) * plot_h, 1.0)
            x = pad_l + index * group_w + position * (slot_w + 2) + 1
            parts.append(
                f'<rect x="{x:.1f}" y="{y_of(value):.1f}" width="{slot_w:.1f}" '
                f'height="{bar_h:.1f}" fill="{color}"><title>{minute.strftime("%H:%M")} — {value:,.2f} {unit}</title></rect>'
            )

    if threshold is not None:
        y = y_of(threshold)
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" '
            f'stroke="{COLORS["bad"]}" stroke-width="1.4" stroke-dasharray="6 3"/>'
        )
        # Nhãn đặt ở góc dưới-trái vùng vẽ, có viền trắng (paint-order) để không bị
        # cột dữ liệu che và không chồng lên nhãn mốc thời gian ở đáy.
        parts.append(
            f'<text x="{pad_l + 5}" y="{pad_t + plot_h - 6}" font-size="10" fill="{COLORS["bad"]}" '
            f'stroke="#ffffff" stroke-width="2.5" paint-order="stroke">'
            f'threshold {operator} {_fmt_num(threshold)} {unit}{threshold_scope}</text>'
        )

    if buckets:
        parts.append(f'<text x="{pad_l - 6}" y="{pad_t + plot_h + 18}" text-anchor="end" font-size="10" fill="{COLORS["muted"]}">UTC</text>')
        parts.append(f'<text x="{pad_l}" y="{height - 7}" font-size="10" fill="{COLORS["muted"]}">{buckets[0].strftime("%H:%M")}</text>')
        parts.append(
            f'<text x="{pad_l + plot_w}" y="{height - 7}" text-anchor="end" font-size="10" fill="{COLORS["muted"]}">'
            f'{buckets[-1].strftime("%H:%M")}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def legend(series: list[tuple[str, str, list[float | None]]]) -> str:
    if len(series) < 2:
        return ""
    items = "".join(
        f'<span class="legend-item"><i style="background:{color}"></i>{label}</span>'
        for label, color, _ in series
    )
    return f'<div class="legend">{items}</div>'


def stat(label: str, value: str, ok: bool | None = None) -> str:
    cls = "stat" + (" stat-ok" if ok is True else " stat-bad" if ok is False else "")
    return f'<div class="{cls}"><span class="stat-label">{label}</span><span class="stat-value">{value}</span></div>'


def panel(panel_id: str, title: str, question: str, unit: str, body: str, stats: str) -> str:
    return f"""
    <section class="panel" id="{panel_id}">
      <header>
        <h2>{title}</h2>
        <p class="q">{question}</p>
        <span class="unit">đơn vị: {unit}</span>
      </header>
      <div class="stats">{stats}</div>
      {body}
    </section>"""


# ------------------------------------------------------------------------ build


def display_path(path: Path) -> str:
    """Đường dẫn gọn để hiển thị; log nằm ngoài repo vẫn phải render được."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def build_html(records: list[dict], log_path: Path, note: str = "") -> str:
    start, end, current = window_of(records)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if start is None or end is None:
        return f"""<!doctype html><html lang="vi"><meta charset="utf-8">
<title>Day 13 Monitoring dashboard</title>
<body style="font-family:system-ui;padding:40px">
<h1>Chưa có dữ liệu</h1>
<p>Không tìm thấy bản ghi hợp lệ trong <code>{log_path}</code>. Hãy chạy API rồi
<code>python scripts/load_test_spread.py</code>.</p></body></html>"""

    buckets = minute_buckets(start, end)

    def series_for(event_name: str, field: str, agg: str) -> list[float | None]:
        grouped: dict[int, list[float]] = defaultdict(list)
        for record in events(current, event_name):
            value = record.get(field)
            ts = parse_ts(record.get("ts"))
            if not is_number(value) or ts is None:
                continue
            grouped[bucket_index(ts, start)].append(float(value))  # type: ignore[arg-type]
        points: list[float | None] = []
        for index in range(len(buckets)):
            values = grouped.get(index, [])
            if not values:
                points.append(None)
            elif agg == "sum":
                points.append(round(sum(values), 6))
            elif agg == "mean":
                points.append(round(sum(values) / len(values), 4))
            else:
                # percentile() của app.metrics nhận list[int]; các field dùng nhánh này
                # (latency_ms, ttft_ms) luôn là số nguyên trong log nên ép kiểu là chính xác.
                points.append(percentile([int(v) for v in values], int(agg[1:])))
        return points

    def count_series(event_name: str) -> list[float | None]:
        grouped: Counter[int] = Counter()
        for record in events(current, event_name):
            ts = parse_ts(record.get("ts"))
            if ts is not None:
                grouped[bucket_index(ts, start)] += 1
        return [float(grouped[index]) if grouped[index] else None for index in range(len(buckets))]

    # -- panel 1: latency ---------------------------------------------------
    sent = events(current, "response_sent")
    latencies = [int(r["latency_ms"]) for r in sent if is_number(r.get("latency_ms"))]
    ttfts = [int(r["ttft_ms"]) for r in sent if is_number(r.get("ttft_ms"))]
    p50, p95, p99 = (percentile(latencies, p) for p in (50, 95, 99))
    ttft_p95 = percentile(ttfts, 95)
    _, _, lat_threshold, lat_unit = THRESHOLDS["latency"]
    latency_panel = panel(
        "latency",
        "Latency & TTFT",
        "Request có chậm không? P50/P95/P99 và TTFT đang ở mức nào?",
        "ms",
        bar_chart(
            buckets,
            [("latency P95 theo phút", COLORS["primary"], series_for("response_sent", "latency_ms", "p95"))],
            threshold=lat_threshold,
            operator="lte",
            unit="ms",
        ),
        stat("P50", fmt(p50, 0, " ms")) + stat("P95", fmt(p95, 0, " ms"), p95 <= lat_threshold)
        + stat("P99", fmt(p99, 0, " ms")) + stat("TTFT P95", fmt(ttft_p95, 0, " ms")),
    )

    # -- panel 2: traffic ---------------------------------------------------
    traffic_points = count_series("request_received")
    observed = [v for v in traffic_points if v is not None]
    rate = sum(observed) / len(observed) if observed else 0.0
    traffic_panel = panel(
        "traffic",
        "Traffic",
        "Hệ thống đang nhận bao nhiêu request theo thời gian?",
        "request/phút",
        bar_chart(
            buckets,
            [("request nhận được", COLORS["primary"], traffic_points)],
            threshold=1.0,
            operator="gte",
            unit="req/phút",
        ),
        stat("Tổng request", f"{int(sum(observed))}")
        + stat("Rate trung bình", fmt(rate, 2, " req/phút"), rate >= 1.0)
        + stat("Số phút có dữ liệu", f"{len(observed)}/{len(buckets)}"),
    )

    # -- panel 3: errors + retrieval success --------------------------------
    failed = events(current, "request_failed")
    received = events(current, "request_received")
    error_rate = (100.0 * len(failed) / len(received)) if received else 0.0
    error_points: list[float | None] = []
    failed_by_minute = Counter(
        bucket_index(ts, start) for ts in (parse_ts(r.get("ts")) for r in failed) if ts is not None
    )
    received_by_minute = Counter(
        bucket_index(ts, start) for ts in (parse_ts(r.get("ts")) for r in received) if ts is not None
    )
    for index in range(len(buckets)):
        total = received_by_minute.get(index, 0)
        if not total:
            error_points.append(None)
        else:
            error_points.append(round(100.0 * failed_by_minute.get(index, 0) / total, 2))

    # Retrieval success lấy trên MỌI event có field tool_success (cả response_sent
    # lẫn request_failed), nếu chỉ lấy request_failed thì luôn ra 0%.
    tool_records = [r for r in current if isinstance(r.get("tool_success"), bool)]
    retrieval_pct = (
        100.0 * sum(1 for r in tool_records if r["tool_success"]) / len(tool_records)
        if tool_records
        else None
    )
    breakdown = Counter(r.get("error_type") for r in failed)
    breakdown_text = (
        ", ".join(f"{key}×{count}" for key, count in sorted(breakdown.items(), key=lambda item: str(item[0])))
        if breakdown
        else "không có lỗi"
    )
    errors_panel = panel(
        "errors",
        "Errors & retrieval success",
        "Error rate có tăng không, retrieval có đang fail không?",
        "%",
        bar_chart(
            buckets,
            [("error rate theo phút", COLORS["bad"], error_points)],
            threshold=2.0,
            operator="lte",
            unit="%",
        ),
        stat("Error rate", fmt(error_rate, 2, " %"), error_rate <= 2.0)
        + stat("Số request lỗi", str(len(failed)))
        + stat("Retrieval success", fmt(retrieval_pct, 1, " %"),
               None if retrieval_pct is None else retrieval_pct >= 90.0)
        + stat("Lỗi theo loại", breakdown_text),
    )

    # -- panel 4: cost ------------------------------------------------------
    # Threshold của contract là `total` (tổng cả cửa sổ), nên panel vẽ chuỗi
    # tích luỹ để đường threshold so sánh được với dữ liệu.
    cost_points = series_for("response_sent", "cost_usd", "sum")
    cost_total = sum(v for v in cost_points if v is not None)
    cost_panel = panel(
        "cost",
        "Cost",
        "Chi phí có tăng bất thường không?",
        "USD",
        bar_chart(
            buckets,
            [("cost tích luỹ trong cửa sổ", COLORS["secondary"], cost_points)],
            threshold=2.5,
            operator="lte",
            unit="USD",
            mode="cumulative",
            threshold_scope=" (tổng cả cửa sổ)",
        ),
        stat("Tổng cost", fmt(cost_total, 4, " USD"), cost_total <= 2.5)
        + stat("Cost/request", fmt(cost_total / len(sent) if sent else None, 6, " USD")),
    )

    # -- panel 5: tokens ----------------------------------------------------
    # Cùng lý do như cost: threshold `sum_by_field` áp cho tổng cả cửa sổ.
    tokens_in = series_for("response_sent", "tokens_in", "sum")
    tokens_out = series_for("response_sent", "tokens_out", "sum")
    sum_in = sum(v for v in tokens_in if v is not None)
    sum_out = sum(v for v in tokens_out if v is not None)
    tokens_panel = panel(
        "tokens",
        "Tokens",
        "Input/output token có dài bất thường không?",
        "token",
        legend([("input (tích luỹ)", COLORS["primary"], []), ("output (tích luỹ)", COLORS["secondary"], [])])
        + bar_chart(
            buckets,
            [("input", COLORS["primary"], tokens_in), ("output", COLORS["secondary"], tokens_out)],
            threshold=50000.0,
            operator="lte",
            unit="token",
            mode="cumulative",
            threshold_scope=" (input+output, cả cửa sổ)",
        ),
        stat("Tổng input", f"{int(sum_in):,}") + stat("Tổng output", f"{int(sum_out):,}")
        + stat("Tổng cộng", f"{int(sum_in + sum_out):,}", (sum_in + sum_out) <= 50000),
    )

    # -- panel 6: quality ---------------------------------------------------
    quality_points = series_for("response_sent", "quality_score", "mean")
    quality_values = [r["quality_score"] for r in sent if is_number(r.get("quality_score"))]
    quality_mean = sum(quality_values) / len(quality_values) if quality_values else None
    quality_panel = panel(
        "quality",
        "Quality proxy",
        "Quality proxy có giảm dưới mức chấp nhận được không?",
        "điểm 0–1",
        bar_chart(
            buckets,
            [("quality trung bình theo phút", COLORS["ok"], quality_points)],
            threshold=0.75,
            operator="gte",
            unit="điểm",
        ),
        stat("Quality trung bình", fmt(quality_mean, 3),
             None if quality_mean is None else quality_mean >= 0.75)
        + stat("Số câu trả lời", str(len(quality_values))),
    )

    note_html = f'<p class="note">{note}</p>' if note else ""

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>Day 13 Monitoring &amp; LLMOps dashboard</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 20px 24px 32px; background: #f3f4f6; color: {COLORS["ink"]};
         font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  h1 {{ font-size: 19px; margin: 0 0 4px; }}
  .sub {{ color: {COLORS["muted"]}; font-size: 12px; margin: 0 0 6px; }}
  .note {{ font-size: 12.5px; font-weight: 600; color: #7f1d1d; background: #fef2f2;
           border: 1px solid #fecaca; border-radius: 7px; padding: 6px 10px; margin: 0 0 14px; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }}
  .panel {{ background: #fff; border: 1px solid {COLORS["grid"]}; border-radius: 10px; padding: 12px 14px 8px; }}
  .panel h2 {{ font-size: 14px; margin: 0; }}
  .panel .q {{ color: {COLORS["muted"]}; font-size: 11px; margin: 3px 0 0; }}
  .unit {{ display: inline-block; margin-top: 5px; font-size: 10px; color: {COLORS["muted"]};
           background: #f9fafb; border: 1px solid {COLORS["grid"]}; border-radius: 999px; padding: 1px 7px; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px; }}
  .stat {{ background: #f9fafb; border: 1px solid {COLORS["grid"]}; border-radius: 7px;
           padding: 5px 8px; min-width: 86px; }}
  .stat-ok {{ border-color: #bbf7d0; background: #f0fdf4; }}
  .stat-bad {{ border-color: #fecaca; background: #fef2f2; }}
  .stat-label {{ display: block; font-size: 9.5px; text-transform: uppercase;
                 letter-spacing: .04em; color: {COLORS["muted"]}; }}
  .stat-value {{ display: block; font-size: 13px; font-weight: 600; }}
  .legend {{ font-size: 10px; color: {COLORS["muted"]}; margin: 4px 0 0; }}
  .legend-item {{ margin-right: 10px; }}
  .legend-item i {{ display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 4px; }}
  footer {{ margin-top: 16px; font-size: 11px; color: {COLORS["muted"]}; }}
  code {{ background: #eef2ff; padding: 1px 4px; border-radius: 4px; }}
</style>
</head>
<body>
  <h1>Day 13 — Monitoring &amp; LLMOps dashboard</h1>
  <p class="sub">
    Nguồn dữ liệu: <code>{display_path(log_path)}</code>
    &nbsp;•&nbsp; Cửa sổ: {WINDOW_MINUTES} phút ({start.strftime("%H:%M")}–{end.strftime("%H:%M")} UTC, dữ liệu thực tế
    {len([v for v in traffic_points if v is not None])} phút)
    &nbsp;•&nbsp; Tự refresh mỗi {REFRESH_SECONDS}s
    &nbsp;•&nbsp; {len(current)} bản ghi trong cửa sổ
    &nbsp;•&nbsp; sinh lúc {generated}
  </p>
  {note_html}
  <div class="grid">
    {latency_panel}
    {traffic_panel}
    {errors_panel}
    {cost_panel}
    {tokens_panel}
    {quality_panel}
  </div>
  <footer>
    Threshold lấy theo <code>config/dashboard.yaml</code>: latency P95 ≤ 3000 ms · traffic ≥ 1 req/phút ·
    error rate ≤ 2 % · tổng cost ≤ 2.5 USD · tổng token ≤ 50000 · quality ≥ 0.75.
    Trường <code>ts</code> trong log là giờ UTC.
  </footer>
</body>
</html>
"""


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ data/logs.jsonl")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--note", default="", help="Dòng chú thích ở đầu dashboard, ví dụ challenge ID")
    args = parser.parse_args()

    records = load_records(args.log)
    html = build_html(records, args.log, args.note)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    start, end, current = window_of(records)
    print(f"Đã ghi dashboard: {args.out}")
    print(f"Bản ghi đọc được: {len(records)} | trong cửa sổ {WINDOW_MINUTES} phút: {len(current)}")
    if start and end:
        print(f"Cửa sổ: {start.isoformat()} → {end.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
