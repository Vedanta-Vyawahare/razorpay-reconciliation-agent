"""
Regression tests for the reconciliation engine.

Tests verify:
1. Exact match produces high confidence
2. UTR match + amount mismatch produces REVIEW (not UNMATCHED)
3. Missing reference does not zero out confidence
4. Failed settlements are UNMATCHED with 0 confidence
5. Competing candidates trigger REVIEW
6. Confidence is continuous (not binary)
7. Confidence and status are independent concepts
8. Ledger scoring profile does not penalize missing UTR
9. Ledger scoring uses separate weight profile
"""

import pytest
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from matching import match_settlement
from ledger_matching import match_ledger
from ledger_evidence import calculate_ledger_evidence, LEDGER_WEIGHTS
from evidence import reference_score
from config import WEIGHTS


# ============================================================
# RAZORPAY PATH TESTS
# ============================================================

def test_exact_match_high_confidence():
    """TEST A: Exact UTR + exact amount → MATCHED, high confidence."""
    settlement = pd.Series({
        "id": "setl_0001",
        "settlement_utr": "RZP20260601INDB5362",
        "net_amount": 90364.27,
        "settlement_date": pd.to_datetime("2026-06-18"),
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "RZP/20260601INDB5362",
        "bank_amount": 90364.27,
        "bank_date": pd.to_datetime("2026-06-18"),
        "is_credit": True,
        "transaction_type": "NEFT",
        "narration": "DEP TFR/NEFT/CR/RZP/20260601INDB5362",
    }])
    
    result = match_settlement(settlement, bank, set())
    
    assert result["status"] == "MATCHED"
    assert result["confidence"] >= 95.0
    assert result["evidence"]["amount_score"] == 40.0
    assert result["evidence"]["reference_score"] == 35.0


def test_exact_utr_amount_mismatch_is_review():
    """TEST B: Exact UTR + partial payout → REVIEW, meaningful confidence."""
    settlement = pd.Series({
        "id": "setl_0009",
        "settlement_utr": "RZP20260609HDFC8078",
        "net_amount": 133251.98,
        "settlement_date": pd.to_datetime("2026-06-29"),
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "RZP20260609HDFC8078",
        "bank_amount": 73288.59,
        "bank_date": pd.to_datetime("2026-06-29"),
        "is_credit": True,
        "transaction_type": "NEFT",
        "narration": "DEP TFR/NEFT/CR/RZPY/20260609HDFC8078",
    }])
    
    result = match_settlement(settlement, bank, set())
    
    assert result["status"] == "REVIEW"
    assert result["evidence"]["reference_score"] == 35.0
    assert result["evidence"]["amount_score"] == 0.0  # ~45% difference
    assert result["confidence"] > 0.0
    assert result["confidence"] > 50.0  # Reference + date + type should push it above 50


def test_missing_reference_does_not_zero_confidence():
    """TEST C: Missing reference + exact amount/date → still high confidence."""
    settlement = pd.Series({
        "id": "setl_0002",
        "settlement_utr": "RZP20260602HDFC3925",
        "net_amount": 112260.7,
        "settlement_date": pd.to_datetime("2026-06-19"),
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "",
        "bank_amount": 112260.7,
        "bank_date": pd.to_datetime("2026-06-19"),
        "is_credit": True,
        "transaction_type": "NEFT",
        "narration": "SOME VAGUE NARRATION",
    }])
    
    result = match_settlement(settlement, bank, set())
    
    assert result["evidence"]["reference_score"] == 0.0
    assert result["evidence"]["amount_score"] == 40.0
    assert result["evidence"]["date_score"] == 15.0
    # amount(40) + date(15) + type(5) = 60 minimum
    assert result["confidence"] >= 55.0


def test_failed_settlement_is_unmatched():
    """TEST D: Failed settlement → UNMATCHED, confidence 0, no bank consumption."""
    settlement = pd.Series({
        "id": "setl_0030",
        "settlement_utr": "RZP20260630HDFC4457",
        "net_amount": 124258.61,
        "settlement_date": pd.to_datetime("2026-07-24"),
        "status": "failed",
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "RZP20260630HDFC4457",
        "bank_amount": 124258.61,
        "bank_date": pd.to_datetime("2026-07-24"),
        "is_credit": True,
        "transaction_type": "NEFT",
        "narration": "RZP",
    }])
    
    result = match_settlement(settlement, bank, set())
    
    assert result["status"] == "UNMATCHED"
    assert result["confidence"] == 0.0
    assert result["bank_index"] is None


