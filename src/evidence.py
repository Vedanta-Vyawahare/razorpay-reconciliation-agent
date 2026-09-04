"""
Purpose
-------
Calculates deterministic evidence strength for a possible:

    Razorpay Settlement -> Bank Statement

Confidence model
----------------
Amount relationship       : 75 points
Settlement timing         : 15 points
Transaction type          : 7 points
Narration                 : 3 points
                            ----
                            100 points

Important
---------
These are EVIDENCE POINTS, not statistical probabilities.

Ambiguity is handled separately in matching.py and can apply
a small penalty of 0% to 1%.

This file does NOT decide which candidate wins.
It only calculates how much evidence each candidate provides.
"""

import pandas as pd

from config import WEIGHTS, RAZORPAY_KEYWORDS, EXACT_AMOUNT_TOLERANCE, SMALL_AMOUNT_TOLERANCE

from datetime import timedelta


# ============================================================
# HELPERS
# ============================================================

def safe_date(value):
    """
    Safely convert a value to pandas Timestamp.
    """

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

        return pd.to_datetime(value)

    except Exception:

        return None
    
    
def pd_is_missing(value):
    """
    Safely determine whether a value is missing.
    """

    if value is None:
        return True

    try:
        return pd.isna(value)
    except Exception:
        return False


def business_day_difference(date1, date2):
    """
    Calculate the signed number of business days between two dates.

    Positive:
        date2 occurs after date1.

    Negative:
        date2 occurs before date1.

    Example:

        Monday -> Tuesday = +1
        Monday -> Wednesday = +2
        Monday -> Friday = +4

        Tuesday -> Monday = -1

    Weekends are ignored.

    Bank-holiday intelligence is intentionally NOT handled here.
    """

    if (
        pd_is_missing(date1)
        or pd_is_missing(date2)
    ):
        return None

    date1 = pd.Timestamp(date1).normalize()
    date2 = pd.Timestamp(date2).normalize()

    if date1 == date2:
        return 0

    direction = 1 if date2 > date1 else -1

    start = min(date1, date2)
    end = max(date1, date2)

    current = start
    business_days = 0

    while current < end:

        current += timedelta(days=1)

        if current.weekday() < 5:
            business_days += 1

    return business_days * direction

def get_settlement_amount(settlement):
    """
    Retrieve Razorpay net settlement amount.

    Supports:
        net_settlement

    and the older internal field:
        net_amount
    """

    value = settlement.get(
        "net_settlement",
        settlement.get(
            "net_amount"
        )
    )

    try:

        if value is None or pd.isna(value):
            return None

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return None


# ============================================================
# AMOUNT EVIDENCE
# ============================================================

def amount_score(
    settlement_amount,
    bank_amount
):
    """
    Amount evidence.

    Maximum:
        WEIGHTS["amount"]

    Exact net settlement amount receives full evidence.
    """

    max_score = WEIGHTS["amount"]

    if (
        settlement_amount is None
        or bank_amount is None
    ):
        return 0.0

    try:

        settlement_amount = float(
            settlement_amount
        )

        bank_amount = float(
            bank_amount
        )

    except (
        TypeError,
        ValueError
    ):

        return 0.0

    if settlement_amount <= 0:
        return 0.0

    difference = abs(
        settlement_amount
        - bank_amount
    )

    if difference <= EXACT_AMOUNT_TOLERANCE:
        return max_score

    # Percentage difference relative to settlement amount
    percentage_difference = (
        difference
        / settlement_amount
    ) * 100

    # Small absolute differences (e.g. rounding) should still
    # contribute meaningful evidence. Use configured small
    # tolerance as a guideline.
    try:
        small_abs_threshold = float(SMALL_AMOUNT_TOLERANCE)
    except Exception:
        small_abs_threshold = 1.0

    # Score curve (heuristic): gradually degrade evidence as
    # percentage difference increases.
    if difference <= small_abs_threshold:
        return max_score * 0.9

    if percentage_difference <= 1.0:
        return max_score * 0.8

    if percentage_difference <= 3.0:
        return max_score * 0.5

    if percentage_difference <= 7.0:
        return max_score * 0.25

    return 0.0


def date_score(settlement, bank_date):
    """
    Date evidence.

    Maximum:
        WEIGHTS["date"]

    Compares Razorpay settlement_date with the
    actual bank credit date using business days.
    """

    settlement_date = settlement.get(
        "settlement_date"
    )

    settlement_date = safe_date(
        settlement_date
    )

    bank_date = safe_date(
        bank_date
    )

    if (
        settlement_date is None
        or bank_date is None
    ):
        return 0.0

    difference = abs(
        business_day_difference(
            settlement_date,
            bank_date
        )
    )

    max_score = WEIGHTS["date"]

    if difference == 0:
        return max_score

    if difference == 1:
        return max_score * 0.90

    if difference == 2:
        return max_score * 0.75

    if difference == 3:
        return max_score * 0.55

    if difference == 4:
        return max_score * 0.35

    if difference == 5:
        return max_score * 0.15

    return 0.0


# ============================================================
# TRANSACTION TYPE EVIDENCE
# ============================================================

def transaction_type_score(bank_row):
    """
    Transaction type evidence.

    Maximum:
        WEIGHTS["transaction_type"]

    Razorpay settlements normally arrive as incoming
    bank credits.

    NEFT / IMPS / RTGS are strong transfer mechanisms.

    Generic incoming transfers provide weaker evidence.
    """

    max_score = WEIGHTS[
        "transaction_type"
    ]

    if not bank_row.get(
        "is_credit",
        False
    ):
        return 0.0

    transaction_type = str(
        bank_row.get(
            "transaction_type",
            "UNKNOWN"
        )
    ).upper()

    if transaction_type in {
        "NEFT",
        "IMPS",
        "RTGS"
    }:
        return max_score

    if transaction_type == "TRANSFER":
        return max_score * 0.70

    if transaction_type in {
        "UPI",
        "CREDIT"
    }:
        return max_score * 0.40

    return max_score * 0.15


