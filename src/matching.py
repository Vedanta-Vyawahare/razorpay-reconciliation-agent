"""
Purpose
-------

Matches Razorpay settlement records against bank statement credits.

This is the candidate-selection layer.

The matching process is deliberately separated into two stages:

    1. Evidence generation
       -> handled by evidence.py

    2. Candidate selection + ambiguity handling
       -> handled here

The model does NOT assume that the Razorpay UTR must appear
in the bank statement.

Primary evidence:
    - Net settlement amount
    - Settlement date / business-day relationship

Supporting evidence:
    - Incoming transaction type
    - Razorpay-related narration

Ambiguity is treated as a small penalty rather than destroying
a strong match.

The final score is:

    evidence score - ambiguity penalty

The maximum evidence score is 100.
"""


from evidence import calculate_evidence


# ============================================================
# CONFIGURATION
# ============================================================

MATCH_THRESHOLD = 75.0
REVIEW_THRESHOLD = 55.0

# Maximum date window considered for settlement matching.
#
# This is intentionally not treated as a fixed settlement rule.
# The actual date score is calculated by evidence.py.
MAX_BUSINESS_DAY_WINDOW = 5


# ============================================================
# HELPERS
# ============================================================

def safe_float(value):
    """
    Safely convert a value to float.
    """

    try:
        if value is None:
            return None

        return float(value)

    except (ValueError, TypeError):
        return None


def get_settlement_amount(settlement):
    """
    Retrieve the Razorpay net settlement amount.

    Supports the current field:
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

    return safe_float(value)


def get_bank_amount(bank_row):
    """
    Retrieve the incoming bank credit amount.

    Supports the normalized field:
        bank_amount

    and the original CSV field:
        credit
    """

    value = bank_row.get(
        "bank_amount",
        bank_row.get(
            "credit"
        )
    )

    return safe_float(value)


def get_bank_date(bank_row):
    """
    Retrieve normalized bank transaction date.
    """

    return bank_row.get(
        "bank_date",
        bank_row.get(
            "post_date",
            bank_row.get(
                "value_date"
            )
        )
    )


def get_bank_reference(bank_row, index):
    """
    Get the bank reference.

    The bank statement may contain:

        ref_no_cheque_no

    rather than a Razorpay UTR.

    Therefore this is only used for identification,
    not as a mandatory matching criterion.
    """

    return bank_row.get(
        "bank_reference",
        bank_row.get(
            "ref_no_cheque_no",
            bank_row.get(
                "reference",
                index
            )
        )
    )


def is_credit_transaction(bank_row):
    """
    Confirm that the bank row represents money entering
    the merchant account.

    Debit transactions must never become settlement matches.
    """

    if "is_credit" in bank_row:
        return bool(
            bank_row["is_credit"]
        )

    credit = safe_float(
        bank_row.get("credit", 0)
    )

    return credit is not None and credit > 0


# ============================================================
# CANDIDATE FILTERING
# ============================================================

def is_possible_candidate(settlement, bank_row):
    """
    Decide whether a bank row is worth scoring.

    We do NOT require:
        - UTR equality
        - narration equality
        - exact date equality

    because real bank statements may not expose the same
    identifiers as the Razorpay settlement report.

    We DO require:
        - incoming credit
        - usable amount
        - usable date
    """

    if not is_credit_transaction(bank_row):
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

    if get_bank_date(bank_row) is None:
        return False

    return True


# ============================================================
# CANDIDATE SCORING
# ============================================================

def score_candidate(settlement, bank, bank_index):
    """
    Calculate evidence for one candidate bank transaction.

    evidence.py expects bank_rows to be a DataFrame because
    the reconciliation model supports grouped bank credits.

    Therefore even a single candidate is passed as a
    one-row DataFrame.
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
# AMBIGUITY ANALYSIS
# ============================================================

