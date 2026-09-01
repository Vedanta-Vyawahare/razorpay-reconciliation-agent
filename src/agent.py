import pandas as pd

# ---------- Load data ----------
ledger = pd.read_csv("data/internal_ledger.csv")
bank = pd.read_csv("data/bank_statement.csv")


# ---------- Parse the messy Details field ----------
def parse_details(details, ref_no):
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
    else:
        return {"type": "UNKNOWN", "name": None}

bank["parsed"] = bank.apply(lambda row: parse_details(row["Details"], row["Ref No"]), axis=1)
bank["sender_name"] = bank["parsed"].apply(lambda x: x["name"])
bank["txn_type"] = bank["parsed"].apply(lambda x: x["type"])


def compute_gap(ledger_row, bank_row):
    gap = round(ledger_row["Total Amount"] - bank_row["Credit"], 2)
    gap_pct = round(abs(gap) / ledger_row["Total Amount"] * 100, 2)
    return gap, gap_pct


def find_candidates(ledger_row, bank_df, claimed_refs):
    first_name = ledger_row["Customer Name"].split()[0]
    pool = bank_df[~bank_df["Ref No"].isin(claimed_refs)]
    return pool[pool["sender_name"].str.contains(first_name, case=False, na=False)]


# ---------- Build every possible (invoice, bank_row) pair with its gap, sorted best-first ----------
def build_all_pairs(ledger, bank):
    pairs = []
    for _, inv in ledger.iterrows():
        candidates = find_candidates(inv, bank, claimed_refs=set())
        for _, cand in candidates.iterrows():
            gap, gap_pct = compute_gap(inv, cand)
            pairs.append({
                "invoice_id": inv["Invoice ID"], "bank_ref": cand["Ref No"],
                "ledger_amount": inv["Total Amount"], "bank_amount": cand["Credit"],
                "gap": gap, "gap_pct": gap_pct
            })
    return sorted(pairs, key=lambda p: p["gap_pct"])


def bucket_sort(ledger, bank):
    matched, exceptions = [], []
    claimed_invoices, claimed_bank_refs = set(), set()

    all_pairs = build_all_pairs(ledger, bank)

    for pair in all_pairs:
        if pair["invoice_id"] in claimed_invoices or pair["bank_ref"] in claimed_bank_refs:
            continue

        # check for a near-tied competing candidate for this same invoice
        rivals = [p for p in all_pairs
                  if p["invoice_id"] == pair["invoice_id"]
                  and p["bank_ref"] != pair["bank_ref"]
                  and p["bank_ref"] not in claimed_bank_refs]
        is_ambiguous = any(abs(r["gap_pct"] - pair["gap_pct"]) < 1.0 for r in rivals)

        claimed_invoices.add(pair["invoice_id"])
        claimed_bank_refs.add(pair["bank_ref"])

        if is_ambiguous:
            pair["reason"] = "multiple equally plausible bank matches - needs human review"
            exceptions.append(pair)
        elif abs(pair["gap"]) < 0.01:
            matched.append(pair)
        else:
            pair["reason"] = "gap found - needs LLM reasoning (Day 2)"
            exceptions.append(pair)

    matched_invoice_ids = {p["invoice_id"] for p in matched + exceptions}
    unmatched_ledger = [i for i in ledger["Invoice ID"] if i not in matched_invoice_ids]
    unmatched_bank = [r for r in bank["Ref No"] if r not in claimed_bank_refs]

    return matched, exceptions, unmatched_ledger, unmatched_bank


matched, exceptions, unmatched_ledger, unmatched_bank = bucket_sort(ledger, bank)

print(f"Matched: {len(matched)}")
for m in matched:
    print(f"  {m}")
print(f"\nExceptions: {len(exceptions)}")
for e in exceptions:
    print(f"  {e}")
print(f"\nUnmatched ledger: {unmatched_ledger}")
print(f"Unmatched bank: {unmatched_bank}")