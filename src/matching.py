"""
Razorpay Settlement -> Bank Statement Matching Engine

Responsibilities
----------------
1. Generate valid bank candidates for a Razorpay settlement.
2. Score ALL valid candidates.
3. Rank candidates by evidence score.
4. Resolve competition between candidates.
5. Claim a bank row only when the winner is sufficiently strong.
6. Never reuse a claimed bank transaction.
7. Explain why a score is below 100.

Important
---------
evidence.py calculates the individual evidence components.

This file is responsible for:
    - candidate generation
    - candidate ranking
    - ambiguity handling
    - final decision
    - claim safety
"""

import pandas as pd


from evidence import (
    calculate_evidence,
)


# ============================================================
# CONFIGURATION
# ============================================================

# A candidate must reach this score before it can be
# automatically claimed when there is competition.
CLAIM_THRESHOLD = 95.0


# When two strong candidates are very close, do not
# automatically choose one.
AMBIGUITY_MARGIN = 3.0


# Minimum score below which a candidate is generally
# not considered a meaningful candidate.
MIN_CANDIDATE_SCORE = 50.0


# Candidate generation tolerances.
#
# We intentionally allow a reasonably wide amount window
# during candidate discovery. The evidence engine then
# decides how strong the amount relationship actually is.
AMOUNT_TOLERANCE_PERCENT = 10.0


# Date search window.
#
# The settlement_date in the Razorpay settlement file
# represents the date on which the settlement is expected
# to reach the merchant bank.
#
# Bank posting can occasionally happen around that date.
DATE_WINDOW_BUSINESS_DAYS = 3


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value):
    """
    Safely convert a value to float.
    """

    try:

        if value is None:
            return None

        if pd.isna(value):
            return None

        return float(value)

    except (TypeError, ValueError):

        return None


def get_settlement_amount(settlement):
    """
    Retrieve Razorpay net settlement amount.

    Supports both:

        net_settlement

    and:

        net_amount
    """

    value = settlement.get(
        "net_settlement",
        settlement.get(
            "net_amount"
        )
    )

    return safe_float(value)


def get_bank_amount(bank_row):
    """
    Retrieve normalized bank credit amount.
    """

    value = bank_row.get(
        "bank_amount"
    )

    return safe_float(value)


def get_bank_date(bank_row):
    """
    Retrieve normalized bank date.
    """

    value = bank_row.get(
        "bank_date"
    )

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

    except Exception:

        return None

    return pd.Timestamp(value)


def get_settlement_date(settlement):
    """
    Retrieve Razorpay settlement date.
    """

    value = settlement.get(
        "settlement_date"
    )

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

    except Exception:

        return None

    return pd.Timestamp(value)


def is_credit_transaction(bank_row):
    """
    Check whether a bank row represents an incoming credit.
    """

    value = bank_row.get(
        "is_credit",
        False
    )

    if isinstance(value, bool):
        return value

    text = str(value).strip().upper()

    return text in {
        "TRUE",
        "1",
        "YES",
        "Y"
    }


# ============================================================
# DATE / SETTLEMENT CYCLE HELPERS
# ============================================================

def business_day_distance(date1, date2):
    """
    Absolute business-day distance between two dates.

    Weekends are ignored.

    Example:

        Monday -> Monday = 0
        Monday -> Tuesday = 1
        Monday -> Wednesday = 2
    """

    if date1 is None or date2 is None:
        return None

    date1 = pd.Timestamp(date1).normalize()
    date2 = pd.Timestamp(date2).normalize()

    if date1 == date2:
        return 0

    start = min(
        date1,
        date2
    )

    end = max(
        date1,
        date2
    )

    current = start
    days = 0

    while current < end:

        current += pd.Timedelta(
            days=1
        )

        if current.weekday() < 5:
            days += 1

    return days


def signed_business_day_difference(
    date1,
    date2
):
    """
    Signed business-day difference.

    Positive:
        date2 is after date1.

    Negative:
        date2 is before date1.
    """

    if date1 is None or date2 is None:
        return None

    date1 = pd.Timestamp(date1).normalize()
    date2 = pd.Timestamp(date2).normalize()

    if date1 == date2:
        return 0

    direction = 1 if date2 > date1 else -1

    return (
        business_day_distance(
            date1,
            date2
        )
        * direction
    )


