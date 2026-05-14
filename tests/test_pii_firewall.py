"""Tests for the PII firewall (Brief 2b.1)."""

from __future__ import annotations

import pytest

from scripts.pii_firewall import screen


# ---------------------------------------------------------------------------
# Clean inputs — must pass
# ---------------------------------------------------------------------------

class TestCleanInputs:
    def test_empty_string_passes(self):
        blocked, reason = screen("")
        assert not blocked

    def test_generic_legal_question_passes(self):
        blocked, _ = screen("What is the standard indemnification cap for a $25M acquisition?")
        assert not blocked

    def test_generic_mac_question_passes(self):
        blocked, _ = screen("Explain the MAC definition in a typical SPA.")
        assert not blocked

    def test_thousands_separator_under_1k_passes(self):
        blocked, _ = screen("The fee is $999.")
        assert not blocked

    def test_generic_percentage_passes(self):
        blocked, _ = screen("Rep and warranty cap is 20% of purchase price.")
        assert not blocked


# ---------------------------------------------------------------------------
# SSN patterns — must block
# ---------------------------------------------------------------------------

class TestSSN:
    def test_hyphen_separated_ssn(self):
        blocked, reason = screen("SSN: 123-45-6789")
        assert blocked
        assert "SSN" in reason

    def test_space_separated_ssn(self):
        blocked, reason = screen("Social security: 123 45 6789")
        assert blocked

    def test_no_false_positive_on_dates(self):
        blocked, _ = screen("Signed on 2024-05-13 at 11:30.")
        assert not blocked

    def test_no_false_positive_on_zip_plus4(self):
        blocked, _ = screen("Address: New York, NY 10001-1234")
        assert not blocked


# ---------------------------------------------------------------------------
# EIN patterns — must block
# ---------------------------------------------------------------------------

class TestEIN:
    def test_ein_format(self):
        blocked, reason = screen("EIN: 12-3456789")
        assert blocked
        assert "EIN" in reason


# ---------------------------------------------------------------------------
# Email patterns — must block
# ---------------------------------------------------------------------------

class TestEmail:
    def test_standard_email(self):
        blocked, reason = screen("Contact me at alice@lawfirm.com")
        assert blocked
        assert "email" in reason

    def test_email_in_longer_text(self):
        blocked, _ = screen("For questions send an email to bob.jones+legal@bigfirm.org thanks")
        assert blocked


# ---------------------------------------------------------------------------
# Phone patterns — must block
# ---------------------------------------------------------------------------

class TestPhone:
    def test_dashes_format(self):
        blocked, reason = screen("Call us at 212-555-1234")
        assert blocked
        assert "phone" in reason

    def test_parentheses_format(self):
        blocked, _ = screen("Phone: (212) 555-0100")
        assert blocked

    def test_dots_format(self):
        blocked, _ = screen("212.555.6789")
        assert blocked

    def test_no_false_positive_on_section_numbers(self):
        blocked, _ = screen("See Section 9.3.1 of the agreement.")
        assert not blocked


# ---------------------------------------------------------------------------
# Credit card patterns — must block
# ---------------------------------------------------------------------------

class TestCreditCard:
    def test_visa_card(self):
        blocked, reason = screen("Card: 4111 1111 1111 1111")
        assert blocked
        assert "credit_card" in reason

    def test_mastercard(self):
        blocked, _ = screen("5500 0000 0000 0004")
        assert blocked

    def test_amex(self):
        blocked, _ = screen("3714 496353 98431")
        assert blocked


# ---------------------------------------------------------------------------
# Dollar amount ≥ $1,000 — must block
# ---------------------------------------------------------------------------

class TestDollarAmounts:
    def test_comma_formatted_1k(self):
        blocked, reason = screen("The fee is $1,000.")
        assert blocked
        assert "dollar_amount_1k_plus" in reason

    def test_million_amount(self):
        blocked, _ = screen("Deal value: $25,000,000")
        assert blocked

    def test_billion_amount(self):
        blocked, _ = screen("Acquisition price: $1,200,000,000")
        assert blocked

    def test_amount_with_cents(self):
        blocked, _ = screen("Invoice: $2,500.00")
        assert blocked


# ---------------------------------------------------------------------------
# Case number patterns — must block
# ---------------------------------------------------------------------------

class TestCaseNumbers:
    def test_sdny_style(self):
        blocked, reason = screen("Filed in 1:24-cv-00503")
        assert blocked
        assert "case_number" in reason

    def test_cr_docket(self):
        blocked, _ = screen("Indictment: 25-cr-00503-JSR")
        assert blocked

    def test_case_no_prefix(self):
        blocked, _ = screen("Case No. 2024-12345 pending in court")
        assert blocked


# ---------------------------------------------------------------------------
# Trigger phrases — must block
# ---------------------------------------------------------------------------

class TestTriggerPhrases:
    @pytest.mark.parametrize("phrase,text", [
        ("my client", "my client signed the agreement"),
        ("our client", "our client is disputing the clause"),
        ("i represent", "i represent acme corp in this matter"),
        ("we represent", "we represent the buyer in the transaction"),
        ("on behalf of", "on behalf of the seller we object"),
        ("privileged and confidential", "privileged and confidential: attorney memo"),
        ("attorney-client", "this is protected by attorney-client privilege"),
        ("work product", "this document is work product"),
        ("retainer agreement", "our retainer agreement provides"),
    ])
    def test_trigger_phrase_blocked(self, phrase, text):
        blocked, reason = screen(text)
        assert blocked, f"Expected block for phrase: {phrase!r}"
        assert "TRIGGER" in reason

    def test_case_insensitive_trigger(self):
        blocked, reason = screen("MY CLIENT wants to know the indemnification cap.")
        assert blocked

    def test_partial_word_no_false_positive(self):
        # "our" alone shouldn't trip "our client"
        blocked, _ = screen("Our standard practice in M&A diligence is to review all reps.")
        assert not blocked


# ---------------------------------------------------------------------------
# screen() return contract
# ---------------------------------------------------------------------------

class TestScreenContract:
    def test_clean_returns_false_none(self):
        blocked, reason = screen("What is a MAC clause?")
        assert blocked is False
        assert reason is None

    def test_blocked_returns_true_with_reason_string(self):
        blocked, reason = screen("Call 555-123-4567")
        assert blocked is True
        assert isinstance(reason, str)
        assert len(reason) > 0
