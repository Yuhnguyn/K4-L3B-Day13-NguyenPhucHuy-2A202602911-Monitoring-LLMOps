from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.main import app

GENERATED_ID_PATTERN = re.compile(r"req-[0-9a-f]{8}")
PAYLOAD = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "Explain observability",
}


def _send(payload: dict, headers: dict[str, str] | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post("/chat", json=payload, headers=headers)

    return asyncio.run(send())


def _read_records(log_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_generates_correlation_id_and_returns_it_with_timing(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = _send(PAYLOAD)

    assert response.status_code == 200
    correlation_id = response.headers["x-request-id"]
    assert GENERATED_ID_PATTERN.fullmatch(correlation_id), correlation_id
    assert correlation_id == response.json()["correlation_id"]
    assert int(response.headers["x-response-time-ms"]) >= 0

    records = _read_records(log_path)
    assert records
    assert {record["correlation_id"] for record in records} == {correlation_id}


def test_reuses_client_supplied_request_id(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = _send(PAYLOAD, headers={"x-request-id": "req-abcdef01"})

    assert response.headers["x-request-id"] == "req-abcdef01"
    assert {record["correlation_id"] for record in _read_records(log_path)} == {
        "req-abcdef01"
    }


def test_replaces_unsafe_client_request_id(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = _send(PAYLOAD, headers={"x-request-id": "  not a safe request id  "})

    correlation_id = response.headers["x-request-id"]
    assert GENERATED_ID_PATTERN.fullmatch(correlation_id), correlation_id


def test_log_context_does_not_leak_between_requests(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    first = _send(PAYLOAD)
    second = _send({**PAYLOAD, "user_id": "student-02", "session_id": "session-02"})

    first_id = first.headers["x-request-id"]
    second_id = second.headers["x-request-id"]
    assert first_id != second_id

    records = _read_records(log_path)
    by_id: dict[str, list[dict]] = {}
    for record in records:
        by_id.setdefault(record["correlation_id"], []).append(record)

    assert set(by_id) == {first_id, second_id}
    assert sorted(record["event"] for record in by_id[first_id]) == [
        "request_received",
        "response_sent",
    ]
    assert {record["session_id"] for record in by_id[first_id]} == {"session-01"}
    assert {record["session_id"] for record in by_id[second_id]} == {"session-02"}
    assert {record["user_id_hash"] for record in by_id[first_id]} != {
        record["user_id_hash"] for record in by_id[second_id]
    }
    for record in records:
        assert record["feature"] == "qa"
        assert record["model"]
        assert record["env"]
        assert record["user_id_hash"] != "student-01" and record["user_id_hash"] != "student-02"
