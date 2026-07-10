"""Unit tests for PII redaction detectors."""

import pytest

import redaction


@pytest.mark.parametrize(
    "text, placeholder",
    [
        ("reach me at jane.doe@example.com", "[REDACTED_EMAIL]"),
        ("card 4111 1111 1111 1111 on file", "[REDACTED_CC]"),   # Luhn-valid
        ("ssn 123-45-6789", "[REDACTED_SSN]"),
        ("call +1 415-555-0132 now", "[REDACTED_PHONE]"),
        ("server at 192.168.1.100", "[REDACTED_IP]"),
        ("token sk-abcdef0123456789ABCDEF", "[REDACTED_KEY]"),
        ("AKIAIOSFODNN7EXAMPLE", "[REDACTED_KEY]"),
    ],
)
def test_detectors_redact(text, placeholder):
    out = redaction.redact_text(text)
    assert placeholder in out


def test_non_luhn_number_not_treated_as_card():
    # 1234567812345678 fails the Luhn checksum.
    assert "[REDACTED_CC]" not in redaction.redact_text("order 1234567812345678")


def test_clean_text_unchanged():
    text = "The quick brown fox jumps over 3 lazy dogs."
    assert redaction.redact_text(text) == text


def test_multiple_pii_in_one_string():
    out = redaction.redact_text("email a@b.com or call 415-555-0199")
    assert "[REDACTED_EMAIL]" in out
    assert "[REDACTED_PHONE]" in out


def test_redact_list_applies_per_item():
    out = redaction.redact_list(["doc from alice@corp.com", "clean doc"])
    assert out[0] == "doc from [REDACTED_EMAIL]"
    assert out[1] == "clean doc"


def test_none_and_empty_are_passthrough():
    assert redaction.redact_text(None) is None
    assert redaction.redact_text("") == ""
    assert redaction.redact_list(None) is None
