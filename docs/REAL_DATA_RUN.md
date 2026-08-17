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

## Result with costs supplied (all 26 SKUs priced)

```
Delivered 3,742 orders   settlement 785,967   cost 703,455   margin  +82,512
RTO       1,558 orders   settlement   3,936   cost  29,545   drag    -25,609
Returns     497 orders   settlement -68,050   cost  22,620   drag    -90,670
Exchange/cancel/shipped                                       drag     +2,632
Ads spend                                                            -28,524
                                                              FINAL  -59,660
GST position                                                        -105,231
                                                    FINAL incl GST  -164,891
```

**Delivered orders are profitable** (₹210.04 settlement vs ₹187.99 cost per unit).
The loss comes from what happens to the other 36% of orders, and from one product
line in particular.

### The loss is concentrated in the CMF line

| Group | SKUs | Orders | Cost/unit | Settlement/unit | Margin/unit | Net P&L |
|---|---|---|---|---|---|---|
| CMF (`black CMF`, `CMF buds black`, `orange CMF`, `CMF buds white`) | 4 | 3,230 | 225–227 | 225–235 | **2–8** | **−61,472** |
| Everything else (Airpod / WA / OB) | 19 | 2,598 | 125–265 | 166–324 | **22–64** | **+30,143** |

A ₹2–8 margin cannot absorb a 15–23% RTO rate plus 9–11% returns. `CMF buds white`
is already negative before any return (cost 225.00 vs settlement 224.84).

### Returns are the single largest drain

Meesho deducted **₹76,503 of return shipping on 497 returns — ₹153.93 each** — and
reversed the sale, so return rows settle at **−₹68,050** in total. Returns alone
cost ₹90,670 against the ₹82,512 the delivered units earned.

Note this qualifies the "customer pays the courier" assumption: forward shipping
behaves that way, but **return** shipping is deducted from the seller, and at
roughly ₹154 a time it decides whether the month is profitable.

### Sensitivity: unconfirmed return stock

268 RTO/return units have no record in the returns exports, so the engine cannot
confirm the stock came back and writes their cost off (`cost_recognition:
"unrecovered"`). If all of that stock was in fact received back
(`cost_recognition: "delivered"`):

| Policy | Purchase | Final P&L |
|---|---|---|
| `unrecovered` (default, cautious) | 758,220 | **−59,660** |
| `delivered` (assumes all returns recovered) | 706,055 | **−7,495** |

Either way the month is a loss; the true figure sits between the two and is pinned
down by a returns export covering the full period.

---

## Correction and re-run: June + July, terminal orders only (17 Aug 2026)

Two changes were made after the July payment file arrived.

### 1. Cost recognition default was wrong

The earlier default (`unrecovered`) charged product cost for every RTO or return
the returns exports did not explicitly confirm as received back. Returns exports
lag: July's RTOs were mostly not in the 17-Aug download, so 1,562 RTO orders were
treated as lost stock and **₹285,840 was written off that had simply not been
recorded yet**. An RTO parcel is Returned To Origin — it comes back by definition.

The default is now `lost_only`: stock is written off only where a returns export
states it was lost. Effect on the June figure reported earlier:

| June 2026 | Purchase | Final P&L |
|---|---|---|
| as first reported (`unrecovered`) | 758,220 | −59,660 |
| **corrected (`lost_only`)** | **707,580** | **−11,777** |

### 2. Per-order figures now count terminal orders only

Orders still in transit have incurred cost without a final settlement, so they
dilute per-order economics. KPIs and the SKU/State grids now count only orders in
a terminal state (`Config.final_states_only`); `--include-in-flight` restores the
old behaviour. June + July: 12,108 terminal, 73 still moving.

### Result, June + July combined

```
orders (terminal)              11,954
delivered                       7,948   settlement/unit 210.65  cost/unit 188.59
                                        margin/unit      22.06
purchase                    1,507,750
ads spend                     -53,034
FINAL P&L                      -1,714      (essentially break-even)
GST position                 -228,193
FINAL P&L incl GST           -229,907
```

Policy sensitivity, June + July: `lost_only` −1,714 · `delivered` −189 ·
`unrecovered` −377,544. The last is not meaningful until the returns exports cover
the whole period.

### What the numbers say

**Operations are break-even, not loss-making.** Delivered units earn ₹22.06 each;
RTO and returns consume almost exactly that.

**The GST position is the real hole.** Output GST of ₹310,181 is owed on sales
against only ₹81,988 of input credit from Meesho's fees. Purchase input credit is
**zero**, because stock is bought without GST invoices. On ₹1,507,750 of purchases
a GST invoice would carry roughly ₹230,000 of credit — very close to the entire
₹228,193 shortfall.

**The CMF line loses money; everything else earns.**

| Group | SKUs | Orders | Cost/unit | Settlement/unit | Margin/unit | Net |
|---|---|---|---|---|---|---|
| CMF | 4 | 6,723 | 225–227 | 225–234 | **−0.2 to 7.0** | **−50,086** |
| Rest | 29 | 5,231 | 125–265 | 154–324 | **29–62** | **+101,406** |

`black CMF` alone is −29,095 across 4,325 orders on a ₹6.96 margin against a 21%
RTO rate. The Airpod/WA SKUs run ₹40–62 margins and absorb RTO rates of 27–41%
while still earning.

## Outstanding inputs

1. **Returns export covering May–June in full** — would resolve the 268 unconfirmed
   units and close the ₹52k range above.

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
