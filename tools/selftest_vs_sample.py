"""End-to-end test of the engine against the vendor's own answers.

The sample workbook's hidden Payment sheet carries BOTH halves: Meesho's raw
passthrough columns (BA:DJ) and the vendor's computed columns (A:AZ). So we can
feed the raw half through meesho_recon and check we reproduce the vendor half.

    python tools/selftest_vs_sample.py <payment.pkl>
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meesho_recon import engine, reports          # noqa: E402
from meesho_recon.config import Config            # noqa: E402

RAW_MAP = {                       # vendor sheet column -> canonical engine field
    "Sub Order No": "sub_order_no", "Order Date": "order_date",
    "Dispatch Date": "dispatch_date", "Product Name": "product_name",
    "Supplier SKU": "supplier_sku", "Live Order Status": "live_order_status",
    "Product GST %": "product_gst_pct",
    "Listing Price (Incl. GST & Commission)": "listing_price",
    "Quantity": "quantity", "Transaction ID": "transaction_id",
    "Payment Date": "payment_date", "Final Settlement Amount": "settlement",
    "Price Type": "price_type",
    "Total Sale Amount (Incl. Commission & GST)": "sale_amount",
    "Sale Return Amount (Incl. GST)": "sale_return_amount",
    "Fixed Fee (Incl. GST)": "fixed_fee_incl",
    "Warehousing fee (inc Gst)": "warehousing_incl",
    "Shipping Revenue (Incl. GST)": "shipping_revenue",
    "Shipping Return Amount (Incl. GST)": "shipping_return_amt",
    "Return premium (incl GST)": "return_premium",
    "Return premium (incl GST) of Return": "return_premium_ret",
    "Meesho Commission Percentage": "commission_pct",
    "Meesho Commission (Excl. GST)": "commission",
    "Meesho gold platform fee (excl GST)": "gold_fee",
    "Meesho mall platform fee (excl. GST)": "mall_fee",
    "Fixed Fee (excl. GST)": "fixed_fee",
    "Warehousing fee (excl Gst)": "warehousing_fee",
    "Return Shipping Charge (Excl. GST)": "return_ship_charge",
    "GST Compensation (PRP Shipping)": "gst_compensation",
    "Shipping Charge (Excl. GST)": "shipping_charge",
    "Other Support Service Charges (Excl. GST)": "other_support",
    "Waivers (Excl. GST)": "waivers",
    "Net Other Support Service Charges (Excl. GST)": "net_other_support",
    "GST on Meesho Commission": "gst_commission",
    "GST on Warehousing fee": "gst_warehousing",
    "GST on meesho gold": "gst_gold",
    "GST on Meesho Mall platform fee": "gst_mall",
    "GST on Shipping Charge', 'CGST + SGST on Shipping Charge": "gst_shipping",
    "GST on Return Shipping Charge": "gst_return_ship",
    "GST on Net Other Support Service Charges": "gst_net_other",
    "GST on Fixed Fee": "gst_fixed_fee",
    "TCS": "tcs", "TDS Rate %": "tds_rate", "TDS": "tds",
    "Compensation": "compensation", "Claims": "claims", "Recovery": "recovery",
    "Compensation Reason": "compensation_reason", "Claims Reason": "claims_reason",
    "Recovery Reason": "recovery_reason",
}

# engine output -> vendor's own computed column, for column-by-column scoring
CHECKS = [
    ("total_payment", "TotalPayment"),
    ("total_sales2", "Total Sales2"),
    ("total_sales", "Total Sales"),
    ("meesho_gst_credits", "Meesho GST Credits"),
    ("purchase_gst_credit", "Purchase Gst Credit"),
    ("sales_gst_debit", "Sales Gst Debit"),
    ("available_gst_credit", "Available GST Credit"),
    ("purchase", "Purchase"),
    ("pl", "P/L"),
    ("profit_loss_with_gst", "Profit Loss With Gst"),
    ("total_order", "Total Order"),
    ("delivered", "Delivered"),
    ("rto", "RTO"),
    ("customer_return", "Customer Return"),
    ("exchange", "Exchange"),
    ("cancelled", "Cancelled"),
    ("total_ads_cost", "Total Ads Cost"),
    ("tcs_expected", "TCS"),
    ("tds_expected", "TDS"),
]


def main(pkl):
    src = pd.read_pickle(pkl)
    print(f"sample Payment sheet: {src.shape[0]:,} rows x {src.shape[1]} cols")

    raw = pd.DataFrame({dst: src[s] for s, dst in RAW_MAP.items() if s in src.columns})
    raw["_section"] = "Order Payments"
    raw["_source_file"] = src.get("FileName", "sample")
    print(f"raw slice fed to engine: {raw.shape[1]} columns")

    # the vendor's own SKU cost table, recovered from its computed columns
    tmp = src.copy()
    tmp["qty"] = pd.to_numeric(tmp["Quantity"], errors="coerce").replace(0, np.nan)
    tmp["unit"] = pd.to_numeric(tmp["Total Purchase Cost"], errors="coerce") / tmp["qty"]
    costs = (tmp.dropna(subset=["unit"])
                .groupby(tmp["Supplier SKU"].astype(str).str.strip()
                         .str.replace("-", "_", regex=False).str.casefold())["unit"]
                .median().rename("unit_cost").reset_index())
    costs.columns = ["sku_key", "unit_cost"]
    print(f"cost master recovered: {len(costs)} SKUs")

    cfg = Config(return_loss_allowance=0.0, rto_packaging_loss_allowance=0.0)
    raw["_row_id"] = np.arange(len(raw))          # survives the engine's internal re-sort

    # The vendor's ads rows carry a zero settlement: the spend sits in its own
    # column and the GST alongside it -- mirror that, as the raw Ads sheet does.
    ads_mask = src["Live Order Status"].astype(str).eq("Ads Cost").to_numpy()
    raw.loc[ads_mask, "total_ads_cost"] = pd.to_numeric(
        src.loc[ads_mask, "Total Ads Cost"], errors="coerce").to_numpy()
    raw.loc[ads_mask, "gst_ads"] = pd.to_numeric(
        src.loc[ads_mask, "GST"], errors="coerce").to_numpy()
    print(f"ads rows marked: {int(ads_mask.sum())} "
          f"(spend {raw.loc[ads_mask, 'total_ads_cost'].sum():,.2f})")

    out = engine.run(raw, pd.DataFrame(), pd.DataFrame(), costs, cfg)
    out = out.set_index("_row_id").sort_index()    # realign to the vendor sheet's row order
    assert len(out) == len(src), f"row count changed: {len(out)} vs {len(src)}"

    print(f"\n{'engine column':24s} {'vendor column':28s} {'row match':>10s}  {'Σ engine':>16s} {'Σ vendor':>16s}  {'Σ diff':>13s}")
    print("-" * 118)
    scores = []
    for eng_col, vend_col in CHECKS:
        if eng_col not in out.columns or vend_col not in src.columns:
            continue
        a = pd.to_numeric(out[eng_col], errors="coerce").fillna(0.0).to_numpy()
        b = pd.to_numeric(src[vend_col], errors="coerce").fillna(0.0).to_numpy()
        pct = float((np.abs(a - b) < 0.02).mean() * 100)
        scores.append(pct)
        flag = "OK " if pct > 99.5 else "~  " if pct > 90 else "!! "
        print(f"{flag}{eng_col:22s} {vend_col:28s} {pct:9.2f}%  "
              f"{a.sum():16,.2f} {b.sum():16,.2f}  {a.sum() - b.sum():13,.2f}")

    print(f"\ncolumns reproduced >99.5% row-for-row: {sum(1 for p in scores if p > 99.5)}/{len(scores)}"
          f"   >90%: {sum(1 for p in scores if p > 90)}/{len(scores)}")

    t = engine.totals(out)
    print("\nengine grand totals:")
    for k, v in t.items():
        print(f"  {k:22s} {v:>18,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "payment.pkl"))