def get_cycle_type(settlement):
    """
    Normalize settlement cycle.

    Examples:

        merchant_t+1
        standard_t+2
        instant_t+0
    """

    cycle = str(
        settlement.get(
            "settlement_cycle",
            ""
        )
    ).strip().lower()

    return cycle


def cycle_expected_window(settlement):
    """
    Determine the expected bank-date tolerance based
    on the settlement cycle.

    IMPORTANT:

    settlement_date is already the Razorpay settlement date,
    i.e. the date the settlement is supposed to reach the
    merchant.

    Therefore we DO NOT add T+1/T+2 to settlement_date.

    Instead, settlement_cycle tells us how strict we should
    be about bank posting around the settlement date.
    """

    cycle = get_cycle_type(
        settlement
    )

    if "t+0" in cycle:
        return 0

    if "t+1" in cycle:
        return 1

    if "t+2" in cycle:
        return 2

    # Unknown cycle:
    # use the general tolerance.
    return DATE_WINDOW_BUSINESS_DAYS


# ============================================================
# AMOUNT CANDIDATE FILTER
# ============================================================

def amount_within_candidate_window(
    settlement_amount,
    bank_amount
):
    """
    Decide whether a bank amount is close enough to even
    consider as a candidate.

    This is ONLY candidate discovery.

    Final amount strength comes from evidence.py.
    """

    if (
        settlement_amount is None
        or bank_amount is None
    ):
        return False

    if settlement_amount <= 0:
        return False

    difference = abs(
        settlement_amount
        - bank_amount
    )

    percentage_difference = (
        difference
        / settlement_amount
    ) * 100

    return (
        percentage_difference
        <= AMOUNT_TOLERANCE_PERCENT
    )


# ============================================================
# DATE CANDIDATE FILTER
# ============================================================

def date_within_candidate_window(
    settlement,
    bank_row
):
    """
    Determine whether a bank row is close enough in time
    to be considered a candidate.

    settlement_cycle controls the allowed business-day
    tolerance.
    """

    settlement_date = get_settlement_date(
        settlement
    )

    bank_date = get_bank_date(
        bank_row
    )

    if (
        settlement_date is None
        or bank_date is None
    ):
        return False

    distance = business_day_distance(
        settlement_date,
        bank_date
    )

    if distance is None:
        return False

    cycle_window = cycle_expected_window(
        settlement
    )

    # Never allow an unlimited date window.
    allowed_window = max(
        cycle_window,
        DATE_WINDOW_BUSINESS_DAYS
    )

    return distance <= allowed_window


# ============================================================
# CANDIDATE VALIDATION
# ============================================================

def valid_candidate(
    settlement,
    bank_row
):
    """
    Basic candidate validation.
    """

    if not is_credit_transaction(
        bank_row
    ):
        return False

    settlement_amount = get_settlement_amount(
        settlement
    )

    bank_amount = get_bank_amount(
        bank_row
    )

    if settlement_amount is None:
        return False

    if bank_amount is None:
        return False

    if get_settlement_date(
        settlement
    ) is None:
        return False

    if get_bank_date(
        bank_row
    ) is None:
        return False

    if not amount_within_candidate_window(
        settlement_amount,
        bank_amount
    ):
        return False

    if not date_within_candidate_window(
        settlement,
        bank_row
    ):
        return False

    return True


# ============================================================
# CANDIDATE SCORING
# ============================================================

def score_candidate(
    settlement,
    bank,
    bank_index
):
    """
    Calculate evidence for ONE bank candidate.

    evidence.py expects a DataFrame for grouped candidates,
    therefore a single bank row is converted into a one-row
    DataFrame.
    """

    candidate_rows = bank.loc[
        [bank_index]
    ].copy()

    evidence = calculate_evidence(
        settlement,
        candidate_rows
    )

    return evidence


# ============================================================
# SCORE EXPLANATION
# ============================================================

