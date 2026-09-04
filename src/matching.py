from evidence import calculate_evidence
from config import AMBIGUITY_PENALTIES


def find_candidates(settlement, bank_df, claimed_bank_indices):
    """
    Find all plausible incoming bank transactions.

    IMPORTANT:
    We do not throw away a candidate merely because
    its amount is different.

    The evidence layer decides how strong the candidate is.
    """

    candidates = []

    for index, bank_row in bank_df.iterrows():

        # Already accepted by another settlement.
        if index in claimed_bank_indices:
            continue

        # Razorpay settlement should normally appear
        # as an incoming bank credit.
        if not bank_row["is_credit"]:
            continue

        evidence = calculate_evidence(
            settlement,
            bank_row
        )

        if evidence["base_score"] <= 0:
            continue

        candidates.append({
            "bank_index": index,
            "evidence": evidence
        })

    return candidates


def determine_ambiguity(best, candidates):
    """
    Compare the best candidate against competing candidates.

    Ambiguity is intentionally a SMALL penalty.

    A strong match should remain strong even when
    another weak candidate exists.
    """

    if len(candidates) <= 1:
        return 0.0, "none"

    best_score = best["evidence"]["base_score"]

    competitors = [
        candidate
        for candidate in candidates
        if candidate["bank_index"] != best["bank_index"]
    ]

    strong_competitors = []

    for candidate in competitors:

        candidate_score = (
            candidate["evidence"]["base_score"]
        )

        score_difference = (
            best_score - candidate_score
        )

        # Candidate is close enough to deserve
        # ambiguity consideration.
        if score_difference <= 2:
            strong_competitors.append(
                candidate
            )

    count = len(strong_competitors)

    if count == 0:
        return 0.0, "none"

    if count == 1:

        competitor_score = (
            strong_competitors[0]
            ["evidence"]
            ["base_score"]
        )

        difference = (
            best_score - competitor_score
        )

        if difference >= 8:
            return (
                AMBIGUITY_PENALTIES["weak"],
                "weak"
            )

        return (
            AMBIGUITY_PENALTIES["reasonable"],
            "reasonable"
        )

    if count == 2:
        return (
            AMBIGUITY_PENALTIES["strong"],
            "strong"
        )

    return (
        AMBIGUITY_PENALTIES["multiple"],
        "multiple"
    )


def get_status(confidence):
    """
    Convert evidence confidence into a reconciliation state.
    """

    if confidence >= 95:
        return "MATCHED"

    if confidence >= 80:
        return "LIKELY_MATCH"

    if confidence >= 60:
        return "REVIEW"

    return "UNMATCHED"


def match_settlement(
    settlement,
    bank_df,
    claimed_bank_indices
):
    """
    Match one Razorpay settlement against the bank statement.

    Returns:
        - best candidate
        - confidence
        - complete evidence breakdown
        - candidate ranking
        - ambiguity information
    """

    candidates = find_candidates(
        settlement,
        bank_df,
        claimed_bank_indices
    )

    if not candidates:

        return {
            "status": "UNMATCHED",
            "confidence": 0.0,
            "bank_index": None,
            "evidence": None,
            "ambiguity_penalty": 0.0,
            "ambiguity_type": "none",
            "candidate_count": 0,
            "candidate_rankings": []
        }

    # Highest evidence first.
    candidates.sort(
        key=lambda candidate:
        candidate["evidence"]["base_score"],
        reverse=True
    )

    best = candidates[0]

    ambiguity_penalty, ambiguity_type = (
        determine_ambiguity(
            best,
            candidates
        )
    )

    final_confidence = max(
        0.0,
        best["evidence"]["base_score"]
        - ambiguity_penalty
    )

    status = get_status(
        final_confidence
    )

    # --------------------------------------------------
    # Save ranked candidates for auditing.
    # --------------------------------------------------

    candidate_rankings = []

    for rank, candidate in enumerate(
        candidates[:5],
        start=1
    ):

        evidence = candidate["evidence"]

        candidate_rankings.append({
            "rank": rank,
            "bank_index": candidate["bank_index"],
            "score": round(
                evidence["base_score"],
                2
            ),
            "amount_score": round(
                evidence["amount_score"],
                2
            ),
            "date_score": round(
                evidence["date_score"],
                2
            ),
            "transaction_type_score": round(
                evidence["transaction_type_score"],
                2
            ),
            "narration_score": round(
                evidence["narration_score"],
                2
            )
        })

    return {
        "status": status,

        "confidence": round(
            final_confidence,
            2
        ),

        "bank_index": best["bank_index"],

        "evidence": best["evidence"],

        "ambiguity_penalty": round(
            ambiguity_penalty,
            2
        ),

        "ambiguity_type": ambiguity_type,

        "candidate_count": len(candidates),

        "candidate_rankings": candidate_rankings
    }