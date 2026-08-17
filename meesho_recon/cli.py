"""Command line entry point -- a two-step flow.

    Step 1   python -m meesho_recon.cli --data ./raw
             Reads the Meesho downloads and writes SKU_COSTS.xlsx: every SKU found,
             with empty Product Cost / Packaging Cost / GST columns to fill in.
             It stops there, because profit cannot be computed without those costs.

    Step 2   (drop the filled SKU_COSTS.xlsx back into ./raw)
             python -m meesho_recon.cli --data ./raw
             The costs are picked up automatically and the full reconciliation runs.

Pass --report-only to skip step 1 and get everything except product cost and profit.
Files are classified by content, so one folder of mixed Meesho downloads works.
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
                    help="where to write the SKU cost sheet "
                         "(default: <data folder>/SKU_COSTS.xlsx)")
    ap.add_argument("--report-only", action="store_true",
                    help="run the report even with no costs; profit excludes product cost")
    ap.add_argument("--include-in-flight", action="store_true",
                    help="also count orders still in transit (default: terminal states only, "
                         "so per-order economics are not diluted by unfinished journeys)")
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

    priced = set(costs_df["sku_key"]) if not costs_df.empty else set()
    real = df.loc[~df["is_ads"]].copy()
    real["supplier_sku"] = real["supplier_sku"].astype(str)
    # Average sale price is quoted per DELIVERED unit: averaging across RTO rows,
    # which settle at about zero, drags the figure well below what the product
    # actually fetches and would push the seller into under-pricing.
    delivered_rows = real[real["delivered"] > 0]
    avg_sale = (delivered_rows.groupby("supplier_sku")["settlement"].sum()
                / delivered_rows.groupby("supplier_sku")["delivered"].sum())
    catalogue = (real.groupby("supplier_sku")
                     .agg(product_name=("product_name", "first"),
                          orders=("total_order", "sum"),
                          delivered=("delivered", "sum"),
                          sku_key=("substitute_sku", "first"))
                     .sort_values("orders", ascending=False).reset_index()
                     .rename(columns={"supplier_sku": "sku"}))
    catalogue["avg_sale"] = catalogue["sku"].map(avg_sale).fillna(0.0)
    unpriced = catalogue.loc[~catalogue["sku_key"].isin(priced), "sku"].tolist()

    if unpriced:
        dest = args.cost_template or ((args.data or args.out.parent) / "SKU_COSTS.xlsx")
        known = ({r["sku_key"]: r.to_dict() for _, r in costs_df.iterrows()}
                 if not costs_df.empty else {})
        existing = {str(r["sku"]): known.get(ingest.clean_sku(r["sku"]), {})
                    for _, r in catalogue.iterrows()}
        excel_out.write_cost_template(dest, catalogue, existing)

        if not args.report_only:
            print(f"\n{'=' * 68}")
            print(f"STEP 1 of 2 — costs needed for {len(unpriced)} of "
                  f"{len(catalogue)} SKUs")
            print("=" * 68)
            print(f"\n  Cost sheet written:  {dest}")
            print("\n  Open it, fill the yellow Final Cost column (your total cost")
            print("  per unit), save, and put the file back in:")
            print(f"      {args.data or dest.parent}")
            print("\n  Then run the same command again and the full profit")
            print("  calculation will run automatically.")
            print("\n  Top SKUs by order volume:")
            for _, r in catalogue.head(10).iterrows():
                print(f"      {int(r['orders']):5d} orders  avg sale "
                      f"{r['avg_sale']:8.2f}   {r['sku']}")
            if len(catalogue) > 10:
                print(f"      ... and {len(catalogue) - 10} more in the sheet")
            print()
            return 2
        print(f"\n  ! {len(unpriced)} SKUs have no cost -- product cost and profit "
              f"are understated.\n    Cost sheet written to {dest}")
    else:
        print(f"  all {len(priced)} SKUs priced -- product cost included")

    if orders_df is not None and not orders_df.empty and "customer_state" in orders_df.columns:
        smap = (orders_df.drop_duplicates("sub_order_no")
                         .set_index("sub_order_no")["customer_state"])
        df["state"] = df["sub_order_no"].map(smap).fillna("Unknown")

    final_only = not args.include_in_flight
    if final_only and "is_final" in df.columns:
        in_flight = int((~df["is_final"] & ~df["is_ads"]).sum())
        counted = int(df["is_final"].sum())
        print(f"  counting {counted:,} orders in a final state; "
              f"{in_flight:,} still in transit excluded from per-order figures")

    tot = engine.totals(df)
    kpi = reports.kpis(df, final_only)
    print("\n" + "=" * 68)
    print("STEP 2 of 2 — full reconciliation")
    print("=" * 68)
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
        sku=reports.sku_report(df, final_only),
        state=reports.state_report(df, final_only),
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
