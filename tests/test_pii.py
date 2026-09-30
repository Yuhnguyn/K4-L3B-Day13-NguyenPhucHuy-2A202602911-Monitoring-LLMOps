from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_email_variants() -> None:
    emails = (
        "student@vinuni.edu.vn",
        "nguyen.phuc.huy+lab@example.com",
        "user01@sub.domain.co.uk",
    )

    for email in emails:
        out = scrub_text(f"Mail to {email} please")
        assert email not in out
        assert "REDACTED_EMAIL" in out


def test_scrub_cccd_12_digits() -> None:
    out = scrub_text("So CCCD cua toi la 001202012345")

    assert "001202012345" not in out
    assert "REDACTED_CCCD" in out


def test_scrub_credit_card_keeps_layout_variants() -> None:
    cards = (
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "4111111111111111",
    )

    for card in cards:
        out = scrub_text(f"The card number is {card}")
        assert card not in out
        assert "REDACTED_CREDIT_CARD" in out


def test_scrub_cmnd_and_passport() -> None:
    cmnd = scrub_text("CMND cu: 123456789")
    assert "123456789" not in cmnd
    assert "REDACTED_CMND" in cmnd

    passport = scrub_text("Ho chieu B1234567 het han 2030")
    assert "B1234567" not in passport
    assert "REDACTED_PASSPORT_VN" in passport


def test_phone_is_not_split_into_cmnd_redaction() -> None:
    out = scrub_text("Goi 0901234567 gap toi")

    assert "0901234567" not in out
    assert "REDACTED_PHONE_VN" in out
    assert "REDACTED_CMND" not in out


def test_safe_identifiers_are_left_untouched() -> None:
    safe = "req-12345678 model claude-sonnet-4-5 feature qa"
    assert scrub_text(safe) == safe

