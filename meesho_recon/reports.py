"""Report builders: the SKU grid, the State grid, and the two money-recovery exports."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import STATUS_DELIVERED, STATUS_SHIPPED

# report column -> (source column, aggregation) in the vendor's display order
MEASURES = [
    ("Net Sales",              "total_sales"),
    ("Settlement",             "settlement"),
    ("Recovery Amt",           "recovery"),
    ("Claims Amt",             "claims"),
    ("Compensation Amt",       "compensation"),
    ("Gross Profit or Loss",   "pl"),
    ("Purchase",               "purchase"),
    ("Total Order",            "total_order"),
    ("Delivered",              "delivered"),
    ("RTO",                    "rto"),
    ("Customer Return",        "customer_return"),
    ("Exchange",               "exchange"),
    ("Cancelled",              "cancelled"),
    ("Recovery Qty",           "recovery_qty"),
    ("TCS",                    "tcs"),
    ("TDS",                    "tds"),
    ("Claim Qty",              "claim_qty"),
    ("Profit/Loss With Gst",   "profit_loss_with_gst"),
    ("Ads Cost",               "total_ads_cost"),
    ("Referral Amount",        "net_referral_amount"),
    ("Meesho GST Credits",     "meesho_gst_credits"),
    ("Purchase Gst Credit",    "purchase_gst_credit"),
    ("Sales Gst Debit",        "sales_gst_debit"),
    ("Available GST Credit",   "available_gst_credit"),
    ("Shipping Charge (Excl.GST)", "shipping_charge"),
    ("Return Charges",         "final_return_charges"),
    ("Return Loss",            "return_loss_pct"),
    ("RTO Packaging Loss",     "rto_packaging_loss"),
    ("Shipping Diff",          "shipping_diff"),
]


def _derived(g: pd.DataFrame) -> pd.DataFrame:
    """The six pivot calculated fields plus the sheet-formula ratios."""
    delivered_orders = g["Total Order"] - g["RTO"]

    g["Avg Settlement"] = g["Settlement"] / (g["Delivered"] + 1)
    g["Final P & L"] = (g["Gross Profit or Loss"] + g["Ads Cost"] + g["Referral Amount"]
                        + g["Return Loss"] + g["RTO Packaging Loss"])
    g["Final PL with GST"] = g["Final P & L"] + g["Available GST Credit"]
    g["Avg Final PL with GST"] = np.where(
        delivered_orders > 0,
        g["Final PL with GST"] / delivered_orders.replace(0, np.nan),
        g["Final PL with GST"] / g["Total Order"].replace(0, np.nan))
    g["Avg Return Charges"] = (g["Return Charges"] + g["Return Loss"]
                               + g["RTO Packaging Loss"]) / g["P.Count"].replace(0, np.nan)
    g["Return %"] = ((g["Exchange"] + g["Customer Return"])
                     / (g["Customer Return"] + g["Delivered"] + g["Exchange"]).replace(0, np.nan))

    # left-of-pivot sheet formulas
    g["RTO %"] = g["RTO"] / g["Total Order"].replace(0, np.nan)
    g["DTO %"] = (g["Customer Return"] + g["Exchange"]) / delivered_orders.replace(0, np.nan)
    g["Avg Gross P/L"] = np.where(
        delivered_orders > 0,
        g["Gross Profit or Loss"] / delivered_orders.replace(0, np.nan),
        g["Gross Profit or Loss"] / g["Total Order"].replace(0, np.nan))
    g["Avg Final PL without GST"] = np.where(
        delivered_orders > 0,
        g["Final P & L"] / delivered_orders.replace(0, np.nan),
        g["Final P & L"] / g["Total Order"].replace(0, np.nan))
    return g.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _aggregate(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    src = {name: col for name, col in MEASURES if col in df.columns}
    agg = df.groupby(by, dropna=False).agg(**{n: (c, "sum") for n, c in src.items()})
    agg["P.Count"] = df.groupby(by, dropna=False)["p_count"].sum()
    return _derived(agg).reset_index()


def sku_report(df: pd.DataFrame) -> pd.DataFrame:
    """Analysis Report equivalent: one row per SKU, 35 measures."""
    out = _aggregate(df, ["supplier_sku"])
    return out.sort_values("Final P & L", ascending=False).reset_index(drop=True)


def state_report(df: pd.DataFrame) -> pd.DataFrame:
    """Region equivalent: one row per customer state."""
    if "state" not in df.columns:
        return pd.DataFrame()
    out = _aggregate(df, ["state"])
    return out.sort_values("Final P & L", ascending=False).reset_index(drop=True)


def suborder_report(df: pd.DataFrame) -> pd.DataFrame:
    """Drill level: one row per sub-order."""
    return _aggregate(df, ["sub_order_no"])


def grand_total(df: pd.DataFrame) -> pd.Series:
    """Row 12 of the dashboard."""
    tmp = df.assign(_all="TOTAL")
    return _aggregate(tmp, ["_all"]).iloc[0]


def kpis(df: pd.DataFrame) -> dict:
    """The VBA KPI panel (CalculationOfPivot), reproduced."""
    t = grand_total(df)
    settle, ads, ref = t["Settlement"], t["Ads Cost"], t["Referral Amount"]
    purchase, gross = t["Purchase"], t["Gross Profit or Loss"]
    total, rto, delivered = t["Total Order"], t["RTO"], t["Delivered"]
    cust_ret, exch, cancelled = t["Customer Return"], t["Exchange"], t["Cancelled"]
    pl = settle + ads + ref - purchase
    delivered_orders = max(total - rto, 0)

    def safe(n, d):
        return float(n / d) if d else 0.0

    return {
        "Profit/Loss": pl,
        "Bank Received": settle + ads + ref,
        "Purchase Amount": purchase,
        "TCS+TDS": t["TCS"] + t["TDS"],
        "Ads Cost": ads,
        "Ads per Order": safe(ads, total + 1),
        "GST Credit Available": t["Available GST Credit"],
        "Total Orders": total,
        "Avg Sales": safe(t["Net Sales"], total),
        "Avg Settlement": safe(settle, delivered_orders + 1),
        "Avg Dispatch Order": safe(gross + ads, total + 1),
        "P/L per Delivered Order": safe(gross, delivered_orders + 1),
        "Delivered %": safe(delivered, total + 1),
        "RTO %": safe(rto, total + 1),
        "Customer Return %": safe(cust_ret, total - rto - cancelled + 1),
        "Exchange %": safe(exch, total - rto - cancelled + 1),
        "P/L % by Sales": safe(pl, t["Net Sales"] + 1),
        "P/L % by Settlement": safe(pl, settle + t["Claims Amt"] + 1),
        "Final P & L": t["Final P & L"],
        "Final P & L with GST": t["Final PL with GST"],
    }


def pending_payments(orders: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Delivered or shipped, but Meesho has not settled -> money owed. [BR-13]"""
    if orders is None or orders.empty:
        return pd.DataFrame()
    paid = df.groupby("sub_order_no")["settlement"].sum()
    out = orders.copy()
    out["settled_amount"] = out["sub_order_no"].map(paid)
    out["payment_status"] = np.where(out["settled_amount"].notna(), "Paid", "Pending")
    status = out.get("order_status", "").astype(str).str.upper()
    pending = out[(out["payment_status"] == "Pending")
                  & status.isin(["DELIVERED", "SHIPPED", "OUT_FOR_DELIVERY"])]
    return pending.reset_index(drop=True)


