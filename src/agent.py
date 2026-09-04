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


SETTLEMENT_FILE = "data/razorpay_settlements.csv"
BANK_FILE = "data/bank_statement.csv"

OUTPUT_DIR = "output"


def reconcile():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # --------------------------------------------------------
    # LOAD
    # --------------------------------------------------------

    settlements = load_csv(
        SETTLEMENT_FILE
    )

    bank = load_csv(
        BANK_FILE
    )

    # --------------------------------------------------------
    # PREPROCESS
    # --------------------------------------------------------

    settlements = prepare_settlements(
        settlements
    )

    bank = prepare_bank_statement(
        bank
    )
    claimed_bank_indices = set()
    results = []
    # --------------------------------------------------------
    # MATCH
    # --------------------------------------------------------


    for _, settlement in settlements.iterrows():

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

    print("=" * 60)

    for _, row in results_df.iterrows():

        print(
            f"{row['settlement_id']} -> "
            f"{row['bank_reference']} | "
            f"{row['status']} | "
            f"Confidence: "
            f"{row['confidence']}%"
        )


if __name__ == "__main__":
    reconcile()