def test_competing_candidates_are_review():
    """TEST E: Two identical candidates → REVIEW."""
    settlement = pd.Series({
        "id": "setl_dup",
        "settlement_utr": "RZP123",
        "net_amount": 1000.00,
        "settlement_date": pd.to_datetime("2026-06-20"),
    })
    
    bank = pd.DataFrame([
        {
            "bank_reference": "RZP123",
            "bank_amount": 1000.00,
            "bank_date": pd.to_datetime("2026-06-20"),
            "is_credit": True,
            "transaction_type": "NEFT",
            "narration": "RZP",
        },
        {
            "bank_reference": "RZP123",
            "bank_amount": 1000.00,
            "bank_date": pd.to_datetime("2026-06-20"),
            "is_credit": True,
            "transaction_type": "NEFT",
            "narration": "RZP",
        },
    ])
    
    result = match_settlement(settlement, bank, set())
    
    assert result["status"] == "REVIEW"
    assert result["ambiguity_type"] == "multiple_strong_candidates"


def test_confidence_is_continuous():
    """Confidence must be a continuous decimal, not 0 or 100."""
    settlement = pd.Series({
        "id": "setl_cont",
        "settlement_utr": "ABC",
        "net_amount": 1000.00,
        "settlement_date": pd.to_datetime("2026-06-20"),
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "ABC",
        "bank_amount": 995.00,
        "bank_date": pd.to_datetime("2026-06-20"),
        "is_credit": True,
        "transaction_type": "UPI",
        "narration": "UNKNOWN",
    }])
    
    result = match_settlement(settlement, bank, set())
    
    # Should NOT be 0 or 100
    assert result["confidence"] > 0.0
    assert result["confidence"] < 100.0
    # It should be a specific decimal value
    assert isinstance(result["confidence"], float)


def test_confidence_does_not_depend_on_status():
    """A REVIEW item can have high confidence; a MATCHED item can have 100."""
    # Case: High confidence REVIEW (competing candidates)
    settlement = pd.Series({
        "id": "setl_high_review",
        "settlement_utr": "XYZ",
        "net_amount": 1000.00,
        "settlement_date": pd.to_datetime("2026-06-20"),
    })
    
    bank = pd.DataFrame([
        {
            "bank_reference": "XYZ",
            "bank_amount": 1000.00,
            "bank_date": pd.to_datetime("2026-06-20"),
            "is_credit": True,
            "transaction_type": "NEFT",
            "narration": "RZP",
        },
        {
            "bank_reference": "XYZ",
            "bank_amount": 1000.00,
            "bank_date": pd.to_datetime("2026-06-20"),
            "is_credit": True,
            "transaction_type": "NEFT",
            "narration": "RZP",
        },
    ])
    
    result = match_settlement(settlement, bank, set())
    
    assert result["status"] == "REVIEW"
    # Confidence should still be meaningful — not 0
    # The ambiguity penalty reduces it from 100, but it stays high
    assert result["confidence"] > 50.0
    # Critically: status is REVIEW but confidence is NOT 0
    assert result["confidence"] != 0.0


# ============================================================
# REFERENCE NORMALIZATION TESTS
# ============================================================

def test_reference_normalization_strips_slashes():
    """RZP20260601INDB5362 and RZP/20260601INDB5362 must match."""
    score = reference_score(
        "RZP20260601INDB5362",
        "RZP/20260601INDB5362",
        ""
    )
    assert score == WEIGHTS["reference"]  # Full match


def test_reference_normalization_in_narration():
    """UTR embedded in narration should also match."""
    score = reference_score(
        "RZP20260601INDB5362",
        "SOME_OTHER_REF",
        "DEP TFR/NEFT/CR/RZP/20260601INDB5362"
    )
    assert score == WEIGHTS["reference"]


