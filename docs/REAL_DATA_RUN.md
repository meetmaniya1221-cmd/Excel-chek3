# Kesri Enterprise (supplier 2843411) — June 2026 reconciliation run

First run of the clone engine on real seller data, 17 Aug 2026.

## Input files supplied

| File | Rows | Role |
|---|---|---|
| `meesho_PREVIOUS_PAYMENT_2026-06-01_2026-06-30.zip` → `2843411_SP_ORDER_ADS_REFERRAL_PAYMENT_FILE_...xlsx` | 5,913 order-payment rows + 72 ads rows | settlement, fees, taxes, claims |
| `Orders_2026-06-01_2026-06-30_...csv` | 7,329 | order universe, customer state |
| `completed_delivered_*.csv` | 2,007 | returns that came **back** to the seller |
| `completed_lost_*.csv` | 9 | returns **lost** in transit |
| `intransit_*.csv` / `ofd_reverse_*.csv` | 2 / 128 | returns still moving |
| `Supplier-2843411_Status-all_*.csv` | 491 | claim tickets → Claim Status |

All seven files were classified and consumed automatically by `--data`.

## Schema discovery: Meesho has two payment-file generations

The dossier predicted this from a concatenated header in the sample workbook
(`GST on Shipping Charge', 'CGST + SGST on Shipping Charge`). Confirmed:

| | Sample (2025, M Meldi Krupa) | Real (2026, Kesri) |
|---|---|---|
| Order Payments columns | 116 | 43 |
| Fee columns | "Excl. GST" + 8 separate `GST on <fee>` columns | **"Incl. GST"**, per-fee GST columns dropped |
| Sale amount header | `Total Sale Amount (Incl. Commission & GST)` | `Total Sale Amount (Incl. **Shipping** & GST)` |
| Listing price header | `Listing Price (Incl. GST & Commission)` | `Listing Price (Incl. taxes)` |

The engine reads both through one column map, and its GST method auto-selects:
explicit columns when present, otherwise the settlement-identity derivation.

## Validation against the raw file

Independent re-read of the payment workbook vs the engine's output:

| Check | Raw file | Engine | Verdict |
|---|---|---|---|
| Σ Final Settlement | 727,084.58 | 727,084.58 | exact |
| Σ TCS | −4,114.67 | −4,114.67 (recomputed −4,113.55) | exact / ₹1.12 rounding |
| Σ TDS | −823.15 | −823.15 (recomputed −822.71) | exact / ₹0.44 rounding |
| Σ Claims / Recovery / Compensation | 14,169.77 / −904.79 / 385.42 | identical | exact |
| **Fees back-solved from the settlement identity** | **−252,425.36** (sum of the explicit fee columns) | **−252,425.36** (derived, never read) | **exact** |

That last row is the important one: the GST engine derives Meesho's total fees
from the settlement equation alone and lands on the file's own fee columns to the
paisa — on a file generation it has never seen. The 18/118 credit extraction rests
on that identity, so the GST position is trustworthy here.

## Results (June 2026)

```
orders 5,833 · delivered 3,711 (64%) · RTO 1,569 (27%) · customer return 547 (12%)
net sales        970,797.36        settlement       727,084.58
ads spend        −28,524.22        TCS+TDS           −4,937.82
claims            14,169.77        recovery            −904.79
GST credits       38,505.56        sales GST debit −148,087.73
net GST position −105,231.03
Final P&L (before product cost)   698,560.36
Final P&L incl. GST position      593,329.33
```

**These figures exclude product cost** — no SKU cost master was supplied, so
`Purchase = 0` and profit is overstated by exactly the cost of goods sold.
`output/SKU_COST_TEMPLATE.xlsx` lists all 26 SKUs awaiting a price.

## How the tool is driven (two steps)

Profit cannot be computed without product cost, and Meesho never supplies it, so
the CLI refuses to guess and asks for it once:

```
Step 1   python -m meesho_recon.cli --data ./raw
         Reads every Meesho download, then writes raw/SKU_COSTS.xlsx: one row per
         SKU with empty Product Cost / Packaging Cost / Purchase GST % columns
         (yellow), alongside product name, order count, delivered count and
         average sale price so each SKU can be priced in context. Sorted by
         order volume, highest impact first. Exits without a report.

Step 2   (seller fills the yellow columns, saves the file back into ./raw)
         python -m meesho_recon.cli --data ./raw
         The cost sheet is picked up automatically -- no flag, no renaming --
         and the full reconciliation runs.
```

A later month only needs the new SKUs filled: existing costs are carried into the
regenerated sheet. `--report-only` runs everything except product cost and profit.

Verified on this dataset: step 1 emitted 26 SKUs and stopped; after the sheet was
filled, step 2 reported "all 26 SKUs priced" and produced the full P&L.

## Seller decisions taken (17 Aug 2026)

- **One cost column, not several.** The sheet asks for a single `Final Cost` per
  unit — the seller's total landed cost — instead of splitting product, packaging
  and purchase GST. Legacy cost lists using the split columns still load.
- **Shipping is not a cost line.** The customer pays the courier charge, and
  whatever Meesho deducts is already inside Final Settlement Amount, so shipping
  needs no separate treatment. The courier rate card and its overcharge audit are
  therefore optional, and off unless a card is supplied. Courier is still resolved
  per sub-order from the returns exports (Shadowfax 900, PocketShip 488,
  Delhivery 236, Valmo 152, Xpress Bees 84) and remains available for reporting.

## Outstanding inputs

1. **SKU costs** (26 SKUs) — the step-1 sheet is waiting to be filled; this is the
   only remaining P&L component.

Resolved since the first run: the **May 2026 orders export** was supplied, lifting
payment-row-to-order matching from 55% to **99.8%** (16,337 orders across May and
June), so customer state is now populated for effectively the whole payment file
and the State report no longer collapses into "Unknown".

## Notable outputs

- **Pending Payments: 2,149 orders** delivered or shipped with no settlement row —
  money Meesho has not yet paid.
- **Claim tickets**: 164 approved, 13 rejected, rest open/NA.
- **Return outcomes now resolved from data**, not inferred: 1,843 returns confirmed
  received back, 13 lost, 4 still in transit. This is the signal the sample
  workbook never exposed, and it drives cost recognition (`Config.cost_recognition`).
