"""One callable pipeline over a folder of Meesho downloads.

The portal and any future caller drive this instead of re-implementing the CLI:
    result = process_workspace(raw_dir, out_dir)
`result` is JSON-serialisable and says either "needs_costs" (step 1: the SKU cost
sheet was written and profit cannot be computed yet) or "ready" (step 2: the full
report was produced).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import engine, excel_out, ingest, reports
from .cli import classify, DATA_SUFFIXES
from .config import Config


def _f(x, nd=2):
    try:
        v = float(x)
        return round(v, nd) if np.isfinite(v) else 0.0
    except Exception:
        return 0.0


def _sku_economics(r: pd.DataFrame) -> list[dict]:
    """Compact per-SKU table for the portal: unit economics + net P&L."""
    if r.empty:
        return []
    g = r.groupby(r["supplier_sku"].astype(str)).agg(
        orders=("total_order", "sum"), delivered=("delivered", "sum"),
        rto=("rto", "sum"), ret=("customer_return", "sum"),
        settle=("settlement", "sum"), cost=("purchase", "sum"))
    d = r[r["delivered"] > 0]
    dd = d.groupby(d["supplier_sku"].astype(str)).agg(
        s=("settlement", "sum"), c=("purchase", "sum"), n=("delivered", "sum"))
    g["settle_per"] = dd["s"] / dd["n"]
    g["cost_per"] = dd["c"] / dd["n"]
    g["margin_per"] = g["settle_per"] - g["cost_per"]
    g["rto_pct"] = g["rto"] / g["orders"].replace(0, np.nan)
    g["ret_pct"] = g["ret"] / g["orders"].replace(0, np.nan)
    g["net"] = g["settle"] - g["cost"]
    g = g.sort_values("net")
    return [{"sku": k, "orders": int(v["orders"]), "delivered": int(v["delivered"]),
             "rto": int(v["rto"]), "ret": int(v["ret"]),
             "settle_per": _f(v["settle_per"]), "cost_per": _f(v["cost_per"]),
             "margin_per": _f(v["margin_per"]), "rto_pct": _f(v["rto_pct"], 4),
             "net": _f(v["net"])} for k, v in g.iterrows()]


def _state_economics(r: pd.DataFrame) -> list[dict]:
    if r.empty or "state" not in r.columns:
        return []
    g = r.groupby(r["state"].astype(str)).agg(
        orders=("total_order", "sum"), delivered=("delivered", "sum"),
        rto=("rto", "sum"), settle=("settlement", "sum"), cost=("purchase", "sum"))
    g["rto_pct"] = g["rto"] / g["orders"].replace(0, np.nan)
    g["net"] = g["settle"] - g["cost"]
    g = g.sort_values("orders", ascending=False)
    return [{"state": k, "orders": int(v["orders"]), "delivered": int(v["delivered"]),
             "rto": int(v["rto"]), "rto_pct": _f(v["rto_pct"], 4),
             "settle": _f(v["settle"]), "net": _f(v["net"])} for k, v in g.iterrows()]


def process_workspace(raw_dir: Path, out_dir: Path, cfg: Config | None = None,
                      report_only: bool = False, progress=None) -> dict:
    """Run the whole flow over one client's folder. Returns a JSON-able summary."""
    cfg = cfg or Config()
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda *_: None)

    say("scanning files")
    found = [p for p in sorted(raw_dir.rglob("*"))
             if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
             and not p.name.startswith("~$")]
    if not found:
        return {"status": "error", "message": "no data files found in the upload"}
    b = classify(found)
    file_summary = {k: [p.name for p in v] for k, v in b.items()}

    if not b["payments"]:
        return {"status": "error",
                "message": "no Meesho payment file found — upload the "
                           "*PAYMENT_FILE*.xlsx (or its zip) from the supplier panel",
                "files": file_summary}

    say("reading payment files")
    pay = ingest.load_payments(b["payments"])
    ads_df = ingest.load_ads(b["payments"], cfg.fee_gst_rate)
    say("reading orders / returns / costs / claims")
    orders_df = ingest.load_orders(b["orders"]) if b["orders"] else pd.DataFrame()
    returns_df = ingest.load_returns(b["returns"]) if b["returns"] else pd.DataFrame()
    costs_df = ingest.load_costs(b["costs"]) if b["costs"] else pd.DataFrame()
    claims_df = ingest.load_claims(b["claims"]) if b["claims"] else pd.DataFrame()

    if not claims_df.empty:
        pay = pay.merge(claims_df[["sub_order_no", "claim_status"]],
                        on="sub_order_no", how="left")
        pay["claim_status"] = pay["claim_status"].fillna("NA")

    say("reconciling")
    df = engine.run(pay, orders_df, returns_df, costs_df, cfg, ads=ads_df)

    if not orders_df.empty and "customer_state" in orders_df.columns:
        smap = (orders_df.drop_duplicates("sub_order_no")
                         .set_index("sub_order_no")["customer_state"])
        df["state"] = df["sub_order_no"].map(smap).fillna("Unknown")

    # ---- step 1 gate: every SKU needs a Final Cost ----
    priced = set(costs_df["sku_key"]) if not costs_df.empty else set()
    real = df.loc[~df["is_ads"]].copy()
    real["supplier_sku"] = real["supplier_sku"].astype(str)
    drows = real[real["delivered"] > 0]
    avg_sale = (drows.groupby("supplier_sku")["settlement"].sum()
                / drows.groupby("supplier_sku")["delivered"].sum())
    catalogue = (real.groupby("supplier_sku")
                     .agg(product_name=("product_name", "first"),
                          orders=("total_order", "sum"),
                          delivered=("delivered", "sum"),
                          sku_key=("substitute_sku", "first"))
                     .sort_values("orders", ascending=False).reset_index()
                     .rename(columns={"supplier_sku": "sku"}))
    catalogue["avg_sale"] = catalogue["sku"].map(avg_sale).fillna(0.0)
    unpriced = catalogue.loc[~catalogue["sku_key"].isin(priced), "sku"].tolist()

    say("writing SKU cost sheet")
    cost_sheet = out_dir / "SKU_COSTS.xlsx"
    known = ({r["sku_key"]: r.to_dict() for _, r in costs_df.iterrows()}
             if not costs_df.empty else {})
    existing = {str(r["sku"]): known.get(ingest.clean_sku(r["sku"]), {})
                for _, r in catalogue.iterrows()}
    excel_out.write_cost_template(cost_sheet, catalogue, existing)

    base = {
        "files": file_summary,
        "counts": {"payment_rows": int(len(pay)), "ads_rows": int(len(ads_df)),
                   "orders": int(len(orders_df)), "returns": int(len(returns_df)),
                   "claims": int(len(claims_df)), "skus": int(len(catalogue)),
                   "unpriced_skus": len(unpriced)},
        "cost_sheet": cost_sheet.name,
        "unpriced": unpriced[:50],
    }
    if unpriced and not report_only:
        top = catalogue.head(10)
        base.update({
            "status": "needs_costs",
            "top_skus": [{"sku": str(r["sku"]), "orders": int(r["orders"]),
                          "avg_sale": _f(r["avg_sale"])} for _, r in top.iterrows()],
        })
        (out_dir / "result.json").write_text(json.dumps(base, indent=1))
        return base

    # ---- step 2: the full report ----
    say("building report")
    final_only = cfg.final_states_only
    kpi = reports.kpis(df, final_only)
    f = df[df["is_final"] | df["is_ads"]] if final_only and "is_final" in df else df
    r = f[~f["is_ads"]]

    settle, pur = float(r["settlement"].sum()), float(r["purchase"].sum())
    ads = float(f.loc[f["is_ads"], "total_ads_cost"].sum())
    gst = float(r.get("gst_on_settlement", pd.Series(dtype=float)).sum())
    pending = reports.pending_payments(orders_df, df)

    report_path = out_dir / "report.xlsx"
    excel_out.write_report(
        report_path, kpis=kpi,
        sku=reports.sku_report(df, final_only),
        state=reports.state_report(df, final_only),
        suborder=reports.suborder_report(df),
        overcharge=reports.overcharge_report(df),
        pending=pending,
        exceptions=reports.exceptions(df),
    )

    base.update({
        "status": "ready",
        "report": report_path.name,
        "kpis": {k: _f(v) for k, v in kpi.items()},
        "bridge": {
            "settlement": _f(settle), "purchase": _f(pur), "ads": _f(ads),
            "operating_pl": _f(settle - pur + ads), "gst": _f(gst),
            "final_pl": _f(settle - pur + ads + gst),
            "orders": int(r["total_order"].sum()),
            "delivered": int(r["delivered"].sum()),
            "rto": int(r["rto"].sum()),
            "customer_return": int(r["customer_return"].sum()),
            "in_flight": int((~df["is_final"] & ~df["is_ads"]).sum())
                         if "is_final" in df else 0,
            "pending_payments": int(len(pending)),
        },
        "sku_table": _sku_economics(r),
        "state_table": _state_economics(r),
    })
    (out_dir / "result.json").write_text(json.dumps(base, indent=1))
    say("done")
    return base
