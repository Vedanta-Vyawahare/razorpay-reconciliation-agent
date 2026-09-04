"""Documentation for matching.py

Purpose:
Matches each Razorpay settlement against possible bank statement credits.

The engine:

Removes bank debits from consideration.
Scores each possible bank credit.
Ranks candidates by evidence strength.
Checks whether competing candidates are nearly as strong.
Applies a small ambiguity penalty of up to 1%.
Produces a final confidence score.

Current result categories:

MATCHED: confidence ≥ 95%
LIKELY_MATCH: confidence ≥ 80%
REVIEW: confidence ≥ 60%
UNMATCHED: confidence < 60%

Ambiguity does not dominate the score. It only slightly reduces confidence when multiple candidates are similarly plausible."""

from evidence import calculate_evidence
from config import AMBIGUITY_PENALTIES


def find_candidates(settlement, bank_df):

    candidates = []

    for index, bank_row in bank_df.iterrows():

        # Only incoming money can represent
        # a normal Razorpay settlement.
        if not bank_row["is_credit"]:
            continue

        evidence = calculate_evidence(
            settlement,
            bank_row
        )

        # Keep candidates with SOME evidence.
        # We no longer require amount to be close.
        if evidence["base_score"] <= 0:
            continue

        candidates.append({
            "bank_index": index,
            "evidence": evidence,
        })

    return candidates


def determine_ambiguity(best, candidates):

    if len(candidates) <= 1:
        return 0.0, "none"

    best_score = best["evidence"]["base_score"]

    competitors = [
        c for c in candidates
        if c["bank_index"] != best["bank_index"]
    ]

    strong_competitors = []

    for candidate in competitors:

        candidate_score = (
            candidate["evidence"]["base_score"]
        )

        difference = (
            best_score - candidate_score
        )

        # Candidate is genuinely close to the winner.
        if difference <= 2:
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


def match_settlement(settlement, bank_df):

    candidates = find_candidates(
        settlement,
        bank_df
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
        }

    # Highest evidence first.
    candidates.sort(
        key=lambda x: x["evidence"]["base_score"],
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

    if final_confidence >= 95:
        status = "MATCHED"

    elif final_confidence >= 80:
        status = "LIKELY_MATCH"

    elif final_confidence >= 60:
        status = "REVIEW"

    else:
        status = "UNMATCHED"

    return {
        "status": status,
        "confidence": round(
            final_confidence,
            2
        ),
        "bank_index": best["bank_index"],
        "evidence": best["evidence"],
        "ambiguity_penalty": ambiguity_penalty,
        "ambiguity_type": ambiguity_type,
        "candidate_count": len(candidates),
    }