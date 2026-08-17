"""Command line entry point.

    python -m meesho_recon.cli --data ./raw --out ./output/report.xlsx

Files are classified by content, so a single folder of mixed Meesho downloads works.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import engine, excel_out, ingest, reports, validate
from .config import Config

DATA_SUFFIXES = {".xlsx", ".xls", ".xlsb", ".csv", ".txt"}


def classify(paths: list[Path]) -> dict[str, list[Path]]:
    """Sort raw files into payments / orders / returns / costs by name then content."""
    buckets = {"payments": [], "orders": [], "returns": [], "costs": [],
               "claims": [], "unknown": []}
    for p in paths:
        name = p.name.lower()
        if "payment" in name or "settlement" in name:
            buckets["payments"].append(p)
        elif name.startswith("order") or "_order" in name:
            buckets["orders"].append(p)
        elif "supplier-" in name or "ticket" in name or "claim" in name:
            buckets["claims"].append(p)
        elif "return" in name or "rto" in name:
            buckets["returns"].append(p)
        elif "cost" in name or "sku" in name or "purchase" in name or name.startswith("pp"):
            buckets["costs"].append(p)
        else:
            buckets["unknown"].append(p)

    # content sniff for anything the filename did not settle
    for p in list(buckets["unknown"]):
        for kind, spec in (("payments", ingest.PAYMENT_FIELDS),
                           ("returns", ingest.RETURN_FIELDS),
                           ("orders", ingest.ORDER_FIELDS),
                           ("costs", ingest.COST_FIELDS)):
            try:
                _, hits = ingest._find_header_row(p, 0, spec)
            except Exception:
                hits = 0
            if hits >= 5:
                buckets[kind].append(p)
                buckets["unknown"].remove(p)
                break
    return buckets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="meesho-recon",
                                 description="Reconcile Meesho seller payments end to end.")
    ap.add_argument("--data", type=Path, help="folder of raw Meesho downloads")
    ap.add_argument("--payments", type=Path, nargs="*", default=[])
    ap.add_argument("--orders", type=Path, nargs="*", default=[])
    ap.add_argument("--returns", type=Path, nargs="*", default=[])
    ap.add_argument("--costs", type=Path, nargs="*", default=[])
    ap.add_argument("--claims", type=Path, nargs="*", default=[])
    ap.add_argument("--cost-template", type=Path,
                    help="write a SKU cost sheet to fill in, listing every SKU seen")
    ap.add_argument("--rate-card", type=Path, help="JSON: {courier: {forward: x, return: y}}")
    ap.add_argument("--out", type=Path, default=Path("output/reconciliation.xlsx"))
    ap.add_argument("--config", type=Path, help="JSON overrides for Config")
    ap.add_argument("--validate", action="store_true",
                    help="compare totals against the sample workbook's golden numbers")
    ap.add_argument("--dump-table", type=Path, help="write the full computed row table")
    args = ap.parse_args(argv)

    cfg = Config()
    if args.config and args.config.exists():
        for k, v in json.loads(args.config.read_text()).items():
            setattr(cfg, k, v)
    if args.rate_card and args.rate_card.exists():
        card = json.loads(args.rate_card.read_text())
        cfg.courier_rate_card = {
            (courier, rates.get("weight_slab", cfg.default_weight_slab)): rates
            for courier, rates in card.items()
        }

    payments, orders, returns, costs = (list(args.payments), list(args.orders),
                                        list(args.returns), list(args.costs))
    claims = list(args.claims)
    if args.data:
        found = [p for p in sorted(args.data.rglob("*"))
                 if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
                 and not p.name.startswith("~$")]
        b = classify(found)
        payments += b["payments"]; orders += b["orders"]
        returns += b["returns"];   costs += b["costs"]
        claims += b["claims"]
        print(f"Discovered {len(found)} files -> payments={len(b['payments'])} "
              f"orders={len(b['orders'])} returns={len(b['returns'])} "
              f"costs={len(b['costs'])} claims={len(b['claims'])} "
              f"unclassified={len(b['unknown'])}")
        for p in b["unknown"]:
            print(f"  ! unclassified: {p.name}")

    if not payments:
        ap.error("no payment files found -- pass --payments or a --data folder containing them")

    print("Reading payment files ...")
    pay = ingest.load_payments(payments)
    print(f"  {len(pay):,} payment rows from {len(payments)} file(s)")

    ads_df = ingest.load_ads(payments, cfg.fee_gst_rate)
    if not ads_df.empty:
        print(f"  {len(ads_df):,} ads/referral rows "
              f"(spend {ads_df['total_ads_cost'].sum():,.2f})")
    orders_df = ingest.load_orders(orders) if orders else pd.DataFrame()
    returns_df = ingest.load_returns(returns) if returns else pd.DataFrame()
    costs_df = ingest.load_costs(costs) if costs else pd.DataFrame()
    claims_df = ingest.load_claims(claims) if claims else pd.DataFrame()
    for label, d in (("orders", orders_df), ("returns", returns_df),
                     ("cost rows", costs_df), ("claim tickets", claims_df)):
        print(f"  {len(d):,} {label}")

    if not claims_df.empty:
        pay = pay.merge(claims_df[["sub_order_no", "claim_status"]],
                        on="sub_order_no", how="left")
        pay["claim_status"] = pay["claim_status"].fillna("NA")

    print("Running reconciliation ...")
    df = engine.run(pay, orders_df, returns_df, costs_df, cfg, ads=ads_df)

    if args.cost_template:
        seen = (df.loc[~df["is_ads"]]
                  .groupby("supplier_sku")
                  .agg(orders=("total_order", "sum"), delivered=("delivered", "sum"),
                       avg_sale=("total_sales2", "mean"))
                  .sort_values("orders", ascending=False).reset_index())
        seen.insert(1, "product_cost", "")
        seen.insert(2, "packaging_cost", "")
        seen.insert(3, "gst_pct", "")
        args.cost_template.parent.mkdir(parents=True, exist_ok=True)
        seen.rename(columns={"supplier_sku": "sku"}).to_excel(args.cost_template, index=False)
        print(f"Cost template written: {args.cost_template} ({len(seen)} SKUs to price)")

    if orders_df is not None and not orders_df.empty and "customer_state" in orders_df.columns:
        smap = (orders_df.drop_duplicates("sub_order_no")
                         .set_index("sub_order_no")["customer_state"])
        df["state"] = df["sub_order_no"].map(smap).fillna("Unknown")

    tot = engine.totals(df)
    kpi = reports.kpis(df)
    print("\n--- KPIs " + "-" * 52)
    for k, v in kpi.items():
        print(f"  {k:26s} {v:>18,.2f}")

    val = None
    if args.validate:
        val = validate.compare(tot)
        print("\n--- Validation vs sample workbook: " + validate.summarise(val))
        for _, r in val[val["verdict"].isin(["MISMATCH", "MISSING"])].iterrows():
            print(f"  {r['verdict']:9s} {r['metric']:22s} "
                  f"expected={r['expected']} actual={r['actual']}")

    out = excel_out.write_report(
        args.out,
        kpis=kpi,
        sku=reports.sku_report(df),
        state=reports.state_report(df),
        suborder=reports.suborder_report(df),
        overcharge=reports.overcharge_report(df),
        pending=reports.pending_payments(orders_df, df),
        exceptions=reports.exceptions(df),
        validation=val,
    )
    print(f"\nReport written: {out}")

    if args.dump_table:
        args.dump_table.parent.mkdir(parents=True, exist_ok=True)
        (df.to_csv(args.dump_table, index=False) if args.dump_table.suffix == ".csv"
         else df.to_pickle(args.dump_table))
        print(f"Row table written: {args.dump_table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
