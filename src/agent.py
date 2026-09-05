# ============================================================
# RAZORPAY SETTLEMENT RECONCILIATION AGENT
#
# Current scope:
# Razorpay Settlement -> Bank Statement
# ============================================================

import os
import pandas as pd

from preprocessing import (
    load_csv,
    prepare_settlements,
    prepare_bank_statement,
)

from matching import match_settlement
from ledger_preprocessing import prepare_ledger
from ledger_matching import match_ledger
from source_classification import classify_bank_transactions
from services.llm_reasoner import ReconciliationReasoner

SETTLEMENT_FILE = "data/razorpay_settlements.csv"
BANK_FILE = "data/bank_statement.csv"
LEDGER_FILE = "data/internal_ledger.csv"

OUTPUT_DIR = "output"


def reconcile():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # --------------------------------------------------------
    # LOAD
    # --------------------------------------------------------

def reconcile_settlements(bank):
    settlements = load_csv(
        SETTLEMENT_FILE
    )

    settlements = prepare_settlements(
        settlements
    )

    claimed_bank_indices = set()
    results = []
    
    llm = ReconciliationReasoner()
    
    # --------------------------------------------------------
    # HUMAN OVERRIDES
    # --------------------------------------------------------
    overrides_file = "data/human_overrides.csv"
    overrides = {}
    if os.path.exists(overrides_file):
        try:
            df_overrides = pd.read_csv(overrides_file)
            for _, r in df_overrides.iterrows():
                overrides[r['settlement_id']] = r
        except Exception:
            pass

    # --------------------------------------------------------
    # MATCH
    # --------------------------------------------------------

    for _, settlement in settlements.iterrows():
        
        s_id = settlement.get("settlement_id", settlement.get("id", ""))
        
        # Check human override
        override = overrides.get(s_id)
        if override is not None:
            bank_ref = override.get("bank_reference")
            reason = override.get("reason", "Manual Override")
            user = override.get("user", "Accountant")
            
            # Find the bank row index by reference (if it's not NONE)
            b_index = None
            if bank_ref and bank_ref != "NONE":
                b_matches = bank[bank['bank_reference'] == bank_ref]
                if not b_matches.empty:
                    b_index = b_matches.index[0]
                    claimed_bank_indices.add(b_index)
            
            results.append({
                "settlement_id": s_id,
                "settlement_date": settlement["settlement_date"],
                "settlement_cycle": settlement.get("settlement_cycle", ""),
                "settlement_utr": settlement.get("settlement_utr", ""),
                "razorpay_net_settlement": settlement["net_amount"],
                "bank_reference": bank_ref if bank_ref != "NONE" else None,
                "bank_date": bank.loc[b_index, "bank_date"] if b_index is not None else None,
                "bank_credit": bank.loc[b_index, "bank_amount"] if b_index is not None else None,
                "amount_score": 0, "date_score": 0, "reference_score": 0, "transaction_type_score": 0, "narration_score": 0,
                "base_score": 0,
                "ambiguity_penalty": 0, "ambiguity_type": "none",
                "candidate_count": 0, "top_candidate_2_score": None, "top_candidate_3_score": None,
                "confidence": 100.0 if bank_ref != "NONE" else 0.0,
                "status": "MATCHED" if bank_ref != "NONE" else "UNMATCHED",
                "score_explanation": f"HUMAN OVERRIDE applied by {user}",
                "reason": f"Decision: {reason}"
            })
            continue

        result = match_settlement(
            settlement,
            bank,
            claimed_bank_indices
        )

        if result["bank_index"] is not None:

            selected_index = result["bank_index"]

            bank_row = bank.loc[
                selected_index
            ]

            bank_reference = bank_row[
                "bank_reference"
            ]

            bank_date = bank_row[
                "bank_date"
            ]

            bank_amount = bank_row[
                "bank_amount"
            ]

            # Only consume the bank transaction when
            # the system actually accepts the match.
            if result["status"] in [
                "MATCHED",
                "LIKELY_MATCH"
            ]:
                claimed_bank_indices.add(
                    selected_index
                )

        else:
            
            # 23. Do not output bank_reference = None when there is a known top candidate
            if result.get("candidate_rankings") and len(result["candidate_rankings"]) > 0:
                top_candidate = result["candidate_rankings"][0]
                bank_reference = top_candidate["bank_reference"]
                bank_date = top_candidate["bank_date"]
                bank_amount = top_candidate["bank_amount"]
            else:
                bank_reference = None
                bank_date = None
                bank_amount = None

        results.append({

            "settlement_id": settlement.get(
                "settlement_id",
                settlement.get(
                    "id",
                    ""
                )
            ),

            "settlement_date":
                settlement["settlement_date"],
                
            "settlement_cycle": settlement.get("settlement_cycle", ""),
            "settlement_utr": settlement.get("settlement_utr", ""),

            "razorpay_net_settlement":
                settlement["net_amount"],

            "bank_reference":
                bank_reference,

            "bank_date":
                bank_date,

            "bank_credit":
                bank_amount,

            # -----------------------------
            # Evidence breakdown
            # -----------------------------

            "amount_score":
                (
                    result["evidence"]["amount_score"]
                    if result["evidence"]
                    else 0
                ),

            "date_score":
                (
                    result["evidence"]["date_score"]
                    if result["evidence"]
                    else 0
                ),

            "transaction_type_score":
                (
                    result["evidence"][
                        "transaction_type_score"
                    ]
                    if result["evidence"]
                    else 0
                ),

            "narration_score":
                (
                    result["evidence"]["narration_score"]
                    if result["evidence"]
                    else 0
                ),
                
            "reference_score":
                (
                    result["evidence"]["reference_score"]
                    if result["evidence"]
                    else 0
                ),

            "base_score":
                (
                    result["evidence"]["base_score"]
                    if result["evidence"]
                    else 0
                ),

            # -----------------------------
            # Ambiguity
            # -----------------------------

            "ambiguity_penalty":
                result["ambiguity_penalty"],

            "ambiguity_type":
                result.get(
                    "ambiguity_type",
                    "none"
                ),

            # -----------------------------
            # Candidate information
            # -----------------------------

            "candidate_count":
                result.get(
                    "candidate_count",
                    0
                ),

            "top_candidate_2_score":
                (
                    result["candidate_rankings"][1]["score"]
                    if len(
                        result.get(
                            "candidate_rankings",
                            []
                        )
                    ) > 1
                    else None
                ),

            "top_candidate_3_score":
                (
                    result["candidate_rankings"][2]["score"]
                    if len(
                        result.get(
                            "candidate_rankings",
                            []
                        )
                    ) > 2
                    else None
                ),

            # -----------------------------
            # Final result
            # -----------------------------

            "confidence":
                result["confidence"],

            "status":
                result["status"],
                
            "score_explanation":
                " ".join(result.get("score_explanation", [])),
                
            "reason": llm.explain_ambiguity(result.get("candidate_rankings", [])) if result["status"] == "REVIEW" else ("MATCHED AUTOMATICALLY" if result["status"] == "MATCHED" else "NO VALID CANDIDATES")
        })

    results_df = pd.DataFrame(results)

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    matched = results_df[
        results_df["status"].isin([
            "MATCHED",
            "LIKELY_MATCH",
        ])
    ]

    review = results_df[
        results_df["status"] == "REVIEW"
    ]

    unmatched = results_df[
        results_df["status"] == "UNMATCHED"
    ]

    # Bank rows that were never claimed.
    unmatched_bank = bank[
        ~bank.index.isin(
            claimed_bank_indices
        )
    ].copy()

    matched.to_csv(
        f"{OUTPUT_DIR}/settlement_bank_matched.csv",
        index=False
    )

    review.to_csv(
        f"{OUTPUT_DIR}/settlement_bank_review.csv",
        index=False
    )

    unmatched.to_csv(
        f"{OUTPUT_DIR}/settlement_bank_unmatched.csv",
        index=False
    )

    unmatched_bank.to_csv(
        f"{OUTPUT_DIR}/settlement_bank_unmatched_bank.csv",
        index=False
    )

    # --------------------------------------------------------
    # CONSOLE SUMMARY
    # --------------------------------------------------------

    print("=" * 60)
    print("RAZORPAY SETTLEMENT RECONCILIATION")
    print("=" * 60)

    print(
        f"Razorpay settlements : {len(settlements)}"
    )

    print(
        f"Matched              : {len(matched)}"
    )

    print(
        f"Review               : {len(review)}"
    )

    print(
        f"Unmatched settlements : {len(unmatched)}"
    )

    print(
        f"Unmatched bank rows  : {len(unmatched_bank)}"
    )

    print("-" * 60)

    for _, row in results_df.iterrows():

        print(
            f"{row['settlement_id']} -> "
            f"{row['bank_reference']} | "
            f"{row['status']} | "
            f"Confidence: "
            f"{row['confidence']}%"
        )
        
    return {
        "settlements": len(settlements),
        "matched": len(matched),
        "review": len(review),
        "unmatched": len(unmatched),
        "unmatched_bank": len(unmatched_bank)
    }

