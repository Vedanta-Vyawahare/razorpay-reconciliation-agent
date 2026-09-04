"""Purpose:
Stores all configurable parameters used by the Razorpay settlement-to-bank reconciliation engine.
The confidence model uses four evidence categories:
Amount: 75%
Settlement date: 15%
Transaction type: 7%
Narration: 3%
These weights total 100%.
Ambiguity is handled separately as a maximum 1% penalty and is not treated as positive evidence.
The configuration also defines amount tolerances, date-window limits, valid bank credit directions, Razorpay narration keywords, and valid settlement transaction types."""

# ============================================================
# RECONCILIATION CONFIGURATION
# Razorpay Settlement -> Bank Statement
# ============================================================

# Base confidence weights.
# These always add up to 100%.
WEIGHTS = {
    "amount": 75.0,
    "date": 15.0,
    "transaction_type": 7.0,
    "narration": 3.0,
}

# Ambiguity is NOT part of the 100-point evidence score.
# It is a small penalty applied after scoring.
AMBIGUITY_PENALTIES = {
    "none": 0.00,
    "weak": 0.25,
    "reasonable": 0.50,
    "strong": 0.75,
    "multiple": 1.00,
}

# Amount tolerances.
EXACT_AMOUNT_TOLERANCE = 0.01
SMALL_AMOUNT_TOLERANCE = 1.00

# Maximum reasonable settlement-date difference
# expressed in BUSINESS DAYS.
MAX_DATE_WINDOW = 5

# Candidate bank transactions must be credits.
VALID_BANK_DIRECTIONS = {
    "CREDIT",
    "CR",
}

# Keywords that may indicate a Razorpay-related settlement.
RAZORPAY_KEYWORDS = [
    "RAZORPAY",
    "RZPY",
    "RZP",
]

# Transaction types that can reasonably represent
# a settlement credit.
VALID_SETTLEMENT_TYPES = {
    "NEFT",
    "IMPS",
    "RTGS",
    "TRANSFER",
}