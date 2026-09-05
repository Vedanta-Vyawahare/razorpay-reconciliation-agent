"""
Ledger -> Bank matching engine.

Decision policy:
    Amount = 80%
    Date   = 15%
    Type   = 5%
    Name   = 0% (diagnostic only)
    UTR    = N/A

Candidate discovery is deliberately broad. Amount mismatches are
scored, not used to discard candidates early.
"""

import pandas as pd
from ledger_evidence import calculate_ledger_evidence
from services.date_reasoning import business_day_difference

LEDGER_CLAIM_THRESHOLD = 85.0
LEDGER_REVIEW_THRESHOLD = 55.0
LEDGER_MIN_CANDIDATE_SCORE = 15.0
LEDGER_DATE_WINDOW = 15
LEDGER_AMBIGUITY_MARGIN = 8.0

def _date_distance(a, b):
    try:
        if a is None or b is None or pd.isna(a) or pd.isna(b):
            return None
        return abs(business_day_difference(a, b))
    except Exception:
        return None

def generate_ledger_candidates(ledger_row, bank_df, claimed_bank_indices):
    candidates = []
    ledger_date = ledger_row.get("ledger_date")

    for i, bank_row in bank_df.iterrows():
        if i in claimed_bank_indices:
            continue
        if not bool(bank_row.get("is_credit", False)):
            continue

        distance = _date_distance(ledger_date, bank_row.get("bank_date"))
        if distance is not None and distance > LEDGER_DATE_WINDOW:
            continue

        evidence = calculate_ledger_evidence(ledger_row, bank_row)
        score = float(evidence.get("base_score", 0.0))

        if score < LEDGER_MIN_CANDIDATE_SCORE:
            continue

        candidates.append({
            "bank_index": i,
            "bank_reference": bank_row.get("bank_reference"),
            "bank_date": bank_row.get("bank_date"),
            "bank_amount": bank_row.get("bank_amount"),
            "bank_transaction_type": bank_row.get("transaction_type"),
            "bank_narration": bank_row.get("narration"),
            "score": score,
            "evidence": evidence,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates

def _build_explanation(ledger_row, top):
    ev = top["evidence"]
    parts = []

    if ev["amount_score"] >= 79.99:
        parts.append("Exact amount match (80% weight).")
    elif ev["amount_score"] >= 60:
        parts.append(f"Strong amount evidence ({ev['amount_score']:.1f}/80).")
    elif ev["amount_score"] > 0:
        parts.append(f"Partial amount evidence ({ev['amount_score']:.1f}/80).")
    else:
        parts.append("Amount mismatch.")

    if ev["date_score"] >= 14.99:
        parts.append("Exact settlement-date match (15% weight).")
    elif ev["date_score"] > 0:
        parts.append(f"Date provides supporting evidence ({ev['date_score']:.1f}/15).")
    else:
        parts.append("Date provides no evidence.")

    if ev["transaction_type_score"] >= 4.99:
        parts.append("Payment type is compatible (5% weight).")
    elif ev["transaction_type_score"] > 0:
        parts.append("Payment type provides partial support.")
    else:
        parts.append("Payment type does not provide support.")

    if ev.get("name_match_diagnostic"):
        parts.append("Name matched in narration, but name is diagnostic only.")
    else:
        parts.append("Name differs/not found; intentionally not used in the decision.")

    parts.append("UTR/reference is not applicable to ledger reconciliation.")
    return parts

def match_ledger(ledger_row, bank_df, claimed_bank_indices):
    candidates = generate_ledger_candidates(
        ledger_row, bank_df, claimed_bank_indices
    )

    result = {
        "status": "UNMATCHED",
        "bank_index": None,
        "confidence": 0.0,
        "evidence": None,
        "ambiguity_penalty": 0.0,
        "ambiguity_type": "none",
        "candidate_count": len(candidates),
        "candidate_rankings": candidates,
        "score_explanation": [],
    }

    if not candidates:
        result["score_explanation"] = [
            "No credit candidate within the allowed settlement-date window."
        ]
        return result

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    top_score = float(top["score"])
    second_score = float(second["score"]) if second else None
    result["evidence"] = top["evidence"]

    explanation = _build_explanation(ledger_row, top)

    # One candidate: high evidence can be auto-matched.
    if second is None:
        if top_score >= LEDGER_CLAIM_THRESHOLD:
            result["status"] = "MATCHED"
            result["bank_index"] = top["bank_index"]
        elif top_score >= LEDGER_REVIEW_THRESHOLD:
            result["status"] = "REVIEW"
        else:
            result["status"] = "UNMATCHED"
        result["confidence"] = round(top_score, 2)
        result["score_explanation"] = explanation + [
            f"Single best candidate scored {top_score:.2f}%."
        ]
        return result

    margin = top_score - second_score

    # A high-scoring candidate still needs a meaningful lead if
    # another bank row is nearly as plausible.
    if top_score >= LEDGER_CLAIM_THRESHOLD and margin >= LEDGER_AMBIGUITY_MARGIN:
        result["status"] = "MATCHED"
        result["bank_index"] = top["bank_index"]
        result["confidence"] = round(top_score, 2)
        result["score_explanation"] = explanation + [
            f"Clear winner over second candidate by {margin:.2f} points."
        ]
        return result

    if top_score >= LEDGER_REVIEW_THRESHOLD:
        result["status"] = "REVIEW"
        result["confidence"] = round(top_score, 2)
        result["ambiguity_type"] = (
            "multiple_strong_candidates"
            if margin < LEDGER_AMBIGUITY_MARGIN
            else "best_candidate_below_auto_match"
        )
        result["score_explanation"] = explanation + [
            f"Top candidate scored {top_score:.2f}%; second scored {second_score:.2f}%.",
            "Manual review required because the deterministic evidence is not sufficiently decisive.",
        ]
        return result

    result["status"] = "UNMATCHED"
    result["confidence"] = round(top_score, 2)
    result["ambiguity_type"] = "weak_candidates"
    result["score_explanation"] = explanation + [
        f"Best candidate scored only {top_score:.2f}%."
    ]
    return result
