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
        card_tier = parts[1] if len(parts) > 1 else None  # e.g. DR-STD, DR-PREM, DR-DEBIT
        return {"type": "CARD", "name": name, "card_tier": card_tier}
    else:
        return {"type": "UNKNOWN", "name": None}

bank["parsed"] = bank.apply(lambda row: parse_details(row["Details"], row["Ref No"]), axis=1)
bank["sender_name"] = bank["parsed"].apply(lambda x: x["name"])
bank["txn_type"] = bank["parsed"].apply(lambda x: x["type"])


# ---------- Compute gap between an invoice and a candidate bank row ----------
def compute_gap(ledger_row, bank_row):
    gap = round(ledger_row["Total Amount"] - bank_row["Credit"], 2)
    gap_pct = round(abs(gap) / ledger_row["Total Amount"] * 100, 2)
    return gap, gap_pct


# ---------- Find bank rows whose sender name matches this invoice's customer ----------
def find_candidates(ledger_row, bank_df):
    first_name = ledger_row["Customer Name"].split()[0]
    return bank_df[bank_df["sender_name"].str.contains(first_name, case=False, na=False)]


# ---------- Sort every invoice into matched / exceptions / unmatched ----------
def bucket_sort(ledger, bank):
    matched, exceptions, unmatched_ledger = [], [], []
    matched_bank_refs = set()

    for _, inv in ledger.iterrows():
        candidates = find_candidates(inv, bank)
        if candidates.empty:
            unmatched_ledger.append(inv["Invoice ID"])
            continue

        best_row, best_gap_pct = None, None
        for _, cand in candidates.iterrows():
            gap, gap_pct = compute_gap(inv, cand)
            if best_gap_pct is None or gap_pct < best_gap_pct:
                best_row, best_gap_pct = cand, gap_pct

        gap, gap_pct = compute_gap(inv, best_row)
        record = {
            "invoice_id": inv["Invoice ID"],
            "bank_ref": best_row["Ref No"],
            "ledger_amount": inv["Total Amount"],
            "bank_amount": best_row["Credit"],
            "gap": gap,
            "gap_pct": gap_pct,
        }
        matched_bank_refs.add(best_row["Ref No"])

        if abs(gap) < 0.01:
            matched.append(record)
        else:
            exceptions.append(record)  # gap exists - needs LLM reasoning (Day 2)

    unmatched_bank = bank[~bank["Ref No"].isin(matched_bank_refs)]["Ref No"].tolist()
    return matched, exceptions, unmatched_ledger, unmatched_bank


# ---------- Run it ----------
matched, exceptions, unmatched_ledger, unmatched_bank = bucket_sort(ledger, bank)

print(f"Matched: {len(matched)}")
for m in matched:
    print(f"  {m}")

print(f"\nExceptions (gap found, needs reasoning): {len(exceptions)}")
for e in exceptions:
    print(f"  {e}")

print(f"\nUnmatched ledger rows: {unmatched_ledger}")
print(f"Unmatched bank rows: {unmatched_bank}")