# ============================================================
# LEDGER PATH TESTS
# ============================================================

def test_ledger_weights_exclude_reference():
    """Ledger weights must not include reference."""
    assert "reference" not in LEDGER_WEIGHTS
    total = sum(LEDGER_WEIGHTS.values())
    assert total == 100.0


def test_ledger_exact_match_high_confidence():
    """TEST E from prompt: Ledger + exact amount + date + compatible type."""
    ledger_row = pd.Series({
        "ledger_amount": 8430.00,
        "ledger_date": pd.to_datetime("2026-06-16"),
        "customer_name": "Kiran Suppliers",
        "invoice_id": "INV-TEST",
        "payment_method": "netbanking",
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "SBIN49395565",
        "bank_amount": 8430.00,
        "bank_date": pd.to_datetime("2026-06-16"),
        "is_credit": True,
        "transaction_type": "NEFT",
        "narration": "CASH DEP/KIRAN SUPPLIERS",
    }])
    
    result = match_ledger(ledger_row, bank, set())
    
    assert result["status"] == "MATCHED"
    # Amount=45, Date=25, Party=15 (Kiran in narration), Type=10, Narration=5 = 100
    assert result["confidence"] >= 80.0
    assert result["evidence"]["reference_score"] is None
    assert result["evidence"]["reference_applicable"] == False


def test_ledger_amount_mismatch_but_strong_date_type():
    """TEST F: Ledger + amount mismatch + strong date/type → REVIEW."""
    ledger_row = pd.Series({
        "ledger_amount": 10000.00,
        "ledger_date": pd.to_datetime("2026-06-16"),
        "customer_name": "Kiran Suppliers",
        "invoice_id": "INV-MISMATCH",
        "payment_method": "netbanking",
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "REF123",
        "bank_amount": 8430.00,
        "bank_date": pd.to_datetime("2026-06-16"),
        "is_credit": True,
        "transaction_type": "NEFT",
        "narration": "CASH DEP/KIRAN SUPPLIERS",
    }])
    
    result = match_ledger(ledger_row, bank, set())
    
    # Should get scored, not discarded
    assert result["confidence"] > 0.0
    # Reference should be N/A
    assert result["evidence"]["reference_score"] is None
    # Amount mismatch is ~15.7%, so amount_score should be low
    assert result["evidence"]["amount_score"] < 45.0


def test_ledger_no_plausible_candidate():
    """TEST G: Ledger with no matching bank rows → UNMATCHED."""
    ledger_row = pd.Series({
        "ledger_amount": 999999.99,
        "ledger_date": pd.to_datetime("2026-01-01"),
        "customer_name": "NonExistent Corp",
        "invoice_id": "INV-NONE",
        "payment_method": "wire",
    })
    
    bank = pd.DataFrame([{
        "bank_reference": "REF",
        "bank_amount": 100.00,
        "bank_date": pd.to_datetime("2026-12-31"),
        "is_credit": True,
        "transaction_type": "NEFT",
        "narration": "SOME OTHER TRANSACTION",
    }])
    
    result = match_ledger(ledger_row, bank, set())
    
    assert result["status"] == "UNMATCHED"
    assert result["confidence"] < 25.0


def test_ledger_reference_not_applicable():
    """Reference score must be None (not 0) in ledger evidence."""
    ledger_row = pd.Series({
        "ledger_amount": 1000.00,
        "ledger_date": pd.to_datetime("2026-06-20"),
        "customer_name": "Test Corp",
        "invoice_id": "INV-001",
        "payment_method": "upi",
    })
    
    bank_row = pd.Series({
        "bank_reference": "REF123",
        "bank_amount": 1000.00,
        "bank_date": pd.to_datetime("2026-06-20"),
        "is_credit": True,
        "transaction_type": "UPI",
        "narration": "TEST CORP PAYMENT",
    })
    
    evidence = calculate_ledger_evidence(ledger_row, bank_row)
    
    assert evidence["reference_score"] is None
    assert evidence["reference_applicable"] == False
    # Total should be based on 100-point scale without reference
    assert evidence["base_score"] > 0.0
