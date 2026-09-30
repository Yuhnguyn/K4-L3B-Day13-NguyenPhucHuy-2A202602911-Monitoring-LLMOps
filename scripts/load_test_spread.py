"""Gửi request rải đều theo thời gian để dashboard có đủ điểm dữ liệu theo phút.

`load_test.py` bắn toàn bộ query trong vài giây, nên biểu đồ theo phút chỉ có một
cột. Script này giữ cùng bộ input nhưng rắc request ra nhiều phút, phù hợp để tạo
dữ liệu cho 6 panel của dashboard (xem docs/DASHBOARD_SETUP.md).

Ví dụ:
    python scripts/load_test_spread.py --minutes 12 --interval 22
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

BASE_URL = "http://127.0.0.1:8000"
QUERIES = Path("data/sample_queries.jsonl")


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Rải request theo thời gian cho dashboard")
    parser.add_argument("--minutes", type=float, default=12.0, help="Tổng thời gian chạy")
    parser.add_argument("--interval", type=float, default=22.0, help="Giây giữa hai request")
    parser.add_argument("--seed", type=int, default=1313, help="Seed để chọn query lặp lại được")
    args = parser.parse_args()

    payloads = [
        json.loads(line)
        for line in QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rng = random.Random(args.seed)
    deadline = time.monotonic() + args.minutes * 60
    sent = 0

    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            payload = dict(rng.choice(payloads))
            # Đổi session theo từng vòng để log có nhiều session khác nhau như thật.
            payload["session_id"] = f"{payload['session_id']}-run{sent // len(payloads) + 1}"
            try:
                response = client.post(f"{BASE_URL}/chat", json=payload)
                print(
                    f"[{response.status_code}] {response.json().get('correlation_id')} "
                    f"| {payload['feature']} | {payload['message'][:44]}"
                )
            except Exception as exc:  # giữ script chạy tiếp nếu một request lỗi
                print(f"Error: {exc}")
            sent += 1
            time.sleep(args.interval)

    print(f"Đã gửi {sent} request trong {args.minutes} phút.")


if __name__ == "__main__":
    main()
