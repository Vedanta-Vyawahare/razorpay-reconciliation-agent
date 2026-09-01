import pandas as pd

# ---------- Load data ----------

ledger = pd.read_csv("data/internal_ledger.csv")
bank = pd.read_csv("data/bank_statement.csv")


# ---------- Parse messy Details field ----------

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
bank["sender_name"] = bank["parsed"].apply(lambda x: x["name"])
bank["txn_type"] = bank["parsed"].apply(lambda x: x["type"])


# ---------- Normalize names ----------

def normalize_name(name):
    if pd.isna(name):
        return ""

    name = str(name).upper()

    for word in [
        " PRIVATE LIMITED",
        " PVT LTD",
        " LIMITED",
        " LTD",
        " LLP"
    ]:
        name = name.replace(word, "")

    return " ".join(name.split())


ledger["normalized_name"] = (
    ledger["Customer Name"]
    .apply(normalize_name)
)

bank["normalized_name"] = (
    bank["sender_name"]
    .apply(normalize_name)
)


# ---------- Date preparation ----------

ledger["Invoice Date"] = pd.to_datetime(
    ledger["Invoice Date"],
    errors="coerce"
)

bank["Value Date"] = pd.to_datetime(
    bank["Value Date"],
    dayfirst=True,
    errors="coerce"
)


# ---------- Calculate candidate quality ----------

def score_candidate(ledger_row, bank_row):

    ledger_amount = float(ledger_row["Total Amount"])
    bank_amount = float(bank_row["Credit"])

    gap = round(
        ledger_amount - bank_amount,
        2
    )

    gap_pct = (
        abs(gap) / ledger_amount * 100
        if ledger_amount != 0
        else 100
    )

    # ---------- Name ----------

    ledger_name = ledger_row["normalized_name"]
    bank_name = bank_row["normalized_name"]

    name_match = (
        ledger_name == bank_name
        or ledger_name in bank_name
        or bank_name in ledger_name
    )

    # ---------- Date ----------

    if pd.isna(ledger_row["Invoice Date"]) or pd.isna(
        bank_row["Value Date"]
    ):
        date_gap = 999
    else:
        date_gap = abs(
            (
                bank_row["Value Date"]
                - ledger_row["Invoice Date"]
            ).days
        )

    # ---------- Score ----------

    score = 0

    # Amount is strongest signal
    if gap_pct <= 0.01:
        score += 70
    elif gap_pct <= 1:
        score += 55
    elif gap_pct <= 5:
        score += 35
    elif gap_pct <= 10:
        score += 15

    # Customer identity
    if name_match:
        score += 20

    # Date proximity
    if date_gap == 0:
        score += 10
    elif date_gap <= 1:
        score += 8
    elif date_gap <= 3:
        score += 5

    return {
        "gap": gap,
        "gap_pct": round(gap_pct, 2),
        "date_gap": date_gap,
        "name_match": name_match,
        "score": score
    }


# ---------- Find candidates ----------

def find_candidates(
    ledger_row,
    bank_df,
    claimed_refs
):

    candidates = []

    for _, bank_row in bank_df.iterrows():

        ref = bank_row["Ref No"]

        # Already used by a confirmed match
        if ref in claimed_refs:
            continue

        result = score_candidate(
            ledger_row,
            bank_row
        )

        # We only consider same/related customers
        if not result["name_match"]:
            continue

        # Ignore very distant transactions
        if result["date_gap"] > 3:
            continue

        # Ignore completely different amounts
        if result["gap_pct"] > 20:
            continue

        candidates.append({
            "invoice_id": ledger_row["Invoice ID"],
            "bank_ref": ref,
            "ledger_amount": float(
                ledger_row["Total Amount"]
            ),
            "bank_amount": float(
                bank_row["Credit"]
            ),
            "gap": result["gap"],
            "gap_pct": result["gap_pct"],
            "date_gap": result["date_gap"],
            "score": result["score"]
        })

    return sorted(
        candidates,
        key=lambda x: (
            -x["score"],
            x["gap_pct"],
            x["date_gap"]
        )
    )


