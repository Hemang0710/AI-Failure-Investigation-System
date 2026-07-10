"""PII redaction for ingested LLM prompts and responses.

Prompts and responses routinely carry personal data - emails, phone numbers,
payment details, secrets pasted into a chat. An observability store that keeps
them verbatim forever is a liability, so redaction runs at ingestion, before
anything is written to the database. It is regex-based (no heavyweight NLP
dependency) and covers high-signal, structured identifiers; free-form names
and addresses are out of scope and documented as such in SECURITY.md.

Configuration (environment):
  PII_REDACTION_ENABLED   "true"/"false"  (default: true)
  PII_REDACTION_TYPES     comma list of detector names to apply
                          (default: all - email,credit_card,ssn,phone,ip,api_key)
"""

import os
import re
from typing import List, Optional

# Each detector: name -> (compiled pattern, placeholder, optional validator).
# A validator receives the matched string and returns True to redact; it lets
# us confirm a match (e.g. Luhn for cards) before destroying data.


def _luhn_ok(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


_DETECTORS = {
    "email": (
        re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        "[REDACTED_EMAIL]",
        None,
    ),
    # Card-shaped runs of 13-19 digits with optional space/dash grouping,
    # confirmed with a Luhn check so ordinary long numbers are left alone.
    "credit_card": (
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        "[REDACTED_CC]",
        _luhn_ok,
    ),
    "ssn": (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[REDACTED_SSN]",
        None,
    ),
    "phone": (
        re.compile(
            r"(?<!\w)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\w)"
        ),
        "[REDACTED_PHONE]",
        None,
    ),
    "ip": (
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
        "[REDACTED_IP]",
        None,
    ),
    # Common secret shapes: provider keys (sk-/pk-/rk-...), AWS access key ids,
    # GitHub tokens, and long JWTs.
    "api_key": (
        re.compile(
            r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b"
            r"|\bAKIA[0-9A-Z]{16}\b"
            r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
            r"|\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
        ),
        "[REDACTED_KEY]",
        None,
    ),
}


def _load_config():
    enabled = os.getenv("PII_REDACTION_ENABLED", "true").lower() == "true"
    raw = os.getenv("PII_REDACTION_TYPES", "").strip()
    if raw:
        selected = [t.strip() for t in raw.split(",") if t.strip()]
        unknown = [t for t in selected if t not in _DETECTORS]
        if unknown:
            raise ValueError(f"Unknown PII_REDACTION_TYPES: {', '.join(unknown)}")
    else:
        selected = list(_DETECTORS)
    return enabled, [(name, *_DETECTORS[name]) for name in selected]


_ENABLED, _ACTIVE = _load_config()


def redact_text(text: Optional[str]) -> Optional[str]:
    """Return `text` with configured PII patterns replaced by placeholders."""
    if not _ENABLED or not text:
        return text
    result = text
    for _name, pattern, placeholder, validator in _ACTIVE:
        if validator is None:
            result = pattern.sub(placeholder, result)
        else:
            result = pattern.sub(
                lambda m: placeholder if validator(m.group(0)) else m.group(0),
                result,
            )
    return result


def redact_list(items: Optional[List[str]]) -> Optional[List[str]]:
    """Redact each string in a list (e.g. retrieved documents)."""
    if not _ENABLED or not items:
        return items
    return [redact_text(item) for item in items]