def build_score_explanation(
    settlement,
    bank_row,
    evidence,
    final_score
):
    """
    Explain exactly why the candidate received its score.
    """

    explanations = []

    settlement_amount = get_settlement_amount(
        settlement
    )

    bank_amount = get_bank_amount(
        bank_row
    )

    settlement_date = get_settlement_date(
        settlement
    )

    bank_date = get_bank_date(
        bank_row
    )

    # --------------------------------------------------------
    # AMOUNT
    # --------------------------------------------------------

    if (
        settlement_amount is not None
        and bank_amount is not None
    ):

        difference = abs(
            settlement_amount
            - bank_amount
        )

        percentage_difference = (
            difference
            / settlement_amount
        ) * 100

        if difference <= 0.01:

            explanations.append(
                "Exact net settlement amount."
            )

        else:

            explanations.append(
                "Bank amount differs from the "
                f"Razorpay settlement by "
                f"{percentage_difference:.2f}%."
            )

    else:

        explanations.append(
            "Amount evidence unavailable."
        )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    if (
        settlement_date is not None
        and bank_date is not None
    ):

        date_gap = signed_business_day_difference(
            settlement_date,
            bank_date
        )

        cycle = get_cycle_type(
            settlement
        )

        if date_gap == 0:

            explanations.append(
                "Bank date exactly matches the "
                "Razorpay settlement date."
            )

        elif date_gap > 0:

            explanations.append(
                "Bank credit occurred "
                f"{date_gap} business day(s) "
                "after the settlement date."
            )

        else:

            explanations.append(
                "Bank credit occurred "
                f"{abs(date_gap)} business day(s) "
                "before the settlement date."
            )

        if cycle:

            explanations.append(
                f"Settlement cycle: {cycle}."
            )

    else:

        explanations.append(
            "Date evidence unavailable."
        )

    # --------------------------------------------------------
    # TRANSACTION TYPE
    # --------------------------------------------------------

    transaction_type_score = evidence.get(
        "transaction_type_score",
        0
    )

    if transaction_type_score >= 7:

        explanations.append(
            "Incoming bank transaction uses "
            "a strong settlement-compatible "
            "transfer type."
        )

    elif transaction_type_score > 0:

        explanations.append(
            "Incoming transaction type provides "
            "partial supporting evidence."
        )

    else:

        explanations.append(
            "Transaction type provides no "
            "supporting evidence."
        )

    # --------------------------------------------------------
    # NARRATION
    # --------------------------------------------------------

    narration_score = evidence.get(
        "narration_score",
        0
    )

    if narration_score >= 3:

        explanations.append(
            "Bank narration contains a strong "
            "Razorpay identifier."
        )

    elif narration_score > 0:

        explanations.append(
            "Bank narration provides weak "
            "supporting evidence."
        )

    else:

        explanations.append(
            "No Razorpay identifier was found "
            "in the bank narration."
        )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    if final_score >= 99.99:

        explanations.append(
            "Evidence is effectively complete."
        )

    else:

        missing = round(
            100.0 - final_score,
            2
        )

        explanations.append(
            f"Overall evidence is {missing:.2f} "
            "points below 100."
        )

    return explanations


# ============================================================
# AMBIGUITY
# ============================================================

def calculate_ambiguity_penalty(
    candidate_score,
    competing_scores
):
    """
    Calculate ambiguity penalty.

    This is intentionally small.

    Competition is primarily handled through the
    final decision logic rather than destroying the
    evidence score.
    """

    if not competing_scores:
        return 0.0

    second_score = max(
        competing_scores
    )

    difference = (
        candidate_score
        - second_score
    )

    if difference >= 10:
        return 0.0

    if difference >= 5:
        return 0.05

    if difference >= 3:
        return 0.10

    return 0.15


def is_genuine_competition(
    top_score,
    second_score
):
    """
    Determine whether the second candidate is strong enough
    to make the result genuinely ambiguous.

    A weak 40% candidate should not make a 100% candidate
    ambiguous.

    Example:

        100 vs 40 -> clear winner

        98 vs 97 -> genuine competition
    """

    if second_score is None:
        return False

    if second_score < CLAIM_THRESHOLD:
        return False

    difference = (
        top_score
        - second_score
    )

    return difference < AMBIGUITY_MARGIN


# ============================================================
# CANDIDATE GENERATION
# ============================================================