def calculate_ambiguity_penalty(
    candidate_score,
    competing_scores
):
    """
    Apply a small ambiguity penalty.

    IMPORTANT:

    Ambiguity should NOT heavily punish a candidate that has
    otherwise strong evidence.

    Proposed hierarchy:

        No meaningful competitor
            -> 0.00

        One weak competitor
            -> 0.25

        One reasonably strong competitor
            -> 0.50

        Two strong competitors
            -> 0.75

        Multiple nearly identical candidates
            -> 1.00 maximum

    The penalty is deliberately capped at 1%.

    candidate_score:
        Evidence score of selected candidate.

    competing_scores:
        Evidence scores of alternative candidates.
    """

    if not competing_scores:
        return 0.0

    # Keep only candidates that are genuinely competitive.
    meaningful_competitors = [
        score
        for score in competing_scores
        if score >= candidate_score - 15
    ]

    if not meaningful_competitors:
        return 0.0

    strong_competitors = [
        score
        for score in meaningful_competitors
        if score >= 85
    ]

    nearly_identical = [
        score
        for score in meaningful_competitors
        if abs(score - candidate_score) <= 2
    ]

    # Multiple nearly identical candidates.
    if len(nearly_identical) >= 2:
        return 1.0

    # Two strong competitors.
    if len(strong_competitors) >= 2:
        return 0.75

    # One strong competitor.
    if len(strong_competitors) == 1:
        return 0.50

    # A weaker but still meaningful competitor.
    return 0.25


def determine_ambiguity_type(
    candidate_score,
    competing_scores
):
    """
    Explain why a candidate is considered ambiguous.
    """

    if not competing_scores:
        return "none"

    meaningful = [
        score
        for score in competing_scores
        if score >= candidate_score - 15
    ]

    if not meaningful:
        return "none"

    if any(
        abs(score - candidate_score) <= 2
        for score in meaningful
    ):
        return "nearly_identical_candidates"

    if any(
        score >= 85
        for score in meaningful
    ):
        return "strong_competitor"

    return "weak_competitor"


# ============================================================
# DECISION LOGIC
# ============================================================

def determine_status(
    final_score,
    evidence,
    ambiguity_penalty,
    candidate_count
):
    """
    Determine MATCHED / REVIEW / UNMATCHED.

    Amount evidence remains the dominant factor.

    We avoid declaring a match merely because the final
    mathematical score is high if the amount relationship
    is poor.

    This prevents a correct date + transaction type from
    incorrectly overpowering a bad settlement amount.
    """

    amount_score = evidence.get(
        "amount_score",
        0
    )

    date_score = evidence.get(
        "date_score",
        0
    )

    # --------------------------------------------------------
    # Exact amount
    # --------------------------------------------------------

    if amount_score >= 74:

        if final_score >= MATCH_THRESHOLD:

            return "MATCHED"

    # --------------------------------------------------------
    # Strong but non-exact amount
    # --------------------------------------------------------

    if amount_score >= 55:

        if final_score >= MATCH_THRESHOLD:

            return "REVIEW"

    # --------------------------------------------------------
    # Weak amount relationship
    # --------------------------------------------------------

    if amount_score < 45:

        return "UNMATCHED"

    # --------------------------------------------------------
    # Middle ground
    # --------------------------------------------------------

    if final_score >= REVIEW_THRESHOLD:

        return "REVIEW"

    return "UNMATCHED"


# ============================================================
# SINGLE SETTLEMENT MATCH
# ============================================================

def match_settlement(
    settlement,
    bank,
    index
):
    """
    Find the best bank statement candidate for one
    Razorpay settlement.

    claimed_bank_indices prevents the same bank transaction
    from being assigned to multiple settlements.
    """

    candidates = []

    for index, bank_row in bank.iterrows():

        if index in claimed_bank_indices:
            continue

        bank_dict = bank_row.to_dict()

        if not is_possible_candidate(
            settlement,
            bank_dict
        ):
            continue

        evidence = score_candidate(
            settlement,
            bank_dict
        )

        candidates.append({
            "bank_index": index,
            "evidence": evidence,
            "evidence_score": evidence["base_score"]
        })

    # --------------------------------------------------------
    # No candidate
    # --------------------------------------------------------

    if not candidates:

        return {
            "bank_index": None,
            "evidence": None,
            "confidence": 0.0,
            "status": "UNMATCHED",
            "ambiguity_penalty": 0.0,
            "ambiguity_type": "none",
            "candidate_count": 0,
            "competing_indices": []
        }

    # --------------------------------------------------------
    # Sort candidates by evidence strength
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["evidence_score"],
        reverse=True
    )

    best = candidates[0]

    competing = candidates[1:]

    competing_scores = [
        candidate["evidence_score"]
        for candidate in competing
    ]

    # --------------------------------------------------------
    # Ambiguity
    # --------------------------------------------------------

    ambiguity_penalty = calculate_ambiguity_penalty(
        best["evidence_score"],
        competing_scores
    )

    ambiguity_type = determine_ambiguity_type(
        best["evidence_score"],
        competing_scores
    )

    final_score = max(
        0.0,
        best["evidence_score"]
        - ambiguity_penalty
    )

    status = determine_status(
        final_score,
        best["evidence"],
        ambiguity_penalty,
        len(candidates)
    )

    # --------------------------------------------------------
    # Competing bank references
    # --------------------------------------------------------

    competing_indices = [
        candidate["bank_index"]
        for candidate in competing
        if candidate["evidence_score"]
        >= best["evidence_score"] - 15
    ]

    return {
        "bank_index": best["bank_index"],

        "evidence": best["evidence"],

        "confidence": round(
            final_score,
            2
        ),

        "status": status,

        "ambiguity_penalty": round(
            ambiguity_penalty,
            2
        ),

        "ambiguity_type":
            ambiguity_type,

        "candidate_count":
            len(candidates),

        "competing_indices":
            competing_indices
    }


