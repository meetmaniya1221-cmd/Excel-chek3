"""Regression harness against the numbers recovered from the vendor workbook."""
from __future__ import annotations

import pandas as pd

# Grand totals read out of 01 M Meldi Krupa 1260895 Meesho Analysos 0.4.5_1.xlsb
# (orders 11-Dec-2024 -> 26-Jul-2025). A clone fed the same raw files must reproduce these.
GOLDEN_SAMPLE = {
    "rows": 43490,
    "orders": 40994,
    "delivered": 25221,
    "rto": 13492,
    "customer_return": 2281,
    "exchange": 202,
    "cancelled": 135,
    "net_sales": 7336672.0,
    "settlement": 5225069.90,
    "purchase": 3911672.0,
    "gross_pl": 1313397.90,
    "ads": -168111.28,
    "referral": 0.0,
    "tcs": -31083.93,
    "tds": -6201.77,
    "claims": 184651.40,
    "recovery": -31887.68,
    "compensation": 4053.43,
    "gst_credits": 365986.53,
    "sales_gst_debit": -1096511.19,
    "avail_gst": -730524.66,
    "return_charges": -373187.36,
    "shipping_diff": 333518.0,
    "final_pl": 1150680.62,
    "final_pl_with_gst": 420155.96,
}


def compare(actual: dict, expected: dict = None, tol: float = 0.02) -> pd.DataFrame:
    """Side-by-side of computed vs expected totals with a pass/fail verdict."""
    expected = expected or GOLDEN_SAMPLE
    rows = []
    for key in expected:
        exp, act = expected[key], actual.get(key)
        if act is None:
            rows.append({"metric": key, "expected": exp, "actual": None,
                         "diff": None, "diff_pct": None, "verdict": "MISSING"})
            continue
        diff = act - exp
        pct = (diff / exp * 100) if exp else (0.0 if abs(diff) < tol else float("inf"))
        verdict = "OK" if abs(diff) <= max(tol, abs(exp) * 0.0001) else \
                  "CLOSE" if abs(pct) < 1 else "MISMATCH"
        rows.append({"metric": key, "expected": exp, "actual": act,
                     "diff": diff, "diff_pct": pct, "verdict": verdict})
    # anything the engine produced that the golden set does not cover
    for key in actual:
        if key not in expected:
            rows.append({"metric": key, "expected": None, "actual": actual[key],
                         "diff": None, "diff_pct": None, "verdict": "EXTRA"})
    return pd.DataFrame(rows)


def summarise(report: pd.DataFrame) -> str:
    counts = report["verdict"].value_counts().to_dict()
    parts = [f"{v}={counts[v]}" for v in ("OK", "CLOSE", "MISMATCH", "MISSING", "EXTRA")
             if v in counts]
    return " · ".join(parts)