def generate_candidates(
    settlement,
    bank,
    claimed_bank_indices
):
    """
    Generate ALL valid, currently unclaimed candidates.
    """

    candidates = []

    for index, bank_row in bank.iterrows():

        # ----------------------------------------------------
        # NEVER reuse a claimed bank transaction
        # ----------------------------------------------------

        if index in claimed_bank_indices:
            continue

        # ----------------------------------------------------
        # Basic validation
        # ----------------------------------------------------

        if not valid_candidate(
            settlement,
            bank_row
        ):
            continue

        # ----------------------------------------------------
        # Score candidate
        # ----------------------------------------------------

        evidence = score_candidate(
            settlement,
            bank,
            index
        )

        base_score = float(
            evidence.get(
                "base_score",
                0.0
            )
        )

        # ----------------------------------------------------
        # Ignore extremely weak candidates.
        # ----------------------------------------------------

        if base_score < MIN_CANDIDATE_SCORE:
            continue

        candidates.append({

            "bank_index": index,

            "evidence": evidence,

            "base_score": base_score,

            "bank_amount":
                get_bank_amount(
                    bank_row
                ),

            "bank_date":
                get_bank_date(
                    bank_row
                ),

            "bank_reference":
                bank_row.get(
                    "bank_reference",
                    bank_row.get(
                        "ref_no_cheque_no",
                        bank_row.get(
                            "reference",
                            index
                        )
                    )
                ),
        })

    # --------------------------------------------------------
    # Highest evidence first
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["base_score"],
        reverse=True
    )

    return candidates


# ============================================================
# MAIN MATCH FUNCTION
# ============================================================