# ============================================================
# FULL RECONCILIATION
# ============================================================

def reconcile_settlements(
    settlements,
    bank
):
    """
    Reconcile every Razorpay settlement against the bank.

    Returns:

        results
        unmatched_bank_indices
    """

    results = []

    claimed_bank_indices = set()

    for _, settlement_row in settlements.iterrows():

        settlement = settlement_row.to_dict()

        result = match_settlement(
            settlement,
            bank,
            claimed_bank_indices
        )

        # ----------------------------------------------------
        # Selected bank transaction
        # ----------------------------------------------------

        if result["bank_index"] is not None:

            selected_index = result["bank_index"]

            claimed_bank_indices.add(
                selected_index
            )

            bank_row = bank.loc[
                selected_index
            ]

            bank_reference = get_bank_reference(
                bank_row,
                selected_index
            )

            bank_date = get_bank_date(
                bank_row
            )

            bank_amount = get_bank_amount(
                bank_row
            )

        else:

            bank_reference = None
            bank_date = None
            bank_amount = None

        # ----------------------------------------------------
        # Settlement values
        # ----------------------------------------------------

        settlement_id = settlement.get(
            "settlement_id",
            settlement.get(
                "id",
                ""
            )
        )

        settlement_date = settlement.get(
            "settlement_date"
        )

        net_settlement = get_settlement_amount(
            settlement
        )

        # ----------------------------------------------------
        # Competing references
        # ----------------------------------------------------

        competing_refs = []

        for competing_index in result.get(
            "competing_indices",
            []
        ):

            competing_row = bank.loc[
                competing_index
            ]

            competing_refs.append(
                get_bank_reference(
                    competing_row,
                    competing_index
                )
            )

        # ----------------------------------------------------
        # Result row
        # ----------------------------------------------------

        evidence = result["evidence"]

        results.append({

            "settlement_id":
                settlement_id,

            "settlement_date":
                settlement_date,

            "razorpay_net_settlement":
                net_settlement,

            "bank_reference":
                bank_reference,

            "bank_date":
                bank_date,

            "bank_credit":
                bank_amount,

            "amount_score":
                (
                    evidence["amount_score"]
                    if evidence
                    else 0.0
                ),

            "date_score":
                (
                    evidence["date_score"]
                    if evidence
                    else 0.0
                ),

            "transaction_type_score":
                (
                    evidence[
                        "transaction_type_score"
                    ]
                    if evidence
                    else 0.0
                ),

            "narration_score":
                (
                    evidence[
                        "narration_score"
                    ]
                    if evidence
                    else 0.0
                ),

            "evidence_score":
                (
                    evidence["base_score"]
                    if evidence
                    else 0.0
                ),

            "ambiguity_penalty":
                result["ambiguity_penalty"],

            "confidence":
                result["confidence"],

            "status":
                result["status"],

            "ambiguity_type":
                result.get(
                    "ambiguity_type",
                    "none"
                ),

            "candidate_count":
                result.get(
                    "candidate_count",
                    0
                ),

            "competing_refs":
                competing_refs
        })

    # --------------------------------------------------------
    # Unmatched bank rows
    # --------------------------------------------------------

    unmatched_bank_indices = [
        index
        for index in bank.index
        if index not in claimed_bank_indices
    ]

    return (
        results,
        unmatched_bank_indices
    )