"""Readers for the raw Meesho exports.

Real-world Meesho downloads vary: header rows sit at different depths, column
spellings changed between file generations, and one workbook carries several
sections (orders / ads / referral). Everything here is defensive by design --
files are located by content, not by filename.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import pandas as pd

from .config import (CLAIM_FIELDS, COST_FIELDS, ORDER_FIELDS, PAYMENT_FIELDS,
                     RETURN_FIELDS)

warnings.simplefilter("ignore", UserWarning)          # openpyxl style noise on Meesho files

_PUNCT = re.compile(r"[^a-z0-9]+")


def normalise_header(name) -> str:
    """'Total Sale Amount (Incl. Commission & GST)' -> 'total sale amount incl commission gst'"""
    return _PUNCT.sub(" ", str(name).lower()).strip()


def resolve_columns(df: pd.DataFrame, spec: dict) -> dict:
    """Map canonical field name -> actual column label present in df.

    Exact matches are claimed first, across every field, before any fuzzy matching
    runs. That ordering matters: 'Order Number' and 'Suborder Number' both live in
    the returns export, and a loose substring pass would bind the sub-order field
    to the parent order and silently join on the wrong key.
    """
    lookup: dict[str, str] = {}
    for col in df.columns:
        lookup.setdefault(normalise_header(col), col)

    resolved: dict[str, str] = {}
    claimed: set[str] = set()

    for field, candidates in spec.items():                       # pass 1: exact
        for cand in candidates:
            if cand in lookup and lookup[cand] not in claimed:
                resolved[field] = lookup[cand]
                claimed.add(lookup[cand])
                break

    for field, candidates in spec.items():                       # pass 2: fuzzy
        if field in resolved:
            continue
        best, best_len = None, 0
        for cand in candidates:
            if len(cand) < 5:
                continue
            for norm, col in lookup.items():
                if col in claimed or cand not in norm:
                    continue
                if len(cand) > best_len:                          # longest phrase wins
                    best, best_len = col, len(cand)
        if best is not None:
            resolved[field] = best
            claimed.add(best)
    return resolved


def _read_any(path: Path, sheet=0, header=0) -> pd.DataFrame:
    """Read a sheet or CSV. `header` is the 0-based row index of the header line.

    Meesho panel CSVs carry a multi-line banner (supplier name, download stamp,
    a blank line) before the real header, so honouring `header` matters here --
    passing it straight through to read_csv as `skiprows` is what makes the
    banner-prefixed exports load at all.
    """
    if path.suffix.lower() in (".csv", ".txt"):
        return pd.read_csv(path, dtype=str, keep_default_na=False,
                           skiprows=header if header else None,
                           header=None if header is None else 0,
                           engine="python", on_bad_lines="skip")
    engine = "pyxlsb" if path.suffix.lower() == ".xlsb" else None
    return pd.read_excel(path, sheet_name=sheet, header=header, dtype=object, engine=engine)


def _find_header_row(path: Path, sheet, spec: dict, max_scan: int = 14):
    """Meesho files carry title/banner rows. Score the first rows for field hits."""
    try:
        if path.suffix.lower() in (".csv", ".txt"):
            # Read rows with the csv module: the panel banner is 2 columns wide while
            # the real header is 20+, and pandas would treat the wider row as broken.
            import csv as _csv
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                rows = [r for _, r in zip(range(max_scan), _csv.reader(fh))]
            probe = pd.DataFrame(rows)
        else:
            probe = _read_any(path, sheet=sheet, header=None).head(max_scan)
    except Exception:
        return 0, 0
    wanted = {c for cands in spec.values() for c in cands}
    best, best_hits = 0, 0
    for i in range(len(probe)):
        cells = {normalise_header(v) for v in probe.iloc[i].tolist()}
        hits = len(cells & wanted)
        if hits > best_hits:
            best, best_hits = i, hits
    return best, best_hits


def load_table(path: Path, spec: dict, sheet=0) -> pd.DataFrame | None:
    """Load one sheet, auto-detecting its header row; returns canonical-named columns."""
    header, hits = _find_header_row(path, sheet, spec)
    if hits < 2:
        return None
    df = _read_any(path, sheet=sheet, header=header)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    cols = resolve_columns(df, spec)
    if "sub_order_no" not in cols and "sku" not in cols:
        return None
    out = df.rename(columns={v: k for k, v in cols.items()})
    out = out[[c for c in cols if c in out.columns]].copy()
    out["_source_file"] = path.name
    out["_source_sheet"] = str(sheet)
    return out


def _sheets_of(path: Path):
    if path.suffix.lower() in (".csv", ".txt"):
        return [0]
    engine = "pyxlsb" if path.suffix.lower() == ".xlsb" else None
    return pd.ExcelFile(path, engine=engine).sheet_names


def load_payments(paths) -> pd.DataFrame:
    """Order-payment rows from every payment workbook, all sheets, concatenated."""
    frames = []
    for p in map(Path, paths):
        for sheet in _sheets_of(p):
            t = load_table(p, PAYMENT_FIELDS, sheet)
            if t is not None and "settlement" in t.columns:
                t["_section"] = str(sheet)
                frames.append(t)
    if not frames:
        raise ValueError("No order-payment rows found in the supplied payment files.")
    df = pd.concat(frames, ignore_index=True, sort=False)
    # A sub-order can legitimately repeat (multiple settlement transactions);
    # only exact duplicates of the same line in the same file are noise.
    return df.drop_duplicates(
        subset=[c for c in ("sub_order_no", "transaction_id", "settlement",
                            "sale_amount", "_source_file") if c in df.columns],
        keep="first",
    ).reset_index(drop=True)


ADS_AMOUNT_HINTS = ("total ads cost", "ads cost", "amount", "spend", "total amount",
                    "ad spend", "deduction", "referral amount", "total")
ADS_GST_HINTS = ("gst", "tax", "cgst", "sgst", "igst")
ADS_DATE_HINTS = ("date", "payment date", "deduction date", "period")


def load_ads(paths, fee_gst_rate: float = 0.18) -> pd.DataFrame:
    """Ads / referral sections of the payment workbooks.

    These are NOT settlement rows: in the vendor's output the ads lines carry a
    zero settlement and the spend sits in its own column, with the GST component
    booked as input credit. Amount is stored negative (a deduction).
    """
    frames = []
    for p in map(Path, paths):
        for sheet in _sheets_of(p):
            label = str(sheet).lower()
            if not any(k in label for k in ("ad", "referral", "marketing")):
                continue
            header, _ = _find_header_row(
                p, sheet, {"amount": list(ADS_AMOUNT_HINTS), "gst": list(ADS_GST_HINTS),
                           "date": list(ADS_DATE_HINTS),
                           "extra": ["campaign id", "ad cost", "reward id", "store name",
                                     "credits waivers discounts", "deduction duration"]})
            try:
                df = _read_any(p, sheet=sheet, header=header)
            except Exception:
                continue
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if df.empty:
                continue

            norm = {normalise_header(c): c for c in df.columns}
            amt_col = next((norm[n] for h in ADS_AMOUNT_HINTS for n in norm if h in n), None)
            if amt_col is None:                       # fall back to the widest numeric column
                nums = [c for c in df.columns
                        if pd.to_numeric(df[c], errors="coerce").notna().sum() > len(df) * 0.5]
                if not nums:
                    continue
                amt_col = max(nums, key=lambda c: pd.to_numeric(df[c], errors="coerce").abs().sum())
            gst_col = next((norm[n] for h in ADS_GST_HINTS for n in norm
                            if h in n and norm[n] != amt_col), None)
            date_col = next((norm[n] for h in ADS_DATE_HINTS for n in norm if h in n), None)

            amount = pd.to_numeric(df[amt_col], errors="coerce")
            keep = amount.notna() & (amount != 0)
            if not keep.any():
                continue
            amount = -amount[keep].abs()              # always a deduction
            gst = (-pd.to_numeric(df.loc[keep, gst_col], errors="coerce").abs()
                   if gst_col else amount * fee_gst_rate / (1 + fee_gst_rate))

            frames.append(pd.DataFrame({
                "total_ads_cost": amount.to_numpy(),
                "gst_ads": gst.fillna(0.0).to_numpy(),
                "payment_date": (pd.to_datetime(df.loc[keep, date_col], errors="coerce",
                                                dayfirst=True).to_numpy()
                                 if date_col else pd.NaT),
                "supplier_sku": "Referral Payments" if "referral" in label else "Ads Cost",
                "sub_order_no": "",
                "_section": str(sheet),
                "_source_file": p.name,
            }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_orders(paths) -> pd.DataFrame:
    frames = []
    for p in map(Path, paths):
        for sheet in _sheets_of(p):
            t = load_table(p, ORDER_FIELDS, sheet)
            if t is not None and "sub_order_no" in t.columns:
                frames.append(t)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    return df.drop_duplicates(
        subset=[c for c in ("sub_order_no", "order_status", "_source_file") if c in df.columns]
    ).reset_index(drop=True)


# The panel splits the return journey across separate exports. Which export a
# sub-order lands in IS the outcome, and that outcome decides whether the seller
# got the stock back -- the fact the payment file never carries.
RETURN_OUTCOME_BY_FILE = (
    ("completed_delivered", "recovered"),    # came back to the seller
    ("completed_lost", "lost"),              # never came back
    ("intransit", "in_transit"),
    ("ofd_reverse", "in_transit"),
)


def _return_outcome(filename: str) -> str:
    low = filename.lower()
    for token, outcome in RETURN_OUTCOME_BY_FILE:
        if token in low:
            return outcome
    return "unknown"


def load_returns(paths) -> pd.DataFrame:
    frames = []
    for p in map(Path, paths):
        for sheet in _sheets_of(p):
            t = load_table(p, RETURN_FIELDS, sheet)
            if t is not None and "sub_order_no" in t.columns:
                t["return_outcome"] = _return_outcome(p.name)
                frames.append(t)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    df["sub_order_no"] = df["sub_order_no"].astype(str).str.strip()
    # a settled outcome beats an in-flight one when a sub-order appears in both
    rank = {"recovered": 0, "lost": 0, "in_transit": 1, "unknown": 2}
    df["_rank"] = df["return_outcome"].map(rank).fillna(3)
    df = (df.sort_values("_rank", kind="stable")
            .drop_duplicates(subset=["sub_order_no"], keep="first")
            .drop(columns="_rank"))
    return df.reset_index(drop=True)


CLAIM_STATUS_MAP = {"approved": "Approved", "open": "Open", "rejected": "Rejected",
                    "closed": "Rejected", "resolved": "Approved"}


def load_claims(paths) -> pd.DataFrame:
    """Support/claim tickets -> the Claim Status the vendor reports per sub-order."""
    frames = []
    for p in map(Path, paths):
        for sheet in _sheets_of(p):
            t = load_table(p, CLAIM_FIELDS, sheet)
            if t is not None and "claim_status" in t.columns:
                frames.append(t)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    df["sub_order_no"] = df["sub_order_no"].astype(str).str.strip()
    df["claim_status"] = (df["claim_status"].astype(str).str.strip().str.casefold()
                            .map(CLAIM_STATUS_MAP).fillna("NA"))
    # an approved ticket outranks an open one for the same sub-order
    order = {"Approved": 0, "Open": 1, "Rejected": 2, "NA": 3}
    df["_r"] = df["claim_status"].map(order).fillna(4)
    return (df.sort_values("_r", kind="stable")
              .drop_duplicates("sub_order_no", keep="first")
              .drop(columns="_r").reset_index(drop=True))


def load_costs(paths) -> pd.DataFrame:
    """SKU cost master -> one row per SKU with a unit cost."""
    frames = []
    for p in map(Path, paths):
        for sheet in _sheets_of(p):
            t = load_table(p, COST_FIELDS, sheet)
            if t is not None and "sku" in t.columns:
                frames.append(t)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    for c in ("product_cost", "packaging_cost", "gst_pct"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0
    df["unit_cost"] = df["product_cost"] + df["packaging_cost"]
    df["sku_key"] = df["sku"].map(clean_sku)
    # last definition wins (cost masters are appended over time)
    return df.drop_duplicates(subset=["sku_key"], keep="last").reset_index(drop=True)


def clean_sku(sku) -> str:
    """Vendor's SubstituteSKU convention: trim, collapse spaces, '-' -> '_', casefold."""
    s = str(sku).strip()
    s = re.sub(r"\s+", " ", s)
    return s.replace("-", "_").casefold()
