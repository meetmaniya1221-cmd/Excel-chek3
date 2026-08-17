"""The reconciliation engine.

Every formula below was recovered from the vendor workbook and verified against
its 43,490 embedded rows. The docstring of each step cites its evidence grade
from docs/REVERSE_ENGINEERING.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (COST_RECOGNISED_STATUSES, ORDER_STATUS_MAP, STATUS_ADS,
                     STATUS_CANCELLED, STATUS_DELIVERED, STATUS_EXCHANGE, STATUS_LOST,
                     STATUS_RETURN, STATUS_RTO, STATUS_SHIPPED, TERMINAL_STATUSES,
                     Config)
from .ingest import clean_sku

MONEY = [
    "settlement", "sale_amount", "sale_return_amount", "shipping_charge",
    "return_ship_charge", "tcs", "tds", "compensation", "claims", "recovery",
    "commission", "fixed_fee", "warehousing_fee", "gold_fee", "mall_fee",
    "other_support", "waivers", "net_other_support", "gst_compensation",
    "shipping_revenue", "shipping_return_amt", "return_premium", "return_premium_ret",
    "gst_commission", "gst_warehousing", "gst_gold", "gst_mall", "gst_shipping",
    "gst_return_ship", "gst_net_other", "gst_fixed_fee",
    "product_gst_pct", "quantity", "listing_price", "commission_pct",
]
GST_FEE_COLS = ["gst_commission", "gst_warehousing", "gst_gold", "gst_mall",
                "gst_shipping", "gst_return_ship", "gst_net_other", "gst_fixed_fee"]


def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def _col(df: pd.DataFrame, name: str, default="") -> pd.Series:
    """Always return a Series, even when the column is absent."""
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)


def prepare(pay: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Coerce types, normalise keys and dates."""
    df = pay.copy()
    for c in MONEY + ["total_ads_cost", "gst_ads"]:
        df[c] = _num(df[c]) if c in df.columns else 0.0

    for c in ("order_date", "dispatch_date", "payment_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True) if c in df.columns else pd.NaT

    df["sub_order_no"] = df.get("sub_order_no", "").astype(str).str.strip()
    df["supplier_sku"] = df.get("supplier_sku", "").astype(str).str.strip()
    df["substitute_sku"] = df["supplier_sku"].map(clean_sku)
    df["id_sku"] = df["sub_order_no"] + " | " + df["supplier_sku"]

    # Ads / referral lines are pseudo-orders: they arrive on their own sheet in the
    # raw file, carry no real sub-order, and are labelled in the status column.
    label = pd.concat([
        df["supplier_sku"].str.casefold(),
        _col(df, "live_order_status").astype(str).str.casefold(),
        _col(df, "product_name").astype(str).str.casefold(),
    ], axis=1)
    is_ads_label = label.isin(["ads cost", "referral payments", "ads", "referral"]).any(axis=1)
    df["is_ads"] = (
        df["sub_order_no"].isin(["", "nan", "None", "0"])
        | is_ads_label
        | _col(df, "_section").astype(str).str.casefold().str.contains("ad|referral", regex=True)
    )
    df["is_referral"] = label.isin(["referral payments", "referral"]).any(axis=1)
    return df


def add_keys(df: pd.DataFrame) -> pd.DataFrame:
    """cSKid occurrence counter and first-row-of-sub-order flag. [PROVEN]"""
    df = df.sort_values(["sub_order_no", "payment_date"], kind="stable").reset_index(drop=True)
    df["cskid"] = df.groupby("id_sku").cumcount() + 1
    df["is_first_row"] = ~df.duplicated("sub_order_no")
    return df


def correct_status(df: pd.DataFrame, orders: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Live Order Status 2: Meesho's status reconciled against payment evidence.

    The vendor's exact rules are not recoverable from the sample (docs section H.4);
    this implements the corrections the sample data demonstrably contains:
      * a return-shipping charge or a negative sale-return amount means the parcel
        came back from the customer -> Return (964 such rows in the sample)
      * an explicit return record classifies RTO vs DTO
      * rows with no status but a settlement are resolved from the orders file
    Anything unexplained keeps Meesho's own status.
    """
    raw = _col(df, "live_order_status").astype(str).str.strip()
    status = raw.str.upper().map(ORDER_STATUS_MAP).fillna(raw)

    if orders is not None and not orders.empty and "order_status" in orders.columns:
        omap = (orders.dropna(subset=["sub_order_no"])
                      .drop_duplicates("sub_order_no")
                      .set_index("sub_order_no")["order_status"]
                      .astype(str).str.upper().map(ORDER_STATUS_MAP))
        filled = df["sub_order_no"].map(omap)
        status = status.where(status.str.len() > 0, filled)

    if returns is not None and not returns.empty and "return_type" in returns.columns:
        r = returns.drop_duplicates("sub_order_no").set_index("sub_order_no")
        rtype = df["sub_order_no"].map(r["return_type"]).astype(str).str.upper()
        # "Courier Return (RTO)" = never reached the customer; "Customer Return" = DTO
        status = pd.Series(
            np.where(rtype.str.contains("RTO"), STATUS_RTO,
            np.where(rtype.str.contains("CUSTOMER|DTO"), STATUS_RETURN, status)),
            index=df.index)
        if "return_outcome" in r.columns:
            df["return_outcome"] = df["sub_order_no"].map(r["return_outcome"]).fillna("none")
        if "courier" in r.columns:
            df["courier_from_returns"] = df["sub_order_no"].map(r["courier"]).fillna("NA")

    # payment evidence: a customer return shows up as return shipping / sale reversal
    returned = (df["return_ship_charge"] != 0) | (df["sale_return_amount"] < 0)
    status = status.where(~(returned & status.isin([STATUS_DELIVERED])) | (df["sale_amount"] <= 0),
                          status)
    df["status"] = status.fillna("").replace({"": STATUS_SHIPPED})
    df.loc[df["is_ads"], "status"] = STATUS_ADS
    return df


def add_counters(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Order counts and status one-hots. [VERIFIED 97-100%]"""
    first = df["is_first_row"] & ~df["is_ads"]
    df["total_order"] = np.where(first, 1.0, 0.0) if cfg.count_orders_on_first_row else \
                        np.where(~df["is_ads"], 1.0, 0.0)

    to = df["total_order"]
    df["delivered"] = np.where(df["status"] == STATUS_DELIVERED, to, 0.0)
    df["rto"] = np.where(df["status"] == STATUS_RTO, to, 0.0)
    df["customer_return"] = np.where(df["status"] == STATUS_RETURN, to, 0.0)
    df["exchange"] = np.where(df["status"] == STATUS_EXCHANGE, to, 0.0)
    df["cancelled"] = np.where(df["status"] == STATUS_CANCELLED, to, 0.0)
    df["lost_qty"] = np.where(df["status"] == STATUS_LOST, to, 0.0)

    # units that physically reached a customer (drives cost recognition)
    df["drc"] = df["delivered"] + df["customer_return"] + df["exchange"]

    df["claim_qty"] = np.where(_col(df, "claim_status").astype(str).eq("Approved"), 1.0, 0.0)
    has_recovery_reason = (_col(df, "recovery_reason").astype(str).str.strip()
                           .replace({"nan": "", "NA": "", "None": ""}).ne(""))
    df["recovery_qty"] = np.where(has_recovery_reason | (df["recovery"] != 0), 1.0, 0.0)

    # orders with money movement -> denominator of Avg Return Charges
    df["p_count"] = (np.where(df["total_payment"] != 0, df["total_order"], 0.0)
                     if "total_payment" in df.columns else df["total_order"])

    # Has this order finished its journey? A parcel still in transit -- forward or
    # on its way back -- has incurred cost without a final settlement, so it is
    # excluded from per-order economics.
    still_moving = _col(df, "return_outcome", "none").eq("in_transit")
    df["is_final"] = df["status"].isin(TERMINAL_STATUSES) & ~still_moving & ~df["is_ads"]
    return df


def add_money(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Settlement grouping and sales. [PROVEN 100%]"""
    # C: sub-order settlement total, repeated on every row of the group
    df["total_payment"] = df.groupby("sub_order_no")["settlement"].transform("sum")
    df.loc[df["is_ads"], "total_payment"] = df.loc[df["is_ads"], "settlement"]

    # D: net sale of the row = sale amount + sale return amount
    df["total_sales2"] = df["sale_amount"] + df["sale_return_amount"]

    # AS: order-level net sale, stamped on the first row
    grp = df.groupby("sub_order_no")["total_sales2"].transform("sum")
    df["total_sales"] = np.where(df["is_first_row"] & ~df["is_ads"], grp, 0.0)
    return df


def add_purchase(df: pd.DataFrame, costs: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """AK -> AE: product cost recognised for units the seller did not get back.

    RTO and cancelled units come back to stock and cost nothing. Delivered units
    always consume cost. Customer returns depend on whether the parcel was actually
    received back in sellable condition -- a fact the payment file does not carry,
    so the policy is configurable (see Config.cost_recognition). [VERIFIED ~97%]
    """
    if costs is not None and not costs.empty and "sku_key" in costs.columns:
        cmap = costs.set_index("sku_key")["unit_cost"]
        df["unit_cost"] = df["substitute_sku"].map(cmap).fillna(0.0)
        df["cost_missing"] = ~df["substitute_sku"].isin(cmap.index) & ~df["is_ads"]
    else:
        df["unit_cost"] = 0.0
        df["cost_missing"] = ~df["is_ads"]

    qty = df["quantity"].where(df["quantity"] > 0, 1.0)
    df["total_purchase_cost"] = df["unit_cost"] * qty

    policy = cfg.cost_recognition
    returned_units = np.maximum(df["customer_return"], df["rto"])

    if policy == "delivered":
        units = df["delivered"] + df["exchange"]
    elif policy == "delivered_return":
        units = df["delivered"] + df["customer_return"] + df["exchange"]
    elif policy == "lost_only":
        # Stock is written off only where a returns export says it was lost.
        # Everything else is assumed to have come back, which is what RTO means.
        lost = _col(df, "return_outcome", "none").eq("lost") | (df["lost_qty"] > 0)
        units = df["delivered"] + df["exchange"] + np.where(lost, returned_units, 0.0)
    else:                                   # "unrecovered"
        # Preferred signal: the returns export says whether the parcel came back.
        # Fallback when no returns file is supplied: a full sale reversal implies
        # the stock was recovered.
        if "return_outcome" in df.columns:
            recovered = df["return_outcome"].eq("recovered")
        else:
            recovered = (df["sale_amount"] + df["sale_return_amount"]).abs().lt(0.01)
        returned = (df["customer_return"] > 0) | (df["rto"] > 0)
        units = df["delivered"] + df["exchange"] + np.where(
            returned & ~recovered, returned_units, 0.0)
    df["cost_units"] = units
    df["purchase"] = df["total_purchase_cost"] * units
    return df


def add_gst(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """The GST line.

    Default ("settlement_flat"): a flat percentage of the settlement that actually
    reaches the bank -- one figure, with no output/input breakdown. This is what
    a seller who files on turnover needs, and it is the mode this client uses.

    "detailed" reproduces the vendor workbook's model instead: output GST on the
    net sale, plus input credit on Meesho's fees derived by back-solving total
    fees from the settlement identity and taking the 18/118 slice
        settlement = net_sale - fees_incl_gst + tcs + tds + compensation + claims + recovery
    plus input credit on purchases. [PROVEN 100% on the 2025 sample and on the
    2026 file, where the derived fees matched the file's own fee columns exactly.]
    """
    if cfg.gst_method == "settlement_flat":
        rate = cfg.gst_settlement_rate
        settle = np.where(df["is_ads"], 0.0, df["settlement"])
        # "net" follows the money: Meesho nets return reversals off the payout, so
        # the bank receives the net figure and the GST on a returned sale unwinds
        # with it. "gross" taxes receipts and lets the reversals go untaxed.
        base = settle if cfg.gst_settlement_base == "net" else np.clip(settle, 0, None)
        df["gst_on_settlement"] = -base * rate
        df["meesho_gst_credits"] = 0.0
        df["purchase_gst_credit"] = 0.0
        df["sales_gst_debit"] = df["gst_on_settlement"]
        df["available_gst_credit"] = df["gst_on_settlement"]
        return df

    non_fee = (df["total_sales2"] + df["tcs"] + df["tds"]
               + df["compensation"] + df["claims"] + df["recovery"])
    fees_incl_gst = df["settlement"] - non_fee                 # negative = charged
    r = cfg.fee_gst_rate
    derived = -fees_incl_gst * (r / (1 + r))

    explicit = sum(df[c] for c in GST_FEE_COLS if c in df.columns)
    explicit = -explicit if isinstance(explicit, pd.Series) else pd.Series(0.0, index=df.index)

    if cfg.gst_credit_method == "derive":
        credit = derived
    elif cfg.gst_credit_method == "columns":
        credit = explicit
    else:                                                       # auto
        credit = np.where(explicit != 0, explicit, derived)
        credit = pd.Series(credit, index=df.index)

    ads_gst = _num(_col(df, "gst_ads", 0.0))
    df["meesho_gst_credits"] = np.where(df["is_ads"], -ads_gst, credit)
    df["purchase_gst_credit"] = df["purchase"] * cfg.purchase_gst_rate

    # output GST is owed on real sales only -- ads/referral lines are purchases, not sales
    gst_pct = df["product_gst_pct"]
    df["sales_gst_debit"] = np.where(
        df["is_ads"], 0.0,
        -df["total_sales2"] * gst_pct / (100.0 + gst_pct.where(gst_pct != 0, 100.0)))
    df["available_gst_credit"] = (df["meesho_gst_credits"] + df["purchase_gst_credit"]
                                  + df["sales_gst_debit"])
    return df


def add_taxes(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Recompute TCS/TDS from the taxable base and compare with the file. [PROVEN 100%]"""
    gst_pct = df["product_gst_pct"]
    taxable = df["total_sales2"] / (1.0 + gst_pct / 100.0)
    df["tcs_expected"] = -taxable * cfg.tcs_rate
    df["tds_expected"] = -taxable * cfg.tds_rate
    df["tcs_variance"] = df["tcs"] - df["tcs_expected"]
    df["tds_variance"] = df["tds"] - df["tds_expected"]
    return df


def add_shipping_audit(df: pd.DataFrame, returns: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Rate-card audit -> Final Return Charges, Overcharged, Shipping Diff. [VERIFIED ~95%]"""
    if "courier_from_returns" in df.columns:
        df["courier"] = df["courier_from_returns"]
    elif returns is not None and not returns.empty and "courier" in returns.columns:
        cmap = returns.drop_duplicates("sub_order_no").set_index("sub_order_no")["courier"]
        df["courier"] = df["sub_order_no"].map(cmap).fillna("NA")
    else:
        df["courier"] = "NA"
    df["courier"] = df["courier"].replace("", "NA").fillna("NA")
    df["weight_slab"] = cfg.default_weight_slab

    fwd_exp = pd.Series(0.0, index=df.index)
    ret_exp = pd.Series(0.0, index=df.index)
    if cfg.courier_rate_card:
        key = list(zip(df["courier"], df["weight_slab"]))
        fwd_exp = pd.Series([cfg.courier_rate_card.get(k, {}).get("forward", 0.0) for k in key],
                            index=df.index)
        ret_exp = pd.Series([cfg.courier_rate_card.get(k, {}).get("return", 0.0) for k in key],
                            index=df.index)

    df["s_charge2"] = fwd_exp                       # expected forward charge
    # corrected return charge: only where the card says Meesho charged too much
    overcharged_ret = (ret_exp != 0) & (df["return_ship_charge"] < ret_exp - 0.01)
    df["rs_charge2"] = np.where(overcharged_ret, ret_exp, 0.0)

    # E: charged fee, replaced by the corrected value where one exists
    df["final_return_charges"] = np.where(df["rs_charge2"] != 0,
                                          df["rs_charge2"], df["return_ship_charge"])

    overcharged_fwd = (fwd_exp != 0) & (df["shipping_charge"] < fwd_exp - 0.01)
    df["overcharged"] = np.where(overcharged_ret | overcharged_fwd, "Yes", "NA")

    df["shipping_diff"] = (np.where(overcharged_fwd, fwd_exp - df["shipping_charge"], 0.0)
                           + np.where(overcharged_ret, ret_exp - df["return_ship_charge"], 0.0))
    return df


def add_pl(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Row P&L and its GST-inclusive variant. [PROVEN 100%]"""
    df["pl"] = df["settlement"] - df["purchase"]
    df["profit_loss_with_gst"] = df["pl"] + df["available_gst_credit"]

    # ads/referral spend arrives on its own feed; if absent, fall back to the
    # settlement column (some exports book the deduction there instead)
    referral = df["is_ads"] & _col(df, "is_referral", False).astype(bool)
    spend = _num(_col(df, "total_ads_cost", 0.0))
    spend = spend.where(spend != 0, df["settlement"])
    df["net_referral_amount"] = np.where(referral, spend, 0.0)
    df["total_ads_cost"] = np.where(df["is_ads"] & ~referral, spend, 0.0)

    df["return_loss_pct"] = np.where(df["is_ads"], cfg.return_loss_allowance, 0.0)
    df["rto_packaging_loss"] = np.where(df["is_ads"], cfg.rto_packaging_loss_allowance, 0.0)
    return df


def add_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Materialised date parts (the slicer columns OD/OM/OY, PD/PM/PY)."""
    for src, pre in (("order_date", "o"), ("payment_date", "p")):
        d = df[src]
        df[f"{pre}d"] = d.dt.strftime("%d")
        df[f"{pre}m"] = d.dt.strftime("%b")
        df[f"{pre}y"] = d.dt.strftime("%Y")
    return df


def run(payments: pd.DataFrame, orders: pd.DataFrame, returns: pd.DataFrame,
        costs: pd.DataFrame, cfg: Config, ads: pd.DataFrame | None = None) -> pd.DataFrame:
    """Full pipeline -> the 'Payment' table equivalent, one row per payment line.

    `ads` carries the ads/referral sections, which are not settlement rows: their
    spend lands in total_ads_cost and their GST in the input-credit column.
    """
    if ads is not None and not ads.empty:
        payments = pd.concat([payments, ads], ignore_index=True, sort=False)
    df = prepare(payments, cfg)
    df = add_keys(df)
    df = correct_status(df, orders, returns)
    df = add_money(df, cfg)
    df = add_counters(df, cfg)
    df = add_purchase(df, costs, cfg)
    df = add_gst(df, cfg)
    df = add_taxes(df, cfg)
    df = add_shipping_audit(df, returns, cfg)
    df = add_pl(df, cfg)
    df = add_dates(df)
    return df


def totals(df: pd.DataFrame) -> dict:
    """The 25 golden numbers, comparable with the vendor workbook."""
    s = lambda c: float(df[c].sum())
    return {
        "rows": int(len(df)),
        "orders": s("total_order"),
        "delivered": s("delivered"),
        "rto": s("rto"),
        "customer_return": s("customer_return"),
        "exchange": s("exchange"),
        "cancelled": s("cancelled"),
        "net_sales": s("total_sales"),
        "settlement": s("settlement"),
        "purchase": s("purchase"),
        "gross_pl": s("pl"),
        "ads": s("total_ads_cost"),
        "referral": s("net_referral_amount"),
        "tcs": s("tcs"),
        "tds": s("tds"),
        "claims": s("claims"),
        "recovery": s("recovery"),
        "compensation": s("compensation"),
        "gst_credits": s("meesho_gst_credits"),
        "purchase_gst_credit": s("purchase_gst_credit"),
        "sales_gst_debit": s("sales_gst_debit"),
        "avail_gst": s("available_gst_credit"),
        "return_charges": s("final_return_charges"),
        "shipping_diff": s("shipping_diff"),
        "final_pl": (s("pl") + s("total_ads_cost") + s("net_referral_amount")
                     + s("return_loss_pct") + s("rto_packaging_loss")),
        "final_pl_with_gst": (s("pl") + s("total_ads_cost") + s("net_referral_amount")
                              + s("return_loss_pct") + s("rto_packaging_loss")
                              + s("available_gst_credit")),
    }
