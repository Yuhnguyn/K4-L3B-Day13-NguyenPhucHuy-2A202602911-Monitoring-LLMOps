from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

REQUEST_ID_HEADER = "x-request-id"
RESPONSE_TIME_HEADER = "x-response-time-ms"

# Chỉ nhận x-request-id do client gửi nếu là một token ngắn, không khoảng trắng
# và không ký tự xuống dòng (chặn log injection qua header).
_INCOMING_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")


def generate_correlation_id() -> str:
    """Sinh correlation ID theo format ``req-<8-hex>``."""
    return f"req-{uuid.uuid4().hex[:8]}"


def resolve_correlation_id(incoming: str | None) -> str:
    """Dùng lại ``x-request-id`` hợp lệ của client, ngược lại sinh ID mới."""
    if incoming:
        candidate = incoming.strip()
        if _INCOMING_ID_PATTERN.fullmatch(candidate):
            return candidate
    return generate_correlation_id()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Xóa context của request trước để request mới không thừa hưởng
        # correlation_id / metadata của request cũ.
        clear_contextvars()

        # Nhận x-request-id từ client hoặc sinh mới, rồi bind vào contextvars
        # để mọi dòng log trong request này tự động mang cùng một ID.
        correlation_id = resolve_correlation_id(request.headers.get(REQUEST_ID_HEADER))
        bind_contextvars(correlation_id=correlation_id)

        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        # Trả ID và thời gian xử lý về client để nối response với log/trace.
        response.headers[REQUEST_ID_HEADER] = correlation_id
        response.headers[RESPONSE_TIME_HEADER] = str(elapsed_ms)

        return response
