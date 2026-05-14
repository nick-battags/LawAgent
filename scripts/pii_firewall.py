"""PII regex firewall for the LawAgent demo.

screen(text) -> (blocked: bool, reason: str | None)

Blocks on:
  - 7 structural PII patterns (SSN, phone, email, credit card,
    dollar amounts ≥$1K, case numbers, EIN)
  - 9 client-engagement trigger phrases that signal real legal matter intake

Call screen() before every LLM call and before any Supermemory write.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns — ordered: faster/more-specific first
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "SSN",
        re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
    ),
    (
        "EIN",
        re.compile(r"\b\d{2}-\d{7}\b"),
    ),
    (
        "credit_card",
        re.compile(
            r"\b(?:"
            r"3[47]\d{2}[- ]?\d{6}[- ]?\d{5}"            # Amex: 4-6-5 = 15 digits
            r"|(?:4\d{3}|5[1-5]\d{2}|6(?:011|5\d{2}))[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}"  # Visa/MC/Discover: 4-4-4-4
            r")\b"
        ),
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "phone",
        re.compile(
            r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)"
        ),
    ),
    (
        "dollar_amount_1k_plus",
        # Matches $1,000 through $999,999,999,999 with optional cents
        re.compile(r"\$\s*(?:\d{1,3}(?:,\d{3})+|\d{4,})(?:\.\d{2})?"),
    ),
    (
        "case_number",
        # Federal docket patterns: 1:24-cv-00123, 24-cr-00456-JSR, Case No. 2024-12345
        re.compile(
            r"(?i)"
            r"(?:\d{1,2}:\d{2,4}-(?:cv|cr|md|mc|mj|bk|ap)-\d{4,}"  # SDNY-style
            r"|\d{2,4}-(?:cv|cr|md|mc|mj|bk|ap)-\d{4,}"               # shorter docket
            r"|(?:case\s*no\.?\s*)\d{4,5}-\d{4,5}"                    # Case No. NNNNN-NNNNN
            r")"
        ),
    ),
]

# ---------------------------------------------------------------------------
# Trigger phrases — signals of active legal matter intake
# ---------------------------------------------------------------------------

_TRIGGER_PHRASES: list[tuple[str, list[str]]] = [
    (
        "client_engagement",
        [
            "my client",
            "our client",
            "i represent",
            "we represent",
            "on behalf of",
            "privileged and confidential",
            "attorney-client",
            "work product",
            "retainer agreement",
        ],
    ),
]


def screen(text: str) -> tuple[bool, str | None]:
    """Screen text for PII and active-matter trigger phrases.

    Returns:
        (False, None)       — text is clean, proceed
        (True, reason_str)  — blocked; reason_str identifies the pattern

    Always call this before any LLM invocation and before Supermemory writes.
    """
    if not text:
        return False, None

    for name, pattern in _PII_PATTERNS:
        if pattern.search(text):
            return True, f"PII_PATTERN:{name}"

    lower = text.lower()
    for category, phrases in _TRIGGER_PHRASES:
        for phrase in phrases:
            if phrase in lower:
                return True, f"TRIGGER:{category}:{phrase}"

    return False, None
