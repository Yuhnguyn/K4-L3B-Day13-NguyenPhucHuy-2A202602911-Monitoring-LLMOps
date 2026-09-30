from __future__ import annotations

import hashlib
import re

# Thứ tự pattern quan trọng: các pattern số dài (phone, cccd, credit card) phải
# chạy trước các pattern số ngắn để không bị cắt thành mảnh nhỏ.
PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    "cccd": r"\b\d{12}\b",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    # CMND 9 số (giấy tờ cũ, trước CCCD 12 số).
    "cmnd": r"(?<!\d)\d{9}(?!\d)",
    # Hộ chiếu phổ thông Việt Nam: 1 chữ cái + 7 chữ số, ví dụ B1234567.
    "passport_vn": r"\b[A-Za-z]\d{7}\b",
}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in PII_PATTERNS.items():
        safe = re.sub(pattern, f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