def reconcile_ledger(ledger, bank):
    claimed_bank_indices = set()
    results = []
    llm = ReconciliationReasoner()

    for _, row in ledger.iterrows():
        ledger_id = row.get("ledger_id", row.get("invoice_id", ""))
        
        result = match_ledger(row, bank, claimed_bank_indices)
        
        if result["bank_index"] is not None and result["status"] == "MATCHED":
            claimed_bank_indices.add(result["bank_index"])
            bank_row = bank.loc[result["bank_index"]]
            bank_ref = bank_row["bank_reference"]
            bank_date = bank_row["bank_date"]
            bank_amt = bank_row["bank_amount"]
        else:
            if result.get("candidate_rankings") and len(result["candidate_rankings"]) > 0:
                top = result["candidate_rankings"][0]
                bank_ref = top["bank_reference"]
                bank_date = top["bank_date"]
                bank_amt = top["bank_amount"]
            else:
                bank_ref = None
                bank_date = None
                bank_amt = None
        
        ev = result["evidence"]
        
        # Generate LLM reasoning for REVIEW cases
        if result["status"] == "REVIEW":
            reason = llm.explain_match(
                source_type="ledger",
                evidence=ev,
                confidence=result["confidence"],
                status=result["status"],
                candidate_info={
                    "bank_reference": bank_ref,
                    "bank_amount": bank_amt,
                    "bank_date": str(bank_date),
                }
            )
        elif result["status"] == "MATCHED":
            reason = "MATCHED AUTOMATICALLY"
        else:
            reason = "NO VALID CANDIDATES"

        results.append({
            "ledger_id": ledger_id,
            "invoice_id": row.get("invoice_id", ""),
            "ledger_date": row["ledger_date"],
            "ledger_amount": row["ledger_amount"],
            "customer_name": row["customer_name"],
            "payment_mode": row["payment_method"],
            "bank_reference": bank_ref,
            "bank_date": bank_date,
            "bank_amount": bank_amt,
            "amount_score": ev["amount_score"] if ev else 0,
            "date_score": ev["date_score"] if ev else 0,
            # Reference is N/A for ledger — preserve None
            "reference_score": ev.get("reference_score") if ev else None,
            "reference_applicable": ev.get("reference_applicable", False) if ev else False,
            "party_score": ev["party_score"] if ev else 0,
            "transaction_type_score": ev["transaction_type_score"] if ev else 0,
            "narration_score": ev["narration_score"] if ev else 0,
            "base_score": ev["base_score"] if ev else 0,
            "ambiguity_penalty": result["ambiguity_penalty"],
            "confidence": result["confidence"],
            "status": result["status"],
            "score_explanation": " ".join(result.get("score_explanation", [])),
            "reason": reason,
        })

    results_df = pd.DataFrame(results)

    matched = results_df[results_df["status"] == "MATCHED"]
    review = results_df[results_df["status"] == "REVIEW"]
    unmatched = results_df[results_df["status"] == "UNMATCHED"]
    unmatched_bank = bank[~bank.index.isin(claimed_bank_indices)]

    matched.to_csv(f"{OUTPUT_DIR}/ledger_bank_matched.csv", index=False)
    review.to_csv(f"{OUTPUT_DIR}/ledger_bank_review.csv", index=False)
    unmatched.to_csv(f"{OUTPUT_DIR}/ledger_bank_unmatched.csv", index=False)
    unmatched_bank.to_csv(f"{OUTPUT_DIR}/ledger_bank_unmatched_bank.csv", index=False)
    results_df.to_csv(f"{OUTPUT_DIR}/ledger_bank_all.csv", index=False)

    print("=" * 60)
    print("LEDGER STATEMENT RECONCILIATION")
    print("=" * 60)
    print(f"Ledger entries       : {len(ledger)}")
    print(f"Matched              : {len(matched)}")
    print(f"Review               : {len(review)}")
    print(f"Unmatched ledger     : {len(unmatched)}")
    print(f"Unmatched bank rows  : {len(unmatched_bank)}")
    print("-" * 60)

    for _, row in results_df.iterrows():
        print(f"{row['ledger_id']} -> {row['bank_reference']} | {row['status']} | Confidence: {row['confidence']}%")
    
    # Print LLM status
    llm_status = llm.get_status()
    print(f"\nLLM Status: {'Available' if llm_status['llm_available'] else 'Unavailable'}")
    if llm_status['quota_exhausted']:
        print("LLM: Quota exhausted — deterministic fallback used for remaining items.")
    print(f"LLM calls made: {llm_status['calls_made']}/{llm_status['calls_remaining'] + llm_status['calls_made']}")
        
    return {
        "ledger_entries": len(ledger),
        "matched": len(matched),
        "review": len(review),
        "unmatched": len(unmatched),
        "unmatched_bank": len(unmatched_bank)
    }

