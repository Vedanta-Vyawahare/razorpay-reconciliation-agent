import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

AMOUNT_WEIGHT = 0.80
DATE_WEIGHT = 0.12
TYPE_WEIGHT = 0.05
AMBIGUITY_WEIGHT = 0.03


# ============================================================
# LOAD DATA
# ============================================================

ledger = pd.read_csv("data/internal_ledger.csv")
bank = pd.read_csv("data/bank_statement.csv")


# ============================================================
# PARSE BANK DETAILS
# ============================================================

def parse_details(details):
    details = str(details)
    parts = details.split("/")

    if details.startswith("UPI"):
        name = parts[3] if len(parts) > 3 else None
        return {"type": "UPI", "name": name}

    elif details.startswith("NEFT"):
        name = parts[2] if len(parts) > 2 else None
        return {"type": "NEFT", "name": name}

    elif details.startswith("CARD"):
        name = parts[3] if len(parts) > 3 else None
        return {"type": "CARD", "name": name}

    return {"type": "UNKNOWN", "name": None}


bank["parsed"] = bank["Details"].apply(parse_details)

bank["sender_name"] = bank["parsed"].apply(
    lambda x: x["name"]
)

bank["txn_type"] = bank["parsed"].apply(
    lambda x: x["type"]
)


# ============================================================
# DATE PREPARATION
# ============================================================

ledger["Invoice Date"] = pd.to_datetime(
    ledger["Invoice Date"],
    errors="coerce"
)

bank["Value Date"] = pd.to_datetime(
    bank["Value Date"],
    dayfirst=True,
    errors="coerce"
)


# ============================================================
# AMOUNT EVIDENCE
# ============================================================

def analyze_amount(ledger_amount, bank_amount):

    ledger_amount = float(ledger_amount)
    bank_amount = float(bank_amount)

    gap = round(ledger_amount - bank_amount, 2)

    if ledger_amount == 0:
        gap_pct = 100.0
    else:
        gap_pct = abs(gap) / ledger_amount * 100

    gap_pct = round(gap_pct, 4)

    # --------------------------------------------
    # Exact
    # --------------------------------------------

    if abs(gap) <= 0.01:

        category = "EXACT"
        score = 100

    # --------------------------------------------
    # Very small difference
    # --------------------------------------------

    elif gap_pct <= 0.10:

        category = "TINY_DIFFERENCE"
        score = 95

    # --------------------------------------------
    # Small deduction
    # --------------------------------------------

    elif gap_pct <= 2:

        category = "SMALL_DEDUCTION"
        score = 85

    # --------------------------------------------
    # Moderate deduction
    # --------------------------------------------

    elif gap_pct <= 5:

        category = "MODERATE_DEDUCTION"
        score = 70

    # --------------------------------------------
    # Possible partial payment / large deduction
    # --------------------------------------------

    elif gap_pct <= 20:

        category = "LARGE_DIFFERENCE"
        score = 45

    # --------------------------------------------
    # Very weak amount relationship
    # --------------------------------------------

    else:

        category = "VERY_LARGE_DIFFERENCE"
        score = 0

    return {
        "gap": gap,
        "gap_pct": gap_pct,
        "amount_category": category,
        "amount_score": score
    }


# ============================================================
# DATE / SETTLEMENT EVIDENCE
# ============================================================

def analyze_date(invoice_date, bank_date):

    if pd.isna(invoice_date) or pd.isna(bank_date):

        return {
            "date_gap": None,
            "settlement_category": "UNKNOWN",
            "date_score": 0
        }

    # Important:
    # We do NOT use absolute date difference.
    # T+1 and T+2 are legitimate settlement behaviour.

    date_difference = (
        bank_date - invoice_date
    ).days

    # --------------------------------------------
    # Same day
    # --------------------------------------------

    if date_difference == 0:

        category = "SAME_DAY"
        score = 100

    # --------------------------------------------
    # T+1
    # --------------------------------------------

    elif date_difference == 1:

        category = "T_PLUS_1"
        score = 95

    # --------------------------------------------
    # T+2
    # --------------------------------------------

    elif date_difference == 2:

        category = "T_PLUS_2"
        score = 90

    # --------------------------------------------
    # T+3
    # --------------------------------------------

    elif date_difference == 3:

        category = "T_PLUS_3"
        score = 65

    # --------------------------------------------
    # Before invoice date
    # --------------------------------------------

    elif date_difference < 0:

        category = "BEFORE_INVOICE"
        score = 25

    # --------------------------------------------
    # Very late settlement
    # --------------------------------------------

    else:

        category = "LATE_SETTLEMENT"
        score = 20

    return {
        "date_gap": date_difference,
        "settlement_category": category,
        "date_score": score
    }


