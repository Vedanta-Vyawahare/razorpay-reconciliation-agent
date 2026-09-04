import pandas as pd
import re


def load_csv(path):
    return pd.read_csv(path)


def normalize_columns(df):
    df = df.copy()

    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    return df


def parse_amount(value):
    if pd.isna(value):
        return None

    value = (
        str(value)
        .replace("₹", "")
        .replace(",", "")
        .strip()
    )

    try:
        return round(float(value), 2)
    except ValueError:
        return None


def parse_date(series):
    """
    Handles ISO dates such as 2026-06-18
    without forcing dayfirst=True.
    """
    return pd.to_datetime(
        series,
        errors="coerce"
    )


def extract_transaction_type(details):
    if pd.isna(details):
        return "UNKNOWN"

    text = str(details).upper()

    if "NEFT" in text:
        return "NEFT"

    if "IMPS" in text:
        return "IMPS"

    if "RTGS" in text:
        return "RTGS"

    if "UPI" in text:
        return "UPI"

    if "TRANSFER" in text:
        return "TRANSFER"

    return "UNKNOWN"


def prepare_settlements(df):
    df = normalize_columns(df)

    if "net_settlement" in df.columns:
        df["net_amount"] = df["net_settlement"].apply(
            parse_amount
        )
    elif "net_amount" in df.columns:
        df["net_amount"] = df["net_amount"].apply(
            parse_amount
        )
    elif "amount" in df.columns:
        df["net_amount"] = df["amount"].apply(
            parse_amount
        )
    else:
        raise ValueError(
            "Settlement file needs net_settlement, "
            "net_amount, or amount."
        )

    if "settlement_date" in df.columns:
        df["settlement_date"] = parse_date(
            df["settlement_date"]
        )
    elif "date" in df.columns:
        df["settlement_date"] = parse_date(
            df["date"]
        )
    else:
        raise ValueError(
            "Settlement file needs settlement_date."
        )

    return df


def prepare_bank_statement(df):
    df = normalize_columns(df)

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    if "value_date" in df.columns:
        df["bank_date"] = parse_date(
            df["value_date"]
        )
    elif "post_date" in df.columns:
        df["bank_date"] = parse_date(
            df["post_date"]
        )
    elif "date" in df.columns:
        df["bank_date"] = parse_date(
            df["date"]
        )
    else:
        raise ValueError(
            "Bank statement needs value_date, "
            "post_date, or date."
        )

    # --------------------------------------------------------
    # CREDIT
    # --------------------------------------------------------

    if "credit" in df.columns:
        df["bank_amount"] = df["credit"].apply(
            parse_amount
        )
    elif "amount" in df.columns:
        df["bank_amount"] = df["amount"].apply(
            parse_amount
        )
    else:
        raise ValueError(
            "Bank statement needs credit or amount."
        )

    # --------------------------------------------------------
    # DEBIT
    # --------------------------------------------------------

    if "debit" in df.columns:
        df["bank_debit"] = df["debit"].apply(
            parse_amount
        ).fillna(0)
    else:
        df["bank_debit"] = 0.0

    # --------------------------------------------------------
    # NARRATION
    # --------------------------------------------------------

    if "details" in df.columns:
        df["narration"] = (
            df["details"]
            .fillna("")
            .astype(str)
        )

    elif "narration" in df.columns:
        df["narration"] = (
            df["narration"]
            .fillna("")
            .astype(str)
        )

    else:
        df["narration"] = ""

    # --------------------------------------------------------
    # BANK REFERENCE
    # --------------------------------------------------------

    if "ref_no_cheque_no" in df.columns:
        df["bank_reference"] = (
            df["ref_no_cheque_no"]
            .fillna("")
            .astype(str)
        )

    elif "ref_no" in df.columns:
        df["bank_reference"] = (
            df["ref_no"]
            .fillna("")
            .astype(str)
        )

    elif "reference" in df.columns:
        df["bank_reference"] = (
            df["reference"]
            .fillna("")
            .astype(str)
        )

    else:
        df["bank_reference"] = ""

    # --------------------------------------------------------
    # TRANSACTION TYPE
    # --------------------------------------------------------

    df["transaction_type"] = (
        df["narration"]
        .apply(extract_transaction_type)
    )

    # --------------------------------------------------------
    # CREDIT FLAG
    # --------------------------------------------------------

    df["is_credit"] = (
        df["bank_amount"].fillna(0) > 0
    )

    return df

def preprocess_bank(bank):
    bank = bank.copy()

    bank["bank_date"] = pd.to_datetime(
        bank["post_date"],
        errors="coerce"
    )

    bank["value_date"] = pd.to_datetime(
        bank["value_date"],
        errors="coerce"
    )

    bank["bank_amount"] = pd.to_numeric(
        bank["credit"],
        errors="coerce"
    ).fillna(0.0)

    bank["bank_reference"] = (
        bank["ref_no_cheque_no"]
        .astype(str)
        .str.strip()
    )

    bank["narration"] = (
        bank["details"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    bank["is_credit"] = bank["credit"].fillna(0) > 0

    bank["transaction_type"] = (
        bank["details"]
        .fillna("")
        .astype(str)
        .str.upper()
        .apply(extract_transaction_type)
    )

    return bank

def extract_transaction_type(details):
    text = str(details).upper()

    if "/NEFT/" in text:
        return "NEFT"

    if "/IMPS/" in text:
        return "IMPS"

    if "/RTGS/" in text:
        return "RTGS"

    if "/UPI/" in text:
        return "UPI"

    if "TRANSFER" in text:
        return "TRANSFER"

    return "UNKNOWN"