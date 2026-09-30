"""Kiểm thử dashboard 6 panel: contract, định dạng số và nhánh lỗi.

Dùng log tổng hợp thay vì `data/logs.jsonl` vì file log thật là dữ liệu runtime
(không commit) và workload sạch không có request lỗi — nhánh error rate / retrieval
success sẽ không bao giờ được chạy nếu chỉ dựa vào log thật.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import dashboard as dash

PANEL_IDS = ("latency", "traffic", "errors", "cost", "tokens", "quality")
BASE_FIELDS = {
    "latency_ms": 150,
    "ttft_ms": 50,
    "tokens_in": 100,
    "tokens_out": 200,
    "cost_usd": 0.0033,
    "quality_score": 0.85,
    "tool_name": "retrieval",
}


def event(name: str, ts: str, **fields: object) -> dict:
    return {
        "ts": ts,
        "level": "info",
        "service": "api",
        "event": name,
        "correlation_id": "req-test0001",
        **fields,
    }


@pytest.fixture
def log_records() -> list[dict]:
    """Ba phút dữ liệu, trong đó một request lỗi để phủ nhánh lỗi."""
    return [
        event("request_received", "2026-09-30T05:00:00Z"),
        event("response_sent", "2026-09-30T05:00:01Z", tool_success=True, **BASE_FIELDS),
        event("request_received", "2026-09-30T05:01:00Z"),
        event("response_sent", "2026-09-30T05:01:01Z", tool_success=True, **BASE_FIELDS),
        event("request_received", "2026-09-30T05:02:00Z"),
        event(
            "request_failed",
            "2026-09-30T05:02:01Z",
            error_type="RuntimeError",
            tool_success=False,
            **BASE_FIELDS,
        ),
    ]


@pytest.fixture
def html(log_records: list[dict]) -> str:
    return dash.build_html(log_records, Path("data/logs.jsonl"))


def test_fmt_num_keeps_precision() -> None:
    assert dash._fmt_num(3000) == "3,000"
    assert dash._fmt_num(2.5) == "2.5"
    assert dash._fmt_num(0.75) == "0.75"


def test_nice_ceil_rounds_to_readable_steps() -> None:
    assert dash._nice_ceil(3300) == 5000
    assert dash._nice_ceil(0.825) == 1.0


def test_cumulative_keeps_running_total_through_gaps() -> None:
    assert dash.cumulative([1.0, None, 2.0]) == [1.0, 1.0, 3.0]


def test_display_path_handles_logs_outside_the_repo(tmp_path: Path) -> None:
    assert dash.display_path(dash.REPO_ROOT / "data" / "logs.jsonl") == "data/logs.jsonl"
    outside = tmp_path / "logs.jsonl"
    assert dash.display_path(outside) == str(outside)


def test_dashboard_renders_the_six_contract_panels(html: str) -> None:
    assert html.count('class="panel"') == 6
    for panel_id in PANEL_IDS:
        assert f'id="{panel_id}"' in html


def test_dashboard_declares_window_and_refresh(html: str) -> None:
    assert 'http-equiv="refresh" content="30"' in html
    assert "Cửa sổ: 60 phút" in html


def test_threshold_labels_keep_decimal_values(html: str) -> None:
    # regression: định dạng :,.0f từng in 2.5 thành "3" và 0.75 thành "1"
    assert "threshold lte 2.5 USD" in html
    assert "threshold gte 0.75 điểm" in html


def test_data_region_counts_only_minutes_with_data(html: str) -> None:
    # regression: chuỗi tích luỹ của cost/tokens từng làm vùng dữ liệu phủ hết 60 phút
    assert "vùng có dữ liệu (3 phút)" in html
    assert "vùng có dữ liệu (60 phút)" not in html


def test_error_rate_and_retrieval_success_path(html: str) -> None:
    assert "33.33 %" in html  # 1 request lỗi trên 3 request nhận được
    assert "RuntimeError×1" in html
    assert "66.7 %" in html  # 2/3 event có field tool_success
    assert "không có lỗi" not in html


def test_note_is_optional_and_escaped(log_records: list[dict]) -> None:
    plain = dash.build_html(log_records, Path("data/logs.jsonl"))
    assert 'class="note"' not in plain

    noted = dash.build_html(log_records, Path("data/logs.jsonl"), "challenge <a> & b")
    assert "challenge &lt;a&gt; &amp; b" in noted


def test_empty_log_renders_placeholder() -> None:
    assert "Chưa có dữ liệu" in dash.build_html([], Path("data/logs.jsonl"))