def match_settlement(
    settlement,
    bank,
    claimed_bank_indices
):
    """
    Match ONE Razorpay settlement against the bank statement.

    Decision logic
    --------------

    ONE candidate:

        >= 95%
            MATCHED

        < 95%
            REVIEW / UNMATCHED

    MULTIPLE candidates:

        Top >= 95%
        AND top clearly beats second
            MATCHED

        Otherwise
            REVIEW

    A weak second candidate does NOT make a strong
    candidate ambiguous.
    """

    candidates = generate_candidates(
        settlement,
        bank,
        claimed_bank_indices
    )

    # ========================================================
    # NO CANDIDATES
    # ========================================================

    if not candidates:

        return {

            "bank_index": None,

            "evidence": None,

            "ambiguity_penalty": 0.0,

            "confidence": 0.0,

            "status": "UNMATCHED",

            "ambiguity_type": "none",

            "candidate_count": 0,

            "candidate_rankings": [],

            "score_explanation": [
                "No valid unclaimed bank candidate "
                "was found."
            ],
        }

    # ========================================================
    # TOP CANDIDATE
    # ========================================================

    top = candidates[0]

    top_score = float(
        top["base_score"]
    )

    second = (
        candidates[1]
        if len(candidates) > 1
        else None
    )

    second_score = (
        float(
            second["base_score"]
        )
        if second is not None
        else None
    )

    # ========================================================
    # AMBIGUITY PENALTY
    # ========================================================

    competing_scores = []

    if second is not None:

        competing_scores = [
            float(
                candidate["base_score"]
            )
            for candidate in candidates[1:]
        ]

    ambiguity_penalty = calculate_ambiguity_penalty(
        top_score,
        competing_scores
    )

    # ========================================================
    # FINAL SCORE
    # ========================================================

    final_score = round(
        top_score
        * (1.0 - ambiguity_penalty),
        2
    )

    # ========================================================
    # RANKINGS
    # ========================================================

    candidate_rankings = []

    for rank, candidate in enumerate(
        candidates,
        start=1
    ):

        candidate_rankings.append({

            "rank": rank,

            "bank_index":
                candidate["bank_index"],

            "bank_reference":
                candidate["bank_reference"],

            "bank_amount":
                candidate["bank_amount"],

            "bank_date":
                candidate["bank_date"],

            "score":
                round(
                    candidate["base_score"],
                    2
                ),

            "amount_score":
                round(
                    candidate["evidence"].get(
                        "amount_score",
                        0
                    ),
                    2
                ),

            "date_score":
                round(
                    candidate["evidence"].get(
                        "date_score",
                        0
                    ),
                    2
                ),

            "transaction_type_score":
                round(
                    candidate["evidence"].get(
                        "transaction_type_score",
                        0
                    ),
                    2
                ),

            "narration_score":
                round(
                    candidate["evidence"].get(
                        "narration_score",
                        0
                    ),
                    2
                ),
        })

    # ========================================================
    # SCORE EXPLANATION
    # ========================================================

    explanation = build_score_explanation(
        settlement,
        bank.loc[
            top["bank_index"]
        ],
        top["evidence"],
        final_score
    )

    # ========================================================
    # DECISION
    # ========================================================

    # --------------------------------------------------------
    # CASE 1:
    # One candidate only
    # --------------------------------------------------------

    if second is None:

        if top_score >= CLAIM_THRESHOLD:

            return {

                "bank_index":
                    top["bank_index"],

                "evidence":
                    top["evidence"],

                "ambiguity_penalty":
                    0.0,

                "confidence":
                    round(
                        top_score,
                        2
                    ),

                "status":
                    "MATCHED",

                "ambiguity_type":
                    "none",

                "candidate_count":
                    1,

                "candidate_rankings":
                    candidate_rankings,

                "score_explanation":
                    explanation,
            }

        return {

            "bank_index": None,

            "evidence":
                top["evidence"],

            "ambiguity_penalty":
                0.0,

            "confidence":
                round(
                    top_score,
                    2
                ),

            "status":
                "REVIEW",

            "ambiguity_type":
                "weak_single_candidate",

            "candidate_count":
                1,

            "candidate_rankings":
                candidate_rankings,

            "score_explanation":
                explanation
                + [
                    f"Candidate score is below the "
                    f"{CLAIM_THRESHOLD:.0f}% automatic "
                    "claim threshold."
                ],
        }

    # --------------------------------------------------------
    # CASE 2:
    # Multiple candidates, but top is below 95%
    # --------------------------------------------------------

    if top_score < CLAIM_THRESHOLD:

        return {

            "bank_index": None,

            "evidence":
                top["evidence"],

            "ambiguity_penalty":
                ambiguity_penalty,

            "confidence":
                round(
                    final_score,
                    2
                ),

            "status":
                "REVIEW",

            "ambiguity_type":
                "multiple_weak_candidates",

            "candidate_count":
                len(candidates),

            "candidate_rankings":
                candidate_rankings,

            "score_explanation":
                explanation
                + [
                    f"Best candidate is only "
                    f"{top_score:.2f}%, below the "
                    f"{CLAIM_THRESHOLD:.0f}% claim threshold."
                ],
        }

    # --------------------------------------------------------
    # CASE 3:
    # Multiple strong candidates
    # --------------------------------------------------------

    if is_genuine_competition(
        top_score,
        second_score
    ):

        return {

            "bank_index": None,

            "evidence":
                top["evidence"],

            "ambiguity_penalty":
                ambiguity_penalty,

            "confidence":
                round(
                    final_score,
                    2
                ),

            "status":
                "REVIEW",

            "ambiguity_type":
                "multiple_strong_candidates",

            "candidate_count":
                len(candidates),

            "candidate_rankings":
                candidate_rankings,

            "score_explanation":
                explanation
                + [
                    "Multiple strong candidates were found.",
                    (
                        f"Top candidate: "
                        f"{top_score:.2f}%."
                    ),
                    (
                        f"Second candidate: "
                        f"{second_score:.2f}%."
                    ),
                    (
                        f"Difference: "
                        f"{top_score - second_score:.2f} "
                        "points."
                    ),
                    (
                        "No bank row was claimed because "
                        "the candidates are too close."
                    ),
                ],
        }

    # --------------------------------------------------------
    # CASE 4:
    # Multiple candidates, but top clearly wins
    # --------------------------------------------------------

    return {

        "bank_index":
            top["bank_index"],

        "evidence":
            top["evidence"],

        "ambiguity_penalty":
            ambiguity_penalty,

        "confidence":
            round(
                final_score,
                2
            ),

        "status":
            "MATCHED",

        "ambiguity_type":
            "none",

        "candidate_count":
            len(candidates),

        "candidate_rankings":
            candidate_rankings,

        "score_explanation":
            explanation
            + [
                (
                    f"Top candidate scored "
                    f"{top_score:.2f}%."
                ),
                (
                    f"Second candidate scored "
                    f"{second_score:.2f}%."
                ),
                (
                    "Top candidate exceeded the "
                    f"{CLAIM_THRESHOLD:.0f}% claim threshold "
                    "and was sufficiently stronger."
                ),
            ],
    }