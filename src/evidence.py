
"""Purpose:
Calculates the evidence strength for a possible Razorpay settlement → bank statement match.

The confidence model consists of:

Amount relationship: 75%
Settlement timing: 15%
Transaction type: 7%
Narration: 3%

Amount receives the highest weight because the Razorpay settlement amount represents the expected settlement value.

Settlement timing is evaluated using business days rather than simple calendar-day differences.

Bank transaction type verifies that the candidate represents a plausible incoming settlement.

Narration provides additional supporting evidence when Razorpay-related identifiers such as RZPY or RAZORPAY are present.

This file calculates evidence but does not resolve competition between multiple candidates."""


# ============================================================
# EVIDENCE SCORING
# Razorpay Settlement -> Bank Statement
# ============================================================

from config import WEIGHTS, RAZORPAY_KEYWORDS
from datetime import timedelta


def amount_score(settlement_amount, bank_amount):
    """
    Amount evidence: maximum 75 points.

    The score is continuous rather than simply
    75 or 0.
    """

    if settlement_amount is None or bank_amount is None:
        return 0.0

    difference = abs(
        settlement_amount - bank_amount
    )

    if difference <= 0.01:
        return 75.0

    percentage_difference = (
        difference / settlement_amount
    ) * 100

    if percentage_difference <= 0.01:
        return 74.0

    if percentage_difference <= 0.05:
        return 72.0

    if percentage_difference <= 0.10:
        return 69.0

    if percentage_difference <= 0.25:
        return 64.0

    if percentage_difference <= 0.50:
        return 55.0

    if percentage_difference <= 1.00:
        return 45.0

    if percentage_difference <= 2.00:
        return 30.0

    if percentage_difference <= 5.00:
        return 15.0

    if percentage_difference <= 10.00:
        return 5.0

    return 0.0


def business_day_difference(date1, date2):
    """
    Count weekdays between two dates.

    Holiday intelligence will be added later.
    """

    if pd_is_missing(date1) or pd_is_missing(date2):
        return None

    date1 = date1.normalize()
    date2 = date2.normalize()

    if date1 == date2:
        return 0

    start = min(date1, date2)
    end = max(date1, date2)

    business_days = 0
    current = start

    while current < end:

        current += timedelta(days=1)

        if current.weekday() < 5:
            business_days += 1

    return business_days


def pd_is_missing(value):
    try:
        return value is None or value is pd.NaT
    except Exception:
        return value is None


def date_score(settlement_date, bank_date):
    """
    Date evidence: maximum 15 points.

    Settlement timing is evaluated in business days.
    """

    difference = business_day_difference(
        settlement_date,
        bank_date
    )

    if difference is None:
        return 0.0

    if difference == 0:
        return 15.0

    if difference == 1:
        return 13.5

    if difference == 2:
        return 11.5

    if difference == 3:
        return 8.5

    if difference == 4:
        return 5.0

    if difference == 5:
        return 2.0

    return 0.0


def transaction_type_score(bank_row):
    """
    Transaction type evidence: maximum 7 points.
    """

    if not bank_row.get("is_credit", False):
        return 0.0

    transaction_type = str(
        bank_row.get(
            "transaction_type",
            "UNKNOWN"
        )
    ).upper()

    if transaction_type == "NEFT":
        return 7.0

    if transaction_type == "IMPS":
        return 7.0

    if transaction_type == "RTGS":
        return 7.0

    if transaction_type == "TRANSFER":
        return 5.0

    return 2.0


def narration_score(narration):
    """
    Narration evidence: maximum 3 points.
    """

    if not narration:
        return 0.0

    text = str(narration).upper()

    for keyword in RAZORPAY_KEYWORDS:

        if keyword in text:
            return 3.0

    return 0.5


def calculate_evidence(settlement, bank_row):

    amount = amount_score(
        settlement["net_amount"],
        bank_row["bank_amount"]
    )

    date = date_score(
        settlement["settlement_date"],
        bank_row["bank_date"]
    )

    transaction_type = transaction_type_score(
        bank_row
    )

    narration = narration_score(
        bank_row["narration"]
    )

    base_score = (
        amount
        + date
        + transaction_type
        + narration
    )

    return {
        "amount_score": round(amount, 2),
        "date_score": round(date, 2),
        "transaction_type_score": round(
            transaction_type,
            2
        ),
        "narration_score": round(
            narration,
            2
        ),
        "base_score": round(
            base_score,
            2
        ),
    }