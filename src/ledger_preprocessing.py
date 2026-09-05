import pandas as pd
from utils.money import parse_amount
from utils.normalization import normalize_columns

def prepare_ledger(ledger_df):
    """
    Normalize internal ledger data.

    The matching date should represent the expected/settlement date
    when such a field exists. invoice_date is used only as a fallback.
    No UTR/reference is manufactured for ledger rows.
    """
    df = normalize_columns(ledger_df)

    if "settlement_date" in df.columns:
        df["ledger_date"] = pd.to_datetime(
            df["settlement_date"], format="%Y-%m-%d", errors="coerce"
        )
    elif "expected_settlement_date" in df.columns:
        df["ledger_date"] = pd.to_datetime(
            df["expected_settlement_date"], format="%Y-%m-%d", errors="coerce"
        )
    elif "invoice_date" in df.columns:
        df["ledger_date"] = pd.to_datetime(
            df["invoice_date"], format="%Y-%m-%d", errors="coerce"
        )
    elif "date" in df.columns:
        df["ledger_date"] = pd.to_datetime(
            df["date"], format="%Y-%m-%d", errors="coerce"
        )
    else:
        df["ledger_date"] = pd.NaT

    if "invoice_amount" in df.columns:
        df["ledger_amount"] = df["invoice_amount"].apply(parse_amount)
    elif "amount" in df.columns:
        df["ledger_amount"] = df["amount"].apply(parse_amount)
    elif "net_amount" in df.columns:
        df["ledger_amount"] = df["net_amount"].apply(parse_amount)
    else:
        df["ledger_amount"] = None

    if "customer_name" not in df.columns:
        df["customer_name"] = ""

    if "invoice_id" not in df.columns:
        df["invoice_id"] = ""

    if "ledger_id" not in df.columns:
        df["ledger_id"] = df["invoice_id"]

    if "payment_method" in df.columns:
        df["payment_method"] = (
            df["payment_method"].fillna("").astype(str).str.lower().str.strip()
        )
    elif "payment_type" in df.columns:
        df["payment_method"] = (
            df["payment_type"].fillna("").astype(str).str.lower().str.strip()
        )
    else:
        df["payment_method"] = ""

    return df