# ============================================================
# TRANSACTION TYPE EVIDENCE
# ============================================================

def analyze_transaction_type(bank_type):

    # This is deliberately a SMALL signal.
    #
    # We don't assume that UPI/CARD/NEFT tells us
    # exactly how the ledger was paid.
    #
    # It is supporting evidence only.

    if bank_type in ["UPI", "CARD", "NEFT"]:

        return {
            "type_score": 100,
            "type_evidence": bank_type
        }

    return {
        "type_score": 50,
        "type_evidence": "UNKNOWN"
    }


# ============================================================
# COMBINE EVIDENCE
# ============================================================

def calculate_evidence_score(
    amount_evidence,
    date_evidence,
    type_evidence
):

    amount_component = (
        amount_evidence["amount_score"]
        * AMOUNT_WEIGHT
    )

    date_component = (
        date_evidence["date_score"]
        * DATE_WEIGHT
    )

    type_component = (
        type_evidence["type_score"]
        * TYPE_WEIGHT
    )

    base_score = (
        amount_component
        + date_component
        + type_component
    )

    return round(base_score, 2)


# ============================================================
# BUILD CANDIDATE
# ============================================================

def evaluate_candidate(invoice, bank_row):

    amount_evidence = analyze_amount(
        invoice["Total Amount"],
        bank_row["Credit"]
    )

    date_evidence = analyze_date(
        invoice["Invoice Date"],
        bank_row["Value Date"]
    )

    type_evidence = analyze_transaction_type(
        bank_row["txn_type"]
    )

    evidence_score = calculate_evidence_score(
        amount_evidence,
        date_evidence,
        type_evidence
    )

    return {

        "invoice_id": invoice["Invoice ID"],

        "bank_ref": bank_row["Ref No"],

        "ledger_amount": float(
            invoice["Total Amount"]
        ),

        "bank_amount": float(
            bank_row["Credit"]
        ),

        "gap": amount_evidence["gap"],

        "gap_pct": amount_evidence["gap_pct"],

        "amount_category":
            amount_evidence["amount_category"],

        "amount_score":
            amount_evidence["amount_score"],

        "date_gap":
            date_evidence["date_gap"],

        "settlement_category":
            date_evidence["settlement_category"],

        "date_score":
            date_evidence["date_score"],

        "transaction_type":
            bank_row["txn_type"],

        "type_score":
            type_evidence["type_score"],

        "evidence_score":
            evidence_score
    }


# ============================================================
# FIND ALL CANDIDATES
# ============================================================

def find_candidates(invoice, bank_df, claimed_refs):

    candidates = []

    for _, bank_row in bank_df.iterrows():

        ref = bank_row["Ref No"]

        # Already assigned to another invoice
        if ref in claimed_refs:
            continue

        candidate = evaluate_candidate(
            invoice,
            bank_row
        )

        # ----------------------------------------------------
        # Do NOT use customer name as a hard filter.
        #
        # The bank statement and ledger do not share a
        # guaranteed identity field.
        # ----------------------------------------------------

        # Completely unreasonable amount relationships
        # can still be removed to reduce search space.
        #
        # But keep reasonably sized differences because
        # they may represent fees, refunds, commissions,
        # partial payments, etc.

        if candidate["gap_pct"] > 50:
            continue

        # Very late transactions are weak candidates.
        # We keep them only if the amount evidence is strong.
        if (
            candidate["date_gap"] is not None
            and candidate["date_gap"] > 7
            and candidate["amount_score"] < 95
        ):
            continue

        candidates.append(candidate)

    return sorted(
        candidates,
        key=lambda x: (
            -x["evidence_score"],
            x["gap_pct"]
        )
    )


# ============================================================
# AMBIGUITY ANALYSIS
# ============================================================

def analyze_ambiguity(candidates):

    if len(candidates) <= 1:

        return {
            "is_ambiguous": False,
            "ambiguity_penalty": 0,
            "competing_refs": []
        }

    best = candidates[0]

    # Candidates close to the best candidate
    rivals = []

    for candidate in candidates[1:]:

        score_difference = (
            best["evidence_score"]
            - candidate["evidence_score"]
        )

        # 5 points is deliberately a small tolerance.
        if score_difference <= 5:

            rivals.append(candidate)

    if not rivals:

        return {
            "is_ambiguous": False,
            "ambiguity_penalty": 0,
            "competing_refs": []
        }

    # Ambiguity is a PENALTY.
    #
    # More strong competitors = greater uncertainty.

    if len(rivals) == 1:
        penalty = 5

    elif len(rivals) == 2:
        penalty = 8

    else:
        penalty = 10

    return {
        "is_ambiguous": True,
        "ambiguity_penalty": penalty,
        "competing_refs": [
            r["bank_ref"]
            for r in rivals
        ]
    }


