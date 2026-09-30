from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Callable

try:
    from langfuse import get_client, observe, propagate_attributes

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyClient:
        def update_current_span(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


def get_langfuse_client():
    return get_client()


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )


@contextmanager
def child_observation(client: Any, *, as_type: str, name: str, **kwargs: Any):
    """Mở child observation (span/generation) cho một bước nhỏ của request.

    Nhờ nó, waterfall trên Langfuse tách được thời gian retrieval và LLM thay vì
    chỉ có một root observation. Hàm trả về ``None`` khi client không hỗ trợ API
    observation (Langfuse tắt, SDK chưa cài, hoặc client giả trong test) để app
    vẫn chạy bình thường và không cần rẽ nhánh ở nơi gọi.
    """
    starter: Callable[..., Any] | None = getattr(
        client, "start_as_current_observation", None
    )
    if not callable(starter):
        yield None
        return
    with starter(as_type=as_type, name=name, **kwargs) as observation:
        yield observation


def update_observation(observation: Any, **kwargs: Any) -> None:
    """Ghi model/token/cost/output vào observation vừa tạo; bỏ qua an toàn nếu rỗng."""
    updater = getattr(observation, "update", None)
    if callable(updater):
        updater(**kwargs)
