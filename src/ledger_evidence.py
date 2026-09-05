"""
Ledger -> Bank deterministic evidence engine.

IMPORTANT:
- Ledger reconciliation is NOT Razorpay settlement reconciliation.
- UTR/reference is NOT applicable and has ZERO decision weight.
- Customer/retailer name is diagnostic only and has ZERO decision weight.
- Primary decision evidence:
    Amount        80%
    Settlement date 15%
    Payment type  5%
"""

import pandas as pd
from utils.money import safe_float
from services.date_reasoning import business_day_difference

LEDGER_WEIGHTS = {
    "amount": 80.0,
    "date": 15.0,
    "type": 5.0,
    "party": 0.0,
    "narration": 0.0,
}

def normalize_text(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())

def amount_score(ledger_amt, bank_amt):
    if ledger_amt is None or bank_amt is None:
        return 0.0
    try:
        ledger_amt = float(ledger_amt)
        bank_amt = float(bank_amt)
    except (TypeError, ValueError):
        return 0.0
    if ledger_amt <= 0 or bank_amt <= 0:
        return 0.0

    max_pts = LEDGER_WEIGHTS["amount"]
    diff = abs(ledger_amt - bank_amt)
    pct = diff / ledger_amt * 100.0

    if diff <= 0.01:
        return max_pts
    if pct <= 0.25:
        return max_pts * 0.98
    if pct <= 0.50:
        return max_pts * 0.95
    if pct <= 1.00:
        return max_pts * 0.90
    if pct <= 2.00:
        return max_pts * 0.75
    if pct <= 5.00:
        return max_pts * 0.50
    if pct <= 10.00:
        return max_pts * 0.25
    return 0.0

def date_score(ledger_date, bank_date):
    if ledger_date is None or bank_date is None:
        return 0.0
    try:
        if pd.isna(ledger_date) or pd.isna(bank_date):
            return 0.0
        diff = abs(business_day_difference(ledger_date, bank_date))
    except Exception:
        return 0.0

    max_pts = LEDGER_WEIGHTS["date"]
    if diff == 0:
        return max_pts
    if diff == 1:
        return max_pts * 0.90
    if diff == 2:
        return max_pts * 0.75
    if diff == 3:
        return max_pts * 0.55
    if diff <= 5:
        return max_pts * 0.35
    if diff <= 7:
        return max_pts * 0.15
    return 0.0

def payment_type_score(payment_method, transaction_type):
    """Small corroborating signal only; never a primary key."""
    if payment_method is None or transaction_type is None:
        return 0.0
    pm = str(payment_method).strip().lower()
    tt = str(transaction_type).strip().upper()
    if not pm or not tt or pm in {"nan", "none"}:
        return 0.0

    max_pts = LEDGER_WEIGHTS["type"]

    direct = {
        "upi": {"UPI"},
        "neft": {"NEFT"},
        "rtgs": {"RTGS"},
        "imps": {"IMPS"},
        "netbanking": {"NEFT", "RTGS", "IMPS", "TRANSFER"},
        "bank_transfer": {"NEFT", "RTGS", "IMPS", "TRANSFER"},
        "bank transfer": {"NEFT", "RTGS", "IMPS", "TRANSFER"},
        "card": {"NEFT", "IMPS", "RTGS", "TRANSFER"},
        "wallet": {"NEFT", "IMPS", "RTGS", "TRANSFER"},
        "emi": {"NEFT", "IMPS", "RTGS", "TRANSFER"},
    }
    if pm in direct and tt in direct[pm]:
        return max_pts
    if tt in {"CREDIT", "TRANSFER", "UNKNOWN"}:
        return max_pts * 0.5
    return 0.0

def party_name_score(customer_name, narration):
    """
    Diagnostic only. Always returns zero so names cannot influence
    candidate ranking or the final decision.
    """
    return 0.0

def narration_score(customer_name, narration):
    """Narration/name are deliberately non-decisive for ledger matching."""
    return 0.0

def calculate_ledger_evidence(ledger_row, bank_row):
    ledger_amount = safe_float(ledger_row.get("ledger_amount"))
    bank_amount = safe_float(bank_row.get("bank_amount"))

    amt = amount_score(ledger_amount, bank_amount)
    dt = date_score(
        ledger_row.get("ledger_date"),
        bank_row.get("bank_date"),
    )
    typ = payment_type_score(
        ledger_row.get("payment_method"),
        bank_row.get("transaction_type"),
    )

    total = amt + dt + typ

    # Name/reference are explicitly diagnostic/non-applicable.
    name = ledger_row.get("customer_name", "")
    narration = bank_row.get("narration", "")
    name_match = bool(
        normalize_text(name)
        and normalize_text(name) in normalize_text(narration)
    )

    return {
        "amount_score": round(amt, 2),
        "date_score": round(dt, 2),
        "party_score": 0.0,
        "transaction_type_score": round(typ, 2),
        "narration_score": 0.0,
        "reference_score": None,
        "reference_applicable": False,
        "name_match_diagnostic": name_match,
        "base_score": round(total, 2),
    }