# ============================================================
# FINAL CANDIDATE SCORE
# ============================================================

def apply_ambiguity(candidate, ambiguity):

    penalty = (
        ambiguity["ambiguity_penalty"]
        * AMBIGUITY_WEIGHT
    )

    # Ambiguity weight is intentionally tiny.
    final_score = round(
        candidate["evidence_score"] - penalty,
        2
    )

    candidate["ambiguity_penalty"] = penalty
    candidate["final_score"] = final_score

    candidate["competing_refs"] = (
        ambiguity["competing_refs"]
    )

    return candidate


# ============================================================
# DECISION ENGINE
# ============================================================

def classify_candidate(candidate, ambiguity):

    score = candidate["final_score"]

    # --------------------------------------------------------
    # Ambiguous candidates always require review.
    # --------------------------------------------------------

    if ambiguity["is_ambiguous"]:

        candidate["decision"] = "AMBIGUOUS"

        candidate["reason"] = (
            "Multiple bank transactions have "
            "similar supporting evidence."
        )

        candidate["requires_human_review"] = True

        return candidate

    # --------------------------------------------------------
    # Exact amount
    # --------------------------------------------------------

    if candidate["amount_category"] == "EXACT":

        candidate["decision"] = "MATCHED"

        candidate["reason"] = (
            "Bank transaction matches the ledger "
            "amount exactly."
        )

        candidate["requires_human_review"] = False

        return candidate

    # --------------------------------------------------------
    # Small/moderate difference
    # --------------------------------------------------------

    if candidate["amount_category"] in [
        "TINY_DIFFERENCE",
        "SMALL_DEDUCTION",
        "MODERATE_DEDUCTION"
    ]:

        candidate["decision"] = "EXCEPTION"

        candidate["reason"] = (
            "A strong candidate exists, but the "
            "settled amount differs from the ledger."
        )

        candidate["requires_human_review"] = False

        return candidate

    # --------------------------------------------------------
    # Large difference
    # --------------------------------------------------------

    if candidate["amount_category"] == "LARGE_DIFFERENCE":

        candidate["decision"] = "EXCEPTION"

        candidate["reason"] = (
            "A possible bank transaction was found, "
            "but the amount difference is significant."
        )

        candidate["requires_human_review"] = True

        return candidate

    # --------------------------------------------------------
    # Weak evidence
    # --------------------------------------------------------

    candidate["decision"] = "HUMAN_REVIEW"

    candidate["reason"] = (
        "No sufficiently strong reconciliation "
        "explanation was established."
    )

    candidate["requires_human_review"] = True

    return candidate


# ============================================================
# RECONCILIATION
# ============================================================

def reconcile(ledger, bank):

    matched = []
    exceptions = []

    claimed_invoices = set()
    claimed_bank_refs = set()

    # --------------------------------------------------------
    # Evaluate invoices independently first.
    #
    # We do NOT immediately claim a bank transaction while
    # looking at candidates.
    # --------------------------------------------------------

    invoice_results = []

    for _, invoice in ledger.iterrows():

        candidates = find_candidates(
            invoice,
            bank,
            claimed_bank_refs
        )

        if not candidates:

            invoice_results.append({
                "invoice_id": invoice["Invoice ID"],
                "candidates": []
            })

            continue

        ambiguity = analyze_ambiguity(
            candidates
        )

        best = apply_ambiguity(
            candidates[0].copy(),
            ambiguity
        )

        best = classify_candidate(
            best,
            ambiguity
        )

        invoice_results.append({
            "invoice_id": invoice["Invoice ID"],
            "result": best,
            "candidates": candidates
        })

    # --------------------------------------------------------
    # Process results.
    # --------------------------------------------------------

    for result in invoice_results:

        if "result" not in result:
            continue

        candidate = result["result"]

        invoice_id = candidate["invoice_id"]
        bank_ref = candidate["bank_ref"]

        # ----------------------------------------------------
        # Ambiguous:
        # DO NOT claim either side.
        # ----------------------------------------------------

        if candidate["decision"] == "AMBIGUOUS":

            exceptions.append(candidate)

            continue

        # ----------------------------------------------------
        # Already claimed by a previous strong match.
        # ----------------------------------------------------

        if (
            invoice_id in claimed_invoices
            or bank_ref in claimed_bank_refs
        ):
            continue

        # ----------------------------------------------------
        # Claim unique candidate.
        # ----------------------------------------------------

        claimed_invoices.add(invoice_id)
        claimed_bank_refs.add(bank_ref)

        if candidate["decision"] == "MATCHED":

            matched.append(candidate)

        else:

            exceptions.append(candidate)

    # ========================================================
    # UNMATCHED
    # ========================================================

    unmatched_ledger = [
        invoice_id
        for invoice_id in ledger["Invoice ID"]
        if invoice_id not in claimed_invoices
    ]

    unmatched_bank = [
        ref
        for ref in bank["Ref No"]
        if ref not in claimed_bank_refs
    ]

    return (
        matched,
        exceptions,
        unmatched_ledger,
        unmatched_bank
    )