# ============================================================
# NARRATION EVIDENCE
# ============================================================

def narration_score(narration):
    """
    Narration evidence.

    Maximum:
        WEIGHTS["narration"]

    This is deliberately a supporting signal.

    We should NOT make narration a primary matching key
    because bank narrations are inconsistent.
    """

    max_score = WEIGHTS[
        "narration"
    ]

    if pd_is_missing(narration):
        return 0.0

    text = str(
        narration
    ).upper()

    # Strong Razorpay identifiers.
    strong_keywords = [
        keyword.upper()
        for keyword in RAZORPAY_KEYWORDS
    ]

    for keyword in strong_keywords:

        if keyword in text:
            return max_score

    # Generic settlement wording is weak evidence.
    weak_terms = [
        "SETTLEMENT",
        "PAYOUT",
        "PAYMENT GATEWAY",
        "PG"
    ]

    for term in weak_terms:

        if term in text:
            return max_score * 0.40

    return 0.0


# ============================================================
# COMPLETE EVIDENCE
# ============================================================

def calculate_evidence(settlement, bank_rows):
    """
    Calculate evidence for a Razorpay settlement -> bank statement match.

    bank_rows may be:
        1. A pandas DataFrame containing multiple bank rows
        2. A pandas Series containing one bank row

    For Razorpay lump-sum settlements, multiple bank credits
    may collectively represent the settlement.
    """

    settlement_amount = get_settlement_amount(
        settlement
    )

    if settlement_amount is None:
        return {
            "amount_score": 0.0,
            "date_score": 0.0,
            "transaction_type_score": 0.0,
            "narration_score": 0.0,
            "base_score": 0.0,
        }

    # --------------------------------------------------------
    # NORMALIZE INPUT
    # --------------------------------------------------------

    if isinstance(bank_rows, pd.Series):

        bank_rows = bank_rows.to_frame().T

    elif not isinstance(bank_rows, pd.DataFrame):

        return {
            "amount_score": 0.0,
            "date_score": 0.0,
            "transaction_type_score": 0.0,
            "narration_score": 0.0,
            "base_score": 0.0,
        }

    if bank_rows.empty:

        return {
            "amount_score": 0.0,
            "date_score": 0.0,
            "transaction_type_score": 0.0,
            "narration_score": 0.0,
            "base_score": 0.0,
        }

    # --------------------------------------------------------
    # AMOUNT
    # --------------------------------------------------------

    bank_amounts = pd.to_numeric(
        bank_rows["bank_amount"],
        errors="coerce"
    ).fillna(0.0)

    total_bank_amount = round(
        bank_amounts.sum(),
        2
    )

    amount = amount_score(
        settlement_amount,
        total_bank_amount
    )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    bank_dates = bank_rows[
        "bank_date"
    ].dropna()

    if len(bank_dates) > 0:

        # For a grouped settlement, use the latest
        # credit date as the settlement arrival date.
        bank_date = bank_dates.max()

    else:

        bank_date = None

    date = date_score(
        settlement,
        bank_date
    )

    # --------------------------------------------------------
    # TRANSACTION TYPE
    # --------------------------------------------------------

    transaction_type = group_transaction_type_score(
        bank_rows
    )

    # --------------------------------------------------------
    # NARRATION
    # --------------------------------------------------------

    narrations = bank_rows[
        "narration"
    ].dropna().astype(str)

    narration = group_narration_score(
        bank_rows
    )

    # --------------------------------------------------------
    # TOTAL EVIDENCE
    # --------------------------------------------------------

    base_score = (
        amount
        + date
        + transaction_type
        + narration
    )

    return {

        "amount_score":
            round(amount, 2),

        "date_score":
            round(date, 2),

        "transaction_type_score":
            round(transaction_type, 2),

        "narration_score":
            round(narration, 2),

        "base_score":
            round(base_score, 2),

        # Useful for debugging/output
        "bank_total":
            total_bank_amount,

        "bank_row_count":
            len(bank_rows),
    }

def group_transaction_type_score(bank_rows):

    if len(bank_rows) == 0:
        return 0.0

    if not bank_rows["is_credit"].all():
        return 0.0

    types = set(
        bank_rows["transaction_type"]
        .astype(str)
        .str.upper()
    )

    if types & {"NEFT", "IMPS", "RTGS"}:
        return WEIGHTS.get("transaction_type", 7.0)

    if "TRANSFER" in types:
        return 5.0

    return 2.0

def group_narration_score(bank_rows):

    text = " ".join(
        bank_rows["narration"]
        .fillna("")
        .astype(str)
        .str.upper()
    )

    for keyword in RAZORPAY_KEYWORDS:
        if keyword in text:
            return WEIGHTS.get("narration", 3.0)

    # Small supporting score when any narration text exists.
    return max(0.0, WEIGHTS.get("narration", 3.0) * 0.15)


def expected_cycle(settlement):
    """
    Convert settlement cycle string into expected business days.
    Mirrors the behaviour used elsewhere (e.g. matching.expected_cycle_days).
    Returns an integer number of days or None.
    """

    if settlement is None:
        return None

    value = settlement.get(
        "settlement_cycle"
    )

    if value is None:
        return None

    cycle = str(value).strip().lower()

    if "t+0" in cycle:
        return 0

    if "t+1" in cycle:
        return 1

    if "t+2" in cycle:
        return 2

    if "t+3" in cycle:
        return 3

    return None