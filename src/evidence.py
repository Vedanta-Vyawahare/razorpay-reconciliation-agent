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

from config import WEIGHTS, RAZORPAY_KEYWORDS

from datetime import timedelta


# ============================================================
# HELPERS
# ============================================================

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

    The score decreases continuously as the percentage
    difference increases.

    Exact settlement amount receives the full amount weight.

    This is deliberately much more sensitive than the old
    EXACT / SMALL / MODERATE / LARGE buckets.
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

    except (TypeError, ValueError):
        return 0.0

    if settlement_amount <= 0:
        return 0.0

    difference = abs(
        settlement_amount - bank_amount
    )

    # Exact to normal currency precision.
    if difference <= 0.01:
        return max_score

    percentage_difference = (
        difference
        / settlement_amount
    ) * 100

    # --------------------------------------------------------
    # Continuous evidence curve
    # --------------------------------------------------------
    #
    # 0%       -> 75
    # 0.1%     -> ~73
    # 0.5%     -> ~65
    # 1%       -> ~55
    # 2%       -> ~40
    # 5%       -> ~15
    # 10%+     -> 0
    #
    # The exact values are produced continuously rather than
    # by rigid categories.
    # --------------------------------------------------------

    if percentage_difference >= 10:
        return 0.0

    if percentage_difference <= 0.1:

        score = max_score * (
            1
            - (
                percentage_difference
                / 0.1
            ) * 0.025
        )

    elif percentage_difference <= 0.5:

        score = (
            max_score * 0.975
            - (
                percentage_difference
                - 0.1
            )
            / 0.4
            * (
                max_score * 0.10
            )
        )

    elif percentage_difference <= 1.0:

        score = (
            max_score * 0.875
            - (
                percentage_difference
                - 0.5
            )
            / 0.5
            * (
                max_score * 0.15
            )
        )

    elif percentage_difference <= 2.0:

        score = (
            max_score * 0.725
            - (
                percentage_difference
                - 1.0
            )
            / 1.0
            * (
                max_score * 0.20
            )
        )

    elif percentage_difference <= 5.0:

        score = (
            max_score * 0.525
            - (
                percentage_difference
                - 2.0
            )
            / 3.0
            * (
                max_score * 0.325
            )
        )

    else:

        score = (
            max_score * 0.20
            * (
                1
                - (
                    percentage_difference
                    - 5
                )
                / 5
            )
        )

    return max(
        0.0,
        min(
            max_score,
            score
        )
    )


# ============================================================
# SETTLEMENT TIMING EVIDENCE
# ============================================================

def expected_cycle(settlement):
    """
    Determine the expected settlement cycle.

    Examples:

        standard_t+2
        merchant_t+1
        instant_t+0

    The settlement dataset is the source of truth for the
    expected cycle.
    """

    cycle = str(
        settlement.get(
            "settlement_cycle",
            ""
        )
    ).lower()

    if "t+0" in cycle:
        return 0

    if "t+1" in cycle:
        return 1

    if "t+2" in cycle:
        return 2

    return None


def date_score(
    settlement,
    bank_date
):
    """
    Settlement timing evidence.

    Maximum:
        WEIGHTS["date"]

    The score is based on the EXPECTED settlement cycle.

    Example:

        merchant_t+1

        actual T+1
            -> maximum timing evidence

        actual T+2
            -> still plausible, but weaker

        actual T+3
            -> weaker again

        actual T-1
            -> very weak

    This function deliberately does not hardcode bank holidays.
    """

    max_score = WEIGHTS["date"]

    settlement_date = settlement.get(
        "settlement_date"
    )

    if (
        pd_is_missing(settlement_date)
        or pd_is_missing(bank_date)
    ):
        return 0.0

    expected_days = expected_cycle(
        settlement
    )

    if expected_days is None:
        return max_score * 0.40

    actual_days = business_day_difference(
        settlement_date,
        bank_date
    )

    if actual_days is None:
        return 0.0

    deviation = (
        actual_days
        - expected_days
    )

    # --------------------------------------------------------
    # Exact expected settlement day
    # --------------------------------------------------------

    if deviation == 0:
        return max_score

    # --------------------------------------------------------
    # One business day late
    # Still plausible.
    # --------------------------------------------------------

    if deviation == 1:
        return max_score * 0.90

    # --------------------------------------------------------
    # Two business days late
    # Possible, but weaker.
    # --------------------------------------------------------

    if deviation == 2:
        return max_score * 0.70

    # --------------------------------------------------------
    # Three business days late
    # --------------------------------------------------------

    if deviation == 3:
        return max_score * 0.45

    # --------------------------------------------------------
    # Four business days late
    # --------------------------------------------------------

    if deviation == 4:
        return max_score * 0.25

    # --------------------------------------------------------
    # Early settlement.
    #
    # T+1 expected but T+0 observed:
    # possible in some cases, but should not receive full
    # timing evidence.
    # --------------------------------------------------------

    if deviation == -1:

        return max_score * 0.55

    # More than one business day early is suspicious.
    if deviation < -1:

        return max_score * 0.15

    # Far outside expected window.
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

def calculate_evidence(
    settlement,
    bank_row
):
    """
    Calculate all deterministic evidence for one:

        Razorpay settlement -> bank transaction

    candidate.

    Returns individual evidence components plus the
    total deterministic evidence score.
    """

    amount = amount_score(
        settlement.get(
            "net_amount"
        ),
        bank_row.get(
            "bank_amount"
        )
    )

    date = date_score(
        settlement,
        bank_row.get(
            "bank_date"
        )
    )

    transaction_type = (
        transaction_type_score(
            bank_row
        )
    )

    narration = narration_score(
        bank_row.get(
            "narration"
        )
    )

    base_score = (
        amount
        + date
        + transaction_type
        + narration
    )

    return {

        "amount_score":
            round(
                amount,
                2
            ),

        "date_score":
            round(
                date,
                2
            ),

        "transaction_type_score":
            round(
                transaction_type,
                2
            ),

        "narration_score":
            round(
                narration,
                2
            ),

        "base_score":
            round(
                base_score,
                2
            )
    }