# ============================================================
# RUN
# ============================================================

matched, exceptions, unmatched_ledger, unmatched_bank = (
    reconcile(
        ledger,
        bank
    )
)


# ============================================================
# PRINT RESULTS
# ============================================================

print("=" * 70)
print("AI FINANCE CONTROLLER - EVIDENCE ENGINE")
print("=" * 70)

print("\nWEIGHTS")
print(f"Amount:       {AMOUNT_WEIGHT * 100:.0f}%")
print(f"Settlement:   {DATE_WEIGHT * 100:.0f}%")
print(f"Transaction:  {TYPE_WEIGHT * 100:.0f}%")
print(f"Ambiguity:    {AMBIGUITY_WEIGHT * 100:.0f}% penalty")


print("\n" + "=" * 70)
print(f"MATCHED: {len(matched)}")
print("=" * 70)

for item in matched:

    print(
        f"\n{item['invoice_id']} -> {item['bank_ref']}"
    )

    print(
        f"  Amount: ₹{item['ledger_amount']:.2f}"
        f" -> ₹{item['bank_amount']:.2f}"
    )

    print(
        f"  Gap: ₹{item['gap']:.2f}"
        f" ({item['gap_pct']:.2f}%)"
    )

    print(
        f"  Settlement: {item['settlement_category']}"
    )

    print(
        f"  Type: {item['transaction_type']}"
    )

    print(
        f"  Evidence score: {item['final_score']:.2f}"
    )


print("\n" + "=" * 70)
print(f"EXCEPTIONS: {len(exceptions)}")
print("=" * 70)

for item in exceptions:

    print(
        f"\n{item['invoice_id']} -> {item['bank_ref']}"
    )

    print(
        f"  Decision: {item['decision']}"
    )

    print(
        f"  Amount: ₹{item['ledger_amount']:.2f}"
        f" -> ₹{item['bank_amount']:.2f}"
    )

    print(
        f"  Gap: ₹{item['gap']:.2f}"
        f" ({item['gap_pct']:.2f}%)"
    )

    print(
        f"  Amount category: "
        f"{item['amount_category']}"
    )

    print(
        f"  Settlement: "
        f"{item['settlement_category']}"
    )

    print(
        f"  Evidence score: "
        f"{item['final_score']:.2f}"
    )

    print(
        f"  Human review: "
        f"{item['requires_human_review']}"
    )

    if item["competing_refs"]:

        print(
            f"  Competing transactions: "
            f"{item['competing_refs']}"
        )

    print(
        f"  Reason: {item['reason']}"
    )


print("\n" + "=" * 70)
print("UNMATCHED")
print("=" * 70)

print(
    f"\nLedger ({len(unmatched_ledger)}):"
)

print(unmatched_ledger)

print(
    f"\nBank ({len(unmatched_bank)}):"
)

print(unmatched_bank)


# ============================================================
# SAVE OUTPUTS
# ============================================================

pd.DataFrame(matched).to_csv(
    "output/matched.csv",
    index=False
)

pd.DataFrame(exceptions).to_csv(
    "output/exceptions.csv",
    index=False
)

pd.DataFrame({
    "Invoice ID": unmatched_ledger
}).to_csv(
    "output/unmatched_ledger.csv",
    index=False
)

pd.DataFrame({
    "Ref No": unmatched_bank
}).to_csv(
    "output/unmatched_bank.csv",
    index=False
)

print("\nOutput files saved.")