def overcharge_report(df: pd.DataFrame) -> pd.DataFrame:
    """'Extra Charge' export: rows where Meesho charged beyond the rate card."""
    cols = ["sub_order_no", "supplier_sku", "courier", "weight_slab", "status",
            "order_date", "dispatch_date", "shipping_charge", "s_charge2",
            "return_ship_charge", "rs_charge2", "final_return_charges",
            "shipping_diff", "overcharged", "settlement"]
    out = df[df["overcharged"] == "Yes"]
    return out[[c for c in cols if c in out.columns]].sort_values(
        "shipping_diff", ascending=False).reset_index(drop=True)


def exceptions(df: pd.DataFrame) -> pd.DataFrame:
    """Rows the engine could not fully resolve -- review these before trusting totals."""
    flags = pd.DataFrame(index=df.index)
    flags["missing_cost"] = df.get("cost_missing", False)
    flags["no_status"] = df["status"].isin(["", STATUS_SHIPPED])
    flags["tcs_mismatch"] = df["tcs_variance"].abs() > 0.05
    flags["tds_mismatch"] = df["tds_variance"].abs() > 0.05
    flags["zero_settlement"] = (df["settlement"] == 0) & ~df["is_ads"]
    keep = flags.any(axis=1)
    out = df.loc[keep, ["sub_order_no", "supplier_sku", "status", "settlement",
                        "total_sales2", "purchase", "pl"]].copy()
    for c in flags.columns:
        out[c] = flags.loc[keep, c]
    return out.reset_index(drop=True)