def reconcile():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Load and Preprocess Bank
    bank = load_csv(BANK_FILE)
    bank = prepare_bank_statement(bank)
    
    # Load and Preprocess Ledger
    ledger = load_csv(LEDGER_FILE)
    ledger = prepare_ledger(ledger)
    
    # Source Classification
    bank = classify_bank_transactions(bank, ledger)
    
    bank.to_csv(f"{OUTPUT_DIR}/bank_source_classification.csv", index=False)
    bank[bank['source'] == 'UNKNOWN'].to_csv(f"{OUTPUT_DIR}/bank_source_review.csv", index=False)
    
    # Split Data by Classification
    bank_razorpay = bank[bank["source"] == "RAZORPAY"].copy()
    # Ledger recon runs against all NON-Razorpay credits.
    # The source classifier is conservative — many genuine ledger
    # payments end up as UNKNOWN. The ledger evidence engine will
    # score them properly; we should not pre-exclude them.
    bank_ledger = bank[bank["source"] != "RAZORPAY"].copy()
    
    # Path 1: Razorpay Settlement Recon
    s_stats = reconcile_settlements(bank_razorpay)
    
    # Path 2: Ledger Recon
    l_stats = reconcile_ledger(ledger, bank_ledger)
    
    # Count Classification Results
    rzp_count = (bank['source'] == 'RAZORPAY').sum()
    ledger_count = (bank['source'] == 'DIRECT_LEDGER').sum()
    unknown_count = (bank['source'] == 'UNKNOWN').sum()
    
    print("\n" + "=" * 60)
    print("RECONCILIATION SUMMARY")
    print("=" * 60)
    print("SOURCE CLASSIFICATION")
    print(f"Razorpay             : {rzp_count}")
    print(f"Direct Ledger        : {ledger_count}")
    print(f"Unknown (Review)     : {unknown_count}")
    
    print("\nRAZORPAY SETTLEMENT -> BANK")
    print(f"Settlements          : {s_stats['settlements']}")
    print(f"Matched              : {s_stats['matched']}")
    print(f"Review               : {s_stats['review']}")
    print(f"Unmatched            : {s_stats['unmatched']}")
    print(f"Unmatched bank rows  : {s_stats['unmatched_bank']}")
    
    print("\nLEDGER -> BANK")
    print(f"Ledger entries       : {l_stats['ledger_entries']}")
    print(f"Matched              : {l_stats['matched']}")
    print(f"Review               : {l_stats['review']}")
    print(f"Unmatched            : {l_stats['unmatched']}")
    print(f"Unmatched bank rows  : {l_stats['unmatched_bank']}")
    print("=" * 60)


if __name__ == "__main__":
    reconcile()