# ============================================================
# RECONCILIATION
# ============================================================

def bucket_sort(ledger, bank):

    matched = []
    exceptions = []

    claimed_invoices = set()
    claimed_bank_refs = set()

    for _, invoice in ledger.iterrows():

        invoice_id = invoice["Invoice ID"]

        if invoice_id in claimed_invoices:
            continue

        candidates = find_candidates(
            invoice,
            bank,
            claimed_bank_refs
        )

        # ----------------------------------------------------
        # No candidate
        # ----------------------------------------------------

        if not candidates:
            continue

        best = candidates[0]

        # ----------------------------------------------------
        # Check for competing candidates
        #
        # IMPORTANT:
        # Do this BEFORE claiming anything.
        # ----------------------------------------------------

        rivals = [
            c for c in candidates[1:]
            if (
                c["bank_ref"] not in claimed_bank_refs
                and abs(
                    c["score"] - best["score"]
                ) <= 5
            )
        ]

        # ----------------------------------------------------
        # Ambiguous
        # ----------------------------------------------------

        if rivals:

            best["decision"] = "AMBIGUOUS"

            best["reason"] = (
                "Multiple bank transactions have similar "
                "evidence. The system cannot safely determine "
                "which transaction belongs to this invoice."
            )

            best["confidence"] = 50

            best["competing_refs"] = [
                r["bank_ref"]
                for r in rivals
            ]

            exceptions.append(best)

            # IMPORTANT:
            # Do NOT claim the invoice.
            # Do NOT claim the bank transaction.
            #
            # They remain unresolved.

            continue

        # ----------------------------------------------------
        # Exact match
        # ----------------------------------------------------

        if best["gap_pct"] <= 0.01:

            best["decision"] = "MATCHED"

            best["reason"] = (
                "A single bank transaction matches the "
                "invoice amount with strong supporting evidence."
            )

            best["confidence"] = min(
                99,
                best["score"]
            )

            matched.append(best)

            claimed_invoices.add(
                invoice_id
            )

            claimed_bank_refs.add(
                best["bank_ref"]
            )

        # ----------------------------------------------------
        # Near match / exception
        # ----------------------------------------------------

        else:

            best["decision"] = "EXCEPTION"

            best["reason"] = (
                "A plausible bank transaction was found, "
                "but the settled amount differs from the "
                "ledger amount. Further reasoning is required."
            )

            best["confidence"] = best["score"]

            exceptions.append(best)

            # We can claim this only because we have
            # selected a unique candidate.
            claimed_invoices.add(
                invoice_id
            )

            claimed_bank_refs.add(
                best["bank_ref"]
            )

    # --------------------------------------------------------
    # Unmatched records
    # --------------------------------------------------------

    matched_or_exception_invoices = {
        x["invoice_id"]
        for x in matched + exceptions
    }

    unmatched_ledger = [
        invoice_id
        for invoice_id in ledger["Invoice ID"]
        if invoice_id not in matched_or_exception_invoices
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
    bucket_sort(
        ledger,
        bank
    )
)


# ============================================================
# PRINT RESULTS
# ============================================================

print("=" * 60)
print("RECONCILIATION RESULTS")
print("=" * 60)


print(f"\nMatched: {len(matched)}")

for item in matched:
    print(
        f"\n{item['invoice_id']}"
        f" -> {item['bank_ref']}"
        f" | Gap: ₹{item['gap']}"
        f" | Confidence: {item['confidence']}%"
    )


print(f"\nExceptions: {len(exceptions)}")

for item in exceptions:
    print(
        f"\n{item['invoice_id']}"
        f" -> {item['bank_ref']}"
        f" | {item['decision']}"
        f" | Gap: ₹{item['gap']}"
        f" | Confidence: {item['confidence']}%"
    )

    print(
        f"  Reason: {item['reason']}"
    )

    if "competing_refs" in item:
        print(
            f"  Competing transactions: "
            f"{item['competing_refs']}"
        )


print(
    f"\nUnmatched ledger: "
    f"{unmatched_ledger}"
)

print(
    f"Unmatched bank: "
    f"{unmatched_bank}"
)


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