# Meesho Analysos 0.4.5 — Reverse-Engineering Dossier

**Workbook:** `01 M Meldi Krupa 1260895return Meesho Analysos 0.4.5_1.xlsb` (19.86 MB, macro-enabled binary)
**Analyzed:** 2026-08-17 · direct BIFF12 binary parse + full VBA extraction + empirical verification against the 43,490 embedded data rows
**Meesho supplier:** ID 1260895 ("M Meldi Krupa", client of "Meldi Maa Enterprise" folder #1413 on the vendor's server)
**Workbook lifecycle:** created 2022-06-10, last modified 2025-07-31; pivot cache last refreshed 2025-07-31 13:50 by vendor operator `yagnesh--4`
**Vendor contact baked into UI:** WhatsApp button → `https://wa.me/919913315809`

Evidence grading used throughout:

| Grade | Meaning |
|---|---|
| **PROVEN** | Formula/identity reproduced exactly (≥99.9% of 43,490 rows, or read directly from formulas/VBA/pivot definitions) |
| **VERIFIED ~N%** | Identity reproduces N% of rows; residual is a known edge case |
| **INFERRED** | Best explanation consistent with all evidence, not directly provable from this file |
| **UNKNOWN** | Cannot determine until raw data is provided |

---

## A. Executive Summary

This workbook is the **delivery vehicle of a two-stage Meesho seller-reconciliation service**. It computes, per sub-order and per SKU, what Meesho actually paid vs. what it should have paid, and turns that into a profit & loss dashboard.

What it does, in plain language:

1. The seller downloads their raw files from the Meesho Supplier Panel (payment files, orders exports, returns data).
2. The **vendor's upstream tool** (a separate workbook/process the vendor keeps — *not* included here) merges those files into one wide "Payment" table: one row per payment-file line, 116 columns = Meesho's raw columns + ~50 vendor-computed reconciliation columns (order counts, status corrections, GST credit math, expected-vs-charged shipping, per-order P&L).
3. A processed copy is dropped into a `Backup\` folder next to this workbook. The **Update button in this workbook imports that file as pasted values** (no live formulas), hides the data sheet (very hidden), and repoints two pivot tables at it.
4. The user interacts only with two pivot dashboards (SKU-level and State-level), 14 slicers, a date-range calendar, and a payment-amount filter. Every headline KPI (Final P&L, GST position, return rates, overcharged shipping recovery) is a pivot aggregation of the hidden table.

The **row-level intelligence lives upstream** — this file contains only its *outputs*. However, because all 43,490 processed rows are embedded, nearly every upstream formula could be **reconstructed empirically and verified to 100%** (Section D/E). The genuinely proprietary remainder is small: the courier rate card, the courier-assignment source, and a handful of config constants.

Headline numbers in the current snapshot (11-Dec-2024 → 26-Jul-2025 order window):
Sales ₹73.4 L · Settlements received ₹52.3 L · Purchase cost recognized ₹39.1 L · **Final P&L ₹11.5 L** · Final P&L incl. GST position ₹4.2 L · 40,994 orders · 61.5% delivered · 32.9% RTO · ads spend ₹1.68 L · shipping overcharge identified ₹3.34 L.

---

## B. Workbook Architecture

### B.1 Sheets

| # | Sheet | Visibility | Protection | VBA codename | Purpose |
|---|-------|-----------|------------|--------------|---------|
| 1 | **Region** | visible | protected, no password | `Report1211` (empty module) | State-level pivot dashboard. PivotTable rows `Ok → State → Supplier SKU`, 17 value columns. Header formulas mirror Analysis Report date range. |
| 2 | **Analysis Report** | visible | protected, no password | `Report111` (main UI module) | **Primary dashboard.** Pivot rows `Ok → Supplier SKU → Sub Order No → Transaction ID`, 34 value columns + 1 helper column. All KPI interactivity lives here. |
| 3 | **PP** | visible | protected | `Sheet1` (empty) | Legacy **product-cost master** (SKU → cost, packaging, GST). **Stale & disconnected**: dates 01-Jan-2020, different product catalog, and *nothing in the workbook references it*. It documents the cost-master format the vendor maintains upstream. |
| 4 | **Temp** | visible | protected | `Sheet2` (empty) | Advanced Filter staging area: criteria cells + copy of Payment header + filtered extract target. |
| 5 | **Payment** | **very hidden** | protected | `Payment` (empty) | **The engine room.** 116 columns (A:DL) × 43,490 rows, header on row 2, 100% pasted values (zero formulas). Source of both pivot caches. |
| 6 | **Sales** | visible | protected | `Sales` (2 button handlers) | Meesho **Orders export** + 4 vendor columns; 63,509 rows × 16 cols (A:P), autofilter on A2:Q2, `SUBTOTAL` totals in row 1. |
| 7 | **Update Data** | visible | protected | `Sheet3` (update button) | Empty launcher sheet: branding + hidden `cmdUpdate` ActiveX button (toggled by Ctrl+Shift+M). Workbook opens here. |

Sheet protection is enabled without passwords (hash 0x0000) — protection is cosmetic, to keep the operator inside the intended UI.

### B.2 Defined names

- `Temp!Criteria`, `Temp!Extract` — Excel Advanced Filter plumbing.
- `_FilterDatabase` (Temp, Payment, Sales) — autofilter/advanced-filter ranges.
- `_xlfn.IFERROR`, `_xlfn.XLOOKUP` — future-function compatibility names (evidence the workbook was touched by pre-dynamic-array Excel; XLOOKUP is used somewhere in the vendor's toolchain).
- 13 macro names bound to UI buttons: `AdvanceFilter_Data`, `Analysis_Report`, `Calci`, `CollapseAll`, `CollapseAll2`, `DataSourceSelection`, `ExpandAll`, `ExpandAll2`, `ImageLocation2`, `RefreshAll`, `SalesClick`, `SortAtoZ`, `Whatsapp`.
- 14 slicer names (below).

### B.3 Pivot tables, caches, slicers

Two pivot tables, both named `PivotTable1` on their own sheets:

**Analysis Report pivot** (part `pivotTable2.bin`, cache `pivotCacheDefinition1.bin`):
- Source `Payment!A2:DL43492` (43,490 records), refreshed 31-Jul-2025.
- Row fields: `Ok` → `Supplier SKU` → `Sub Order No` → `Transaction ID` (drill buttons switch between SKU and Sub Order levels).
- Page/filter area: 7 fields (cache fields 0–6: `cSKid`, `P.Count`, `TotalPayment`, `Total Sales2`, `Final Return Charges`, `Overcharged`, `Courier Company`) — the `TotalPayment` page filter is what the "payment range" Advanced-Filter UI drives.
- 34 data items (all **Sum**), rendering to report columns E:AL — see Section D.3.
- **6 calculated fields** (formulas decoded from the cache in Section D.2).
- Cache stores no records for this pivot (definition carries fields + shared items only).

**Region pivot** (part `pivotTable1.bin`, cache `pivotCacheDefinition2.bin` + `pivotCacheRecords1.bin`, 74 MB):
- Same source range; 116 fields (no calculated fields).
- Row fields: `Ok` → `State` → `Supplier SKU`; 17 data items (all Sum).

**14 slicers**, all cutting the pivots: `OD, OM, OY` (order day/month/year), `PD1, PM2, PY2` (payment day/month/year), `OM1, OY1` (second copies), `Live Order Status 2`, `Claim Status`, `Compansation Type`, `Recovery Type`, `Overcharged`, `Courier Company`. The OD/OM/OY & PD/PM/PY slicers work because the vendor **materializes date parts as text columns** (AT:AY) in the data.

### B.4 VBA project (all code extracted; ~2,500 effective lines)

| Module | Kind | Role |
|---|---|---|
| `UpdateData.bas` | std | `ImportBackup` (auto-import newest file in `Backup\`), `UpdateNewData` (file-picker variant), `ClearAllAndUpdate`, kiosk mode `hd`/`sd`, `SHcmdUpdate` (Ctrl+Shift+M reveals update button), `Whatsapp`, `SalesClick`, `Sales_Format`, `Calci` (opens ProfitCalculator), `Create_Extra_Charge_Sheet` (Ctrl+Shift+E: pivot drill-through → strip columns → save "Extra Charge.xlsx") |
| `Pivot.bas` | std | `DataSourceSelection` (repoint both pivots at `Payment!A2.CurrentRegion`; set B2/B4 = MIN/MAX of `Payment!BB:BB` order date), `AdvanceFilter_Data` (date-range extract to Temp, repoint pivots at Temp), `AdvanceFilter_Data2` (TotalPayment-range extract, with validity check), `RefreshAll`/`Refresh_AnalysisReport` (clear slicers + filters), `CollapseAll`/`ExpandAll` (drill Supplier SKU ↔ Sub Order No), `SortAtoZ`, `ImageLocation2` (repositions 33×2 sort buttons over pivot columns), `Format_AR` |
| `Report111.cls` | Analysis Report sheet | `CalculationOfPivot` (KPI computation on every pivot update — Section D.4), 33 pairs of Up/Down sort handlers, calendar hooks for B2/B4, double-click drill-to-detail with column cleanup, button handlers |
| `Report1211.cls` | Region sheet | empty (Region has no bespoke interactivity) |
| `Sales.cls` | Sales sheet | `cmdPending_Click`: filter C="Pending" AND D∈{DELIVERED, SHIPPED} (money Meesho owes but hasn't settled); `cmdViewAll_Click` |
| `Sheet3.cls` | Update Data sheet | `cmdUpdate_Click` → manual-calc guard → `ImportBackup` → re-hide button |
| `ThisWorkbook.cls` | — | On open: kiosk mode, jump to Update Data, hide update button, hide pivot field list |
| `Calendar.frm` | form | Month/year date-picker writing into B2/B4 |
| `UserForm1.frm` | form | Two-value form → Temp!C2/D2 (payment range, ordered) |
| `ProfitCalculator.frm` | form | Pricing what-if: `RequiredPrice = (ReturnQty × ReturnCharge)/DeliveredQty + ProductCost + Ads + Profit` (defaults 10 × ₹180 / 100 + cost + ₹1 + ₹50) |
| `Report12/Report11/Report121/Report1/Report/Sheet1/Sheet2/Payment` | orphans/empty | Leftovers from older versions (incl. a State-pivot dashboard variant) |

**No** Power Query, no data connections, no external workbook links, no charts, no data validation. 179 ActiveX controls (buttons/images), 5 drawings, 2 threaded comments.

The workbook's own documentation (threaded comment on `B12` of both dashboards, by "haresh makani", 2024-03-12):
> **DTO = (Return + Exchange) × 100 / (Total Order − RTO)**

---

## C. Data Flow

```
[Meesho Supplier Panel downloads]                        (raw, seller-provided)
   ├─ Payment file(s):  {supplierId}_SP_ORDER_ADS_REFERRAL_PAYMENT_FILE_
   │                    PREVIOUS_PAYMENT_{from}_{to}.xlsx
   ├─ Orders export(s): Orders_{d1}_{d2}_{d3}...(.xlsx/.csv)
   ├─ Returns data      (courier per return — inferred source)
   └─ Claims data       (claim status — inferred source)
              │
              ▼
[VENDOR'S UPSTREAM WORKBOOK / PROCESS]  ◄── NOT PRESENT IN THIS FILE
   • merges all payment files (FileName column tags provenance)
   • joins orders + returns + claims by Sub Order No
   • joins SKU cost master (PP-format) by cleaned SKU (SubstituteSKU)
   • applies courier rate card (S.Charge2 / RS.Charge2)
   • computes the ~50 derived columns (Section E logic)
   • writes result file into  <client folder>\Backup\
              │  Payment sheet: header row 2, data A3:ZZ…
              │  Sales sheet:   data C2:BZ…
              ▼
[THIS WORKBOOK — "Update Data" button → ImportBackup]
   1. Clear Payment & Sales sheets
   2. Find newest file under Backup\ (by creation date, recursive)
   3. Copy source Payment!A2:ZZ{lr}  → Payment!A2   (values only)
   4. Copy source Sales!C2:BZ{lr}   → Sales!A2      (values only)
   5. Set Payment very-hidden; close source without saving
   6. DataSourceSelection:
        both pivots ← Payment!A2.CurrentRegion
        'Analysis Report'!B2 = MIN(Payment!BB:BB)   (order-date from)
        'Analysis Report'!B4 = MAX(Payment!BB:BB)   (order-date to)
   7. Payment header row → Temp!A4 (Advanced-Filter header)
   8. Sales: F1=SUBTOTAL(9,A:A), I1=SUBTOTAL(9,I:I), date format, autofilter
              │
              ▼
[INTERACTIVE LAYER]
   • Date-range filter: calendar → B2/B4 → AdvanceFilter_Data:
       Temp criteria "Order Date" ≥B2 ≤B4 → AdvancedFilter copy
       Payment!A2:CG → Temp!A4:CG… → pivots repointed at Temp extract
   • Payment-range filter: UserForm1 → Temp C2/D2 → AdvanceFilter_Data2
   • 14 slicers; Up/Down per-column pivot sorting; SKU⇄SubOrder drill
   • Reset: DataSourceSelection (back to full Payment table)
              │
              ▼
[OUTPUTS]
   • Analysis Report grid (SKU × 35 measures)  + VBA KPI textboxes
   • Region grid (State × 17 measures)
   • Sales "Pending" view (delivered/shipped but unpaid)
   • Ctrl+Shift+E / double-click: drill-through detail exported
     as "Extra Charge.xlsx" (rate-dispute evidence file)
```

Note: `AdvanceFilter_Data` filters only columns A:CG (85 of 116) into Temp — the date-filtered pivot therefore loses columns CH:DL (incl. TCS/TDS/Claims/Recovery/Ads). The full-table view via `DataSourceSelection` has all 116. This is a real quirk of the original, visible in `Pivot.bas`.

---

## D. Formula & Calculation Logic

### D.1 The hidden Payment table — column dictionary & verified derivations

Header row 2; data rows 3…43,492. Roles: **[M]** = Meesho raw passthrough, **[V]** = vendor-computed, **[C]** = config/constant, **[H]** = empty helper.

**Vendor block (A:AZ):**

| Col | Header | Role | Derivation (as verified against all 43,490 rows) | Grade |
|---|---|---|---|---|
| A | `cSKid` | V | Running occurrence counter of `Id + Sku` (1 for first occurrence, 2 for second, …). Ads rows share one key, reaching 372. | PROVEN |
| B | `P.Count` | V | ≈ `Total Order` × (TotalPayment ≠ 0) — "orders with money movement". Denominator of *Avg Return Charges*. | VERIFIED ~97.9% |
| C | `TotalPayment` | V | **= SUM(`Final Settlement Amount` BL) over all rows of the same `Sub Order No`** (group total repeated on every row of the group) | PROVEN 100% |
| D | `Total Sales2` | V | **= BN + BO** (sale amount + sale-return amount = net sale of the row) | PROVEN 100% |
| E | `Final Return Charges` | V | **= CY (`RS.Charge2`) if CY ≠ 0, else CB (`Return Shipping Charge (Excl. GST)`)** — i.e. Meesho's charged return fee, replaced by the rate-card-corrected value where the vendor computed one | PROVEN 100% |
| F | `Overcharged` | V | `"Yes"` ≈ CY ≠ 0 **or** (CZ ≠ 0 and CD < CZ) — flagged when charged shipping exceeds the rate-card expectation (3,524 rows) | VERIFIED ~97% |
| G | `Courier Company` | V | Present only on return-type rows (PocketShip, Shadowfax, Valmo, Delhivery, Ecom Express, Xpress Bees, BlueDart; `NA` otherwise). **Not derivable from the payment or orders file** → joined from returns data upstream | INFERRED (source UNKNOWN) |
| H | `Emty` | H | 0 | PROVEN |
| I–K | `H4 H5 H6` | H | header-only, empty | PROVEN |
| L | `Meesho GST Credits` | V | **Input-GST credit on Meesho's fees.** Normal rows: `= −(BL − (BN+BO) − TCS − TDS − Compensation − Claims − Recovery) × 18/118` (fees are *derived from the settlement equation*, then the 18% GST slice is taken). Ads rows: `= −DE` (GST from ads file). | PROVEN 100% both branches |
| M | `Purchase Gst Credit` | V | `= AE (Purchase) × AN (Purchase GST %)` — zero for this client (AN=0) | PROVEN 100% |
| N | `Sales Gst Debit` | V | `= −(BN+BO) × BG/(100+BG)` — output GST owed on the net sale | PROVEN ~98.7% (residual = ads rows, 0) |
| O | `Available GST Credit` | V | `= L + M + N` (net GST position; negative = GST payable exceeds credits) | PROVEN 100% |
| P | `Total Order` | V | Count of order-journeys for the sub-order, stamped on its **first** payment row (0 on repeats). Usually 1; **2 on 497 exchange/replacement journeys**. Σ = 40,994 = dashboard order count | VERIFIED ~98.7% (exact rule for the 497 needs orders raw data) |
| Q | `Lost Qty` | V | 1 when corrected status = Lost (22 rows) | VERIFIED ~99.9% |
| R | `Recovery Qty` | V | 1 when `Recovery Type` ≠ NA | VERIFIED ~96.8% |
| S | `Cancelled` | V | `Total Order` × (Status2 = Cancelled) | PROVEN 100% |
| T | `Claim Qty` | V | 1 when `Claim Status` = Approved | VERIFIED ~97.4% |
| U | `Exchange` | V | one-hot of Status2 = Exchange | VERIFIED ~99.99% |
| V | `Delivered` | V | one-hot × TotalOrder of Status2 = Delivered (+ delivered leg of exchange journeys) | VERIFIED ~98% |
| W | `Customer Return` | V | one-hot of Status2 = Return | VERIFIED ~99.8% |
| X | `RTO` | V | one-hot of Status2 = RTO | VERIFIED ~99.1% |
| Y | `D+R+C` | V | ≈ Delivered + Customer Return + Exchange ("units that physically reached a customer") — drives purchase recognition | VERIFIED ~91% (edge cases around exchange/claims) |
| Z | `Live Order Status 2` | V | **Corrected status**: starts from BF (`Live Order Status`), reclassified using payment evidence (964 rows Delivered→Return, adds Lost, resolves blanks/Shipped/Cancelled inconsistencies) | INFERRED (rules partially recoverable only with raw returns data) |
| AA | `Recovery Type` | M/V | passthrough of payment-file recovery reason (`MEESHO_SMART_COIN_FEE`, `Affiliate Fee`, penalty texts, …), `NA` default | PROVEN |
| AB | `Compansation Type` | M/V | passthrough of compensation reason, `NA` default | PROVEN |
| AC | `State` | V | Customer state — **joined from Orders data** (payment file has no state; Sales col J does) | INFERRED |
| AD | `Claim Status` | V | `NA` / Approved / Open / Rejected — **from claims/ticket data** (not in payment or orders file) | INFERRED (source UNKNOWN) |
| AE | `Purchase` | V | **Recognized COGS** `= AK × (Delivered + Customer Return + Exchange)` — purchase cost is charged to P&L only for units that reached the customer (RTO/Cancelled recover the stock ⇒ no cost) | VERIFIED ~97% |
| AF | `Shipping Diff` | V | Recoverable shipping delta. Forward branch: `= CZ − CD` where CZ ≠ 0 and CD < CZ. Also populated (rate-value amounts) on some Return rows. Σ = 333,518 | VERIFIED ~95% (return-side branch partially determined) |
| AG | `Profit Loss With Gst` | V | `= AH + O` | PROVEN ~99.1% (ads rows excepted) |
| AH | `P/L` | V | **`= BL (Final Settlement Amount) − AE (Purchase)`** — the core row P&L | PROVEN 100% |
| AI, AJ | `H2 H3` | H | empty | PROVEN |
| AK | `Total Purchase Cost` | V | `= unit_cost(SubstituteSKU) × BI (Quantity)`; unit cost is constant per SKU (120 SKUs in data; e.g. ₹146 for the main SKU) — from the SKU cost master | PROVEN (unit-cost table = raw-data requirement) |
| AL | `Weight Slab` | C | `"Upto 500gm"` on every row — client-level config | PROVEN |
| AM | `Product Na` | V | 0 except `Ads Cost` / `Referral Payments` labels on non-order rows | PROVEN |
| AN | `Purchase GST %` | C | 0 for all order rows (client buys without GST invoice); 0.18 stamped on ads rows | PROVEN |
| AO | `Return Loss %` | C? | **0.5 exactly on the 372 ads rows, 0 elsewhere** (Σ=186 = dashboard "Return Loss") | PROVEN value; semantics UNKNOWN |
| AP | `RTO Packaging Loss` | C? | **14.0 exactly on the 372 ads rows, 0 elsewhere** (Σ=5,208) | PROVEN value; semantics UNKNOWN |
| AQ | `SubstituteSKU` | V | SKU with characters sanitized (`-`→`_` etc.) — join key to cost master | PROVEN |
| AR | `Ok` | V | `"Paid"` on all rows (payment-status partition; first row-field of both pivots) | PROVEN |
| AS | `Total Sales` | V | `= SUM(D) per Sub Order No`, stamped on first row (net sale value of the order); Σ = 7,336,672 = dashboard "Net Sales" | VERIFIED ~97.4% |
| AT–AY | `OD PD OM PM OY PY` | V | Text date parts of Order/Payment date: day `"27"`, month `"Feb"`, year `"2025"` — slicer fodder | PROVEN |
| AZ | `Id + Sku` | V | `"{Sub Order No} | {SKU}"` composite key | PROVEN |

**Meesho payment-file passthrough block (BA:DJ)** — these are the exact column names of Meesho's *Previous Payments* workbook ("Order Payments" sheet), and constitute the raw-file schema you must supply:

| Cols | Headers |
|---|---|
| BA–BM | `Sub Order No`, `Order Date`, `Dispatch Date`, `Product Name`, `Supplier SKU`, `Live Order Status`, `Product GST %`, `Listing Price (Incl. GST & Commission)`, `Quantity`, `Transaction ID`, `Payment Date`, `Final Settlement Amount`, `Price Type` |
| BN–BU | `Total Sale Amount (Incl. Commission & GST)`, `Sale Return Amount (Incl. GST)`, `Fixed Fee (Incl. GST)`, `Warehousing fee (inc Gst)`, `Shipping Revenue (Incl. GST)`, `Shipping Return Amount (Incl. GST)`, `Return premium (incl GST)`, `Return premium (incl GST) of Return` |
| BV–CG | `Meesho Commission Percentage`, `Meesho Commission (Excl. GST)`, `Meesho gold platform fee (excl GST)`, `Meesho mall platform fee (excl. GST)`, `Fixed Fee (excl. GST)`, `Warehousing fee (excl Gst)`, `Return Shipping Charge (Excl. GST)`, `GST Compensation (PRP Shipping)`, `Shipping Charge (Excl. GST)`, `Other Support Service Charges (Excl. GST)`, `Waivers (Excl. GST)`, `Net Other Support Service Charges (Excl. GST)` |
| CH–CO | `GST on Meesho Commission`, `GST on Warehousing fee`, `GST on meesho gold`, `GST on Meesho Mall platform fee`, `GST on Shipping Charge` *(header carries both old & new spellings — the vendor's ETL handles two Meesho file generations)*, `GST on Return Shipping Charge`, `GST on Net Other Support Service Charges`, `GST on Fixed Fee` |
| CP–CX | `TCS`, `TDS Rate %` (=0.1), `TDS`, `Compensation`, `Claims`, `Recovery`, `Compensation Reason`, `Claims Reason`, `Recovery Reason` |
| CY–DL | Vendor extras: `RS.Charge2` (rate-card corrected return charge), `S.Charge2` (rate-card expected forward charge), `HNA4`×4 (0), `GST` (Σ of the CH:CO columns where present; ads GST), `0` (placeholder), `Total Ads Cost` (= BL on ads rows; Σ −168,111), `Net Referral Amount` (0 here), `Reason` (0), `FileName` (source Meesho file name), `HNA5`, `HNA6` (empty) |

Non-order rows: 372 "Ads Cost" rows (ads invoices from the ads section of the payment file, tagged via pseudo-SKU) carry `Total Ads Cost`, ads GST (DE/L), and the AO/AP constants.

### D.2 Pivot calculated fields (decoded from binary cache, exact)

```
Avg Settlement        = 'Final Settlement Amount' / ('Delivered' + 1)
Final PL              = 'P/L' + 'Total Ads Cost' + 'Net Referral Amount'
                        + 'Return Loss %' + 'RTO Packaging Loss'
Final PL with GST     = 'Final PL' + 'Available GST Credit'
Avg Final PL with GST = IF('Total Order' − 'RTO' > 0,
                           'Final PL with GST' / ('Total Order' − 'RTO'),
                           'Final PL with GST' / 'Total Order')
Avg Return Charges    = ('Final Return Charges' + 'Return Loss %'
                         + 'RTO Packaging Loss') / 'P.Count'
Return %              = ('Exchange' + 'Customer Return')
                        / ('Customer Return' + 'Delivered' + 'Exchange')
```
(Verified against the grand-total row: 1,313,398 − 168,111 + 0 + 186 + 5,208 = 1,150,681 = Final P&L shown ✓; 1,150,681 − 730,525 = 420,156 = Final PL with GST ✓.)

### D.3 Analysis Report grid layout (row 11 captions = pivot data items, all Sum)

| Grid col | Caption | Source field |
|---|---|---|
| D | row labels | Ok → Supplier SKU → Sub Order No → Transaction ID |
| E | Net Sales | `Total Sales` |
| F | Sum of Final Settlement Amount | `Final Settlement Amount` |
| G / H / I | Recovery Amt / Claims Amt / Compensation Amt | `Recovery` / `Claims` / `Compensation` |
| J | Gross Profit or Loss | `P/L` |
| K | Purchase | `Purchase` |
| L–R | Total Order / Delivered / RTO / Customer Return / Exchange / Cancelled / Recovery Qty | counters |
| S / T | TCS / TDS | `TCS` / `TDS` |
| U | Claim Qty | `Claim Qty` |
| V | Profit/Loss With Gst | `Profit Loss With Gst` |
| W / X | Ads Cost / Referral Amount | `Total Ads Cost` / `Net Referral Amount` |
| Y / Z / AA / AB | Meesho GST Credits / Purchase Gst Credit / Sales Gst Debit / Available GST Credit | GST block |
| AC / AD | Shipping Charge (Excl.GST) / Return Charges | `Shipping Charge` / `Final Return Charges` |
| AE | Avg Settlement | calc field |
| AF / AG | Return Loss / RTO Packaging Loss | `Return Loss %` / `RTO Packaging Loss` |
| AH / AI / AJ / AK | Final P & L / Final PL with GST / Avg Final PL with GST / Avg Return Charges | calc fields |
| AL | Shipping Diff | `Shipping Diff` |
| AM | Avg Final PL without GST | **sheet formula**, see D.5 |

Region grid: D = Ok→State→SKU labels; E:U = Total Sales, Settlement, Recovery Amt, Claims Amt, Compensation Amt, Gross P/L, Purchase, Total Order, Delivered, RTO, Customer Return, Exchange, Cancelled, Recovery Qty, Claim Qty, Shipping Charge, Return Shipping Charge.

### D.4 VBA KPI panel (`CalculationOfPivot`, fires on every pivot update; row 12 = grand totals)

```
P&L            = F12 + W12 + X12 − K12   (Settlement + Ads + Referral − Purchase)
Bank Received  = F12 + W12 + X12
TCS+TDS        = S12 + T12
Ads/Order      = W12 / (L12+1)
Avg Sales      = E12/L12 (+1 guards)     Avg Settlement = F12 / (L12−N12+1)
Avg Dispatch   = (J12+W12) / (L12+1)     P&L/Delivered  = J12 / (L12−N12+1)
Delivered %    = M12/(L12+1)             RTO %          = N12/(L12+1)
CustReturn %   = O12/(L12−N12−Q12+1)     Exchange %     = P12/(L12−N12−Q12+1)
GST Credit     = AB12
Profit/Loss label & red/green coloring by sign; "% by Sales" = P&L/E12;
"% by Settlement" = P&L/(F12+H12)  (settlement + claims)
```

### D.5 Worksheet formulas (shared-formula masters, decompiled from binary)

On both dashboards, left of the pivot (per visible pivot row):
```
A: =IFERROR(N{r}/L{r}, "")                         'RTO %   (RTO / Total)
B: =IFERROR((O{r}+P{r})/(L{r}-N{r}), "")           'DTO %   ((CustReturn+Exchange)/(Total−RTO))
C: =IFERROR(IFERROR(J{r}/(L{r}-N{r}), J{r}/L{r}),0)'Avg Gross P/L per delivered order
AM (Analysis Report only):
   =IFERROR(IFERROR(AH{r}/(L{r}-N{r}), AH{r}/L{r}), 0)  'Avg Final P&L per delivered order
Region!B2 = 'Analysis Report'!B2      Region!B4 = 'Analysis Report'!B4
```

Temp staging formulas:
```
A1:B1 = "Order Date"            A2 = ">="&'Analysis Report'!B2   B2 = "<="&'Analysis Report'!B4
C1:D1 = "TotalPayment"          C2 = ">="&E1                     D2 = "<="&F1
E1 = 'Analysis Report'!C2       F1 = 'Analysis Report'!D2        G1 = IF(E1-F1<0,"Yes","No")
```

Sales totals: `F1 = SUBTOTAL(9, A3:A1048576)` (CostPrice sum), `I1 = SUBTOTAL(9, I3:I1048576)` (Quantity sum) — respond to the autofilter.

### D.6 Sales sheet columns

| Col | Header | Content |
|---|---|---|
| A | `CostPrice` | vendor col — all 0 for this client (unused) |
| B | `Orderes` | vendor col — 1 unless cancelled (order counter) |
| C | `Payment Status` | vendor col — **number = TotalPayment of the sub-order** (settled), `"Pending"` (no payment row yet), `"Cancel"` (cancelled). Snapshot of an upstream XLOOKUP against Payment |
| D | `Reason for Credit Entry` | Meesho order status: DELIVERED / CANCELLED / SHIPPED / RTO_COMPLETE / RTO_LOCKED / READY_TO_SHIP / PENDING / RTO_INITIATED / DOOR_STEP_EXCHANGED / RTO_DELIVERY_FAILED |
| E–N | Meesho Orders export: `Sub Order No`, `Order Date`, `SKU`, `Size`, `Quantity`, `Customer State`, `Product Name`, `Supplier Listed Price (Incl. GST + Commission)`, `Supplier Discounted Price (Incl GST and Commission)`, `Packet Id` |
| O | `FileName` | source orders file (e.g. `Orders_2025-02-21_2025-02-28_…`) |
| P | placeholder 0 |

"Pending Payment" button = filter C="Pending" AND D∈{DELIVERED, SHIPPED} → **orders delivered/shipped but not yet paid by Meesho** (9,313 pending rows in snapshot).

---

## E. Reconciliation Logic (business view)

1. **Settlement decomposition (per payment row).** Meesho's settlement identity is
   `BL = (BN+BO) − fees(incl GST) + TCS + TDS + Compensation + Claims − Recovery ± waivers`.
   The vendor does not trust per-fee columns (older files lack them); instead it **back-solves total fees** from that identity and extracts the GST-credit slice at 18/118 (column L). PROVEN exact.
2. **Taxes.** `TCS = −0.5% × taxable value` and `TDS = −0.1% × taxable value`, where taxable = `(BN+BO)/(1+GST%/100)`. PROVEN exact — these come from the raw file but the identity confirms the columns' meaning and provides a recomputation path.
3. **GST position.** Output GST on net sale (N) vs input credits on Meesho fees (L) and purchases (M): `Available GST Credit = L + M + N`; negative means net GST payable. Rolled into `Final PL with GST`.
4. **Purchase recognition.** COGS (`AE`) accrues only for units that reached the customer (Delivered + Customer Return + Exchange). RTO/Cancelled units return to stock at zero cost. (A customer *return* still costs the product? — yes per this logic; the vendor treats DTO returns as lost stock value. This is a policy choice baked into the model.)
5. **Row P&L.** `P/L = Settlement − recognized COGS`. Everything else (ads, referral, GST, loss allowances) enters at the *pivot* level via `Final PL` and `Final PL with GST`.
6. **Return-charge audit ("Overcharged").** The vendor maintains a courier rate card (recovered empirically: forward expectation ~₹71–92 by courier, return expectation ~₹150–165). Where Meesho's charged `Return Shipping Charge` exceeds the card, `RS.Charge2` holds the corrected value and `Final Return Charges` uses it; where forward `Shipping Charge` < expected (`S.Charge2`), or return charge exceeds the cap, the row is flagged `Overcharged = "Yes"` and `Shipping Diff` accumulates the recoverable delta (₹333,518 in snapshot — the "Extra Charge.xlsx" export exists to dispute exactly this with Meesho/the vendor's rate desk).
7. **Ads & referral.** Ads-cost rows from the payments file become pseudo-orders (SKU "Ads Cost") carrying `Total Ads Cost` (= their settlement, negative), ads GST credit, and the AO/AP flat allowances; they flow into `Final PL` at pivot level.
8. **Claims / Compensation / Recovery.** Amounts pass through from the payment file (columns CS/CT/CU with reasons); `Claim Qty` counts approved claims (needs claims raw data to fully confirm status sourcing).
9. **Order-journey counting.** `Total Order` counts order-file journeys per sub-order (497 exchange journeys count twice); status one-hots (`Delivered`, `RTO`, `Customer Return`, `Exchange`, `Cancelled`, `Lost`) are derived from the **corrected** status (`Live Order Status 2`), which reconciles the order status against payment evidence (e.g. "Delivered" with a return-shipping charge ⇒ Return; missing/blank ⇒ Lost/Shipped resolution).
10. **Payment completeness (Sales side).** Every order row is marked settled (amount) / Pending / Cancel — surfacing **delivered-but-unpaid** orders, the second recoverable-money report.

---

## F. Business Rules (consolidated)

BR-01 A sub-order's total payment is the sum of *all* its settlement transactions (multiple transactions per sub-order are normal — forward payment, return adjustment, claim credit…). [PROVEN]
BR-02 Net sale of a row = sale amount + sale-return amount; net sale of an order = Σ rows. [PROVEN]
BR-03 An order "counts" once (twice if a replacement journey), on its first payment row only — prevents double counting across settlement transactions. [VERIFIED]
BR-04 Order outcome is the corrected status, not Meesho's raw status. [INFERRED rules]
BR-05 COGS is recognized only for Delivered + Customer Return + Exchange units. [VERIFIED ~97%]
BR-06 Row Gross P&L = settlement − recognized COGS. [PROVEN]
BR-07 Final P&L = Gross P&L + Ads + Referral + Return-loss allowance + RTO-packaging allowance (allowances currently flat 0.5/14 per ads row for this client). [PROVEN formula]
BR-08 GST credit on Meesho fees = 18/118 of fees derived from the settlement identity (fallback: explicit GST columns when the file provides them). [PROVEN]
BR-09 Output GST = GST%/(100+GST%) of net sale, negative sign (liability). [PROVEN]
BR-10 Net GST position = fee credits + purchase credits − output GST; added to Final P&L for the "with GST" view. [PROVEN]
BR-11 TCS 0.5%, TDS 0.1% of taxable value. [PROVEN]
BR-12 Return shipping charged above the courier rate card is replaced by the card value and flagged; forward shipping below expectation is flagged; the difference is tracked as recoverable. [VERIFIED ~95–97%]
BR-13 Delivered/Shipped orders with no settlement = "Pending" money owed by Meesho. [PROVEN]
BR-14 DTO rate = (Return + Exchange)/(Total − RTO); RTO rate = RTO/Total; averages divide by delivered (Total − RTO) with fallback to Total. [PROVEN — vendor's own comment + formulas]
BR-15 Ads/referral spend enters P&L as pseudo-order rows, not as a separate report. [PROVEN]
BR-16 Suggested selling price = cost + ads/unit + target profit + return-cost amortization (ReturnQty×ReturnCharge/DeliveredQty — default 10×₹180/100 = ₹18/unit). [PROVEN — ProfitCalculator]

---

## G. Dependency Map

```
RAW (to be provided)                UPSTREAM VENDOR COLUMNS                 PIVOT / DASHBOARD
─────────────────────               ────────────────────────                ─────────────────
Payment file (BA:DJ) ─┬─▶ C TotalPayment ──────────────┬─▶ F Settlement col
                      ├─▶ D TotalSales2 ─▶ AS TotalSales┼─▶ E Net Sales
                      ├─▶ N SalesGstDebit ─┐            │
                      ├─▶ L MeeshoGSTCred ─┼─▶ O AvailGST ─▶ AB → AI FinalPL+GST
                      ├─▶ TCS/TDS cols ────┘            │
                      ├─▶ CS/CT/CU Claims/Comp/Recovery ┼─▶ G,H,I
                      └─▶ ads rows ─▶ DG TotalAdsCost ──┼─▶ W Ads Cost ─┐
Orders file ──┬─▶ P TotalOrder ─▶ counters S,U,V,W,X ───┼─▶ L..R counts │
              ├─▶ AC State (join) ──────────────────────┼─▶ Region rows │
              └─▶ Sales sheet + C PaymentStatus lookup  │               │
Returns data ─┬─▶ G Courier ─▶ rate card ─▶ CY,CZ ─▶ E FinalRetChg ─▶ AD│
              └─▶ Z Status2 corrections                 │  F Overcharged│
Cost master ──▶ AK TotalPurchCost ─▶ AE Purchase ─▶ AH P/L ─▶ J ─▶ FinalPL (calc fld)
                                        ▲               │       ▲       │
Claims data ──▶ AD ClaimStatus ─▶ T ClaimQty ───────────┘       └── W,X,AF,AG ← ads/allowances
Rate card ────▶ CZ/CY ─▶ AF ShippingDiff ─▶ AL

Order of computation: passthrough → joins (orders/returns/claims/cost) → group keys
(AZ, first-row flags A/B/P) → status correction (Z) → counters → money identities
(C,D,L,M,N,O) → P&L (AE→AH→AG) → shipping audit (CY/CZ→E,F,AF) → date parts →
pivot calc fields → dashboard formulas/KPIs.
Independent branches: GST block, shipping audit, and counters can compute in parallel;
everything downstream of Z depends on the status correction.
```

---

## H. Unknowns (cannot determine from this workbook alone)

1. **The upstream workbook/process itself** — its formulas were reconstructed empirically here, but the actual implementation (VBA? another xlsb? operator steps, run order, dedupe rules across overlapping payment files) is not in this file.
2. **Courier assignment (G)** — which raw file/column supplies the courier per sub-order (returns report? AWB/tracking join?).
3. **The canonical courier rate card** — recovered *values* per courier (forward ~₹71–92, return ~₹150–165, incl. paise variants suggesting a formula, e.g. base+GST or zone factors), but not the card itself, its weight-slab axis (only "Upto 500gm" appears), zone logic, or effective-date versioning.
4. **`Live Order Status 2` correction rules** — the reclassification logic (964 Delivered→Return, Lost detection, Shipped resolution at cutoff) needs returns raw data to pin down.
5. **Exact semantics of `Return Loss %` (0.5) and `RTO Packaging Loss` (₹14)** stamped on ads rows — config knobs, period-level allowances, or prorated estimates? Vendor intent unclear.
6. **`P.Count` and `Total Order` edge rules** for the 497 double-counted journeys and zero-settlement rows (~2% residuals).
7. **Claims sourcing** — where Approved/Open/Rejected comes from.
8. **Sales `Payment Status` refresh timing** — values are a snapshot; 12,890 match current TotalPayment exactly, the rest drifted (older snapshot) or follow an additional rule.
9. **Multi-quantity orders** — every row in this dataset has Quantity = 1; behavior for qty > 1 is unverified.
10. **`Net Referral Amount` handling** — 0 for this client; the referral branch is untested by the data.
11. Minor: conditional-formatting rule formulas (8–9 cosmetic rules per dashboard), ActiveX button imagery.

---

## I. Raw Data Requirements (to rebuild & validate)

### 1. Meesho Payments file(s) — *the* primary input
Supplier Panel → Payments → **Previous Payments** download, e.g.
`1260895_SP_ORDER_ADS_REFERRAL_PAYMENT_FILE_PREVIOUS_PAYMENT_2025-03-01_2025-03-30.xlsx`
— **every file covering the full analysis window** (they are month/window-scoped; the FileName column shows ~dozens were merged).
Required sheets/sections: **Order Payments** (all columns BA:CX above — Sub Order No, dates, status, price/qty, Transaction ID, settlement, sale amounts, every fee & GST column, TCS/TDS, Compensation/Claims/Recovery + reasons), **Ads Cost**, **Referral Payments**, and any Compensation/Recovery detail sheets.
Used for: settlement totals (C), net sales (D/AS), GST engine (L/N/O), taxes, claims/recovery/compensation amounts, ads cost, and the payment-date dimension.

### 2. Meesho Orders export(s)
`Orders_*.csv/xlsx` covering the same window (all files).
Required columns: Reason for Credit Entry, Sub Order No, Order Date, SKU, Size, Quantity, Customer State, Product Name, Supplier Listed Price, Supplier Discounted Price, Packet Id.
Used for: order universe & journey counting (P/Total Order), State (AC), Sales sheet, pending-payment report, cancellations.

### 3. Meesho Returns / RTO report
The export that lists returns with **courier partner** per sub-order (and return type DTO/RTO, dates, AWB).
Used for: Courier (G), status correction (Z), return-charge audit context. *This is the file I could not see — its exact filename/columns from your panel are needed.*

### 4. Claims / Tickets export (if you use it)
Whatever the vendor used for `Claim Status` (Approved/Open/Rejected) — possibly the compensation section of the payments file or the support-ticket export.

### 5. SKU cost master (you own this)
Per SKU: product cost, packaging cost, purchase GST % + "cost includes GST?" flag, and the SKU→SubstituteSKU cleaning convention (PP sheet format: `SKU, Product Name, Selling GST %, Date, Product Cost, Pakaging Cost, GST %, Is Product Cost With GST ?, Total Tax, Total Cost, Order ID, Substitute SKU`).
Used for: AK → AE → every P&L number.

### 6. Courier rate card + weight slabs
Expected forward & return shipping per courier × weight slab (× zone if applicable), plus each SKU's weight slab.
Used for: CY/CZ → Final Return Charges, Overcharged, Shipping Diff.

### 7. Config constants
TCS % (0.5), TDS % (0.1), fee-GST fraction (18/118), ads GST %, the AO/AP allowances (0.5 / ₹14), client GST setup.

### 8. (Ideal) One upstream "Backup" processed file
Any one of the vendor-produced files from your `Backup\` folder. With it, every remaining INFERRED item becomes checkable by direct diff.

---

## J. Clone Specification (Python)

**Goal:** reproduce the Payment table (116 cols), the two pivot reports, the KPI set, and the exception exports — from raw Meesho files, no Excel dependency in the engine.

```
meesho_recon/
├── ingest/
│   ├── payments.py      # read every *PAYMENT_FILE*.xlsx: Order Payments + Ads + Referral
│   │                    #   sheets; normalize both header generations (old/new GST cols);
│   │                    #   tag FileName; concat + dedupe (SubOrderNo, TransactionID, FileName)
│   ├── orders.py        # read Orders_*.csv/xlsx; concat; dedupe by SubOrderNo+status row
│   ├── returns.py       # read returns/RTO export: courier, type, dates per SubOrderNo
│   ├── claims.py        # optional claims/ticket export
│   └── masters.py       # SKU cost master, courier rate card, config.yaml
├── normalize/
│   ├── sku.py           # SubstituteSKU cleaning (reproduce vendor char-substitutions)
│   ├── dates.py         # OD/OM/OY, PD/PM/PY parts; date parsing
│   └── schema.py        # canonical dtypes; sign conventions (deductions negative)
├── engine/
│   ├── keys.py          # Id+Sku, occurrence counters (cSKid), first-row flags
│   ├── status.py        # Live Order Status 2 correction (orders × payments × returns)
│   ├── counters.py      # TotalOrder, Delivered/RTO/Return/Exchange/Cancelled/Lost,
│   │                    #   D+R+C, P.Count, ClaimQty, RecoveryQty
│   ├── money.py         # TotalPayment (group sum), TotalSales2/TotalSales,
│   │                    #   purchase recognition AE=AK×(D+R+C), P/L=BL−AE
│   ├── gst.py           # SalesGstDebit, MeeshoGSTCredits (18/118 settlement-identity
│   │                    #   method + explicit-columns method), PurchaseGstCredit, AvailGST
│   ├── shipping.py      # expected charges from rate card (S.Charge2/RS.Charge2),
│   │                    #   FinalReturnCharges, Overcharged flag, ShippingDiff
│   ├── taxes.py         # TCS/TDS recompute & cross-check vs file values
│   └── ads.py           # ads/referral pseudo-rows, allowances (AO/AP)
├── reports/
│   ├── sku_report.py    # Analysis Report equivalent: groupby SKU (drill SubOrder/Txn),
│   │                    #   34 measures + 6 calculated measures + RTO%/DTO%/averages
│   ├── state_report.py  # Region equivalent: groupby State, 17 measures
│   ├── pending.py       # delivered/shipped & unpaid (Sales logic)
│   ├── overcharge.py    # "Extra Charge" export: disputed shipping rows w/ evidence cols
│   └── excel_out.py     # openpyxl writer: styled xlsx mirroring current layouts
├── validate/
│   └── golden.py        # regression harness vs THIS workbook's numbers (see below)
└── cli.py               # `recon run --client 1260895 --from 2024-12-11 --to 2025-07-26`
```

**Pipeline order** (matches Section G): ingest → normalize → join orders/returns/claims/cost → keys & first-row flags → status correction → counters → money & GST → shipping audit → P&L → aggregate reports → Excel/HTML out.

**Design decisions to carry over**
- Keep deductions negative end-to-end (matches Meesho files and every identity above).
- Aggregate first-row-stamped measures (TotalPayment, TotalOrder, AS) exactly as the vendor does, or better: compute at sub-order grain in a separate table and join — same totals, cleaner model. Flag any divergence in the validator.
- Support both Meesho payment-file generations (explicit GST columns vs derived 18/118) behind one interface — the concatenated `GST on Shipping Charge` header in this workbook proves both exist in the wild.
- Config file per client: TCS/TDS rates, GST fraction, allowances, weight slab, rate card, cost-includes-GST flag.
- Everything pure-pandas/polars; Excel only at the edges (ingest/report).

**Golden-file validation targets** (this snapshot, full window):
```
rows=43,490 · orders=40,994 · delivered=25,221 · RTO=13,492 · returns=2,281
exchange=202 · cancelled=135 · net_sales=7,336,672 · settlement=5,225,069.90
purchase=3,911,672 · gross_PL=1,313,397.90 · ads=−168,111.28 · TCS=−31,083.93
TDS=−6,201.77 · claims=184,651.40 · recovery=−31,887.68 · compensation=4,053.43
gst_credits=365,986.53 · sales_gst_debit=−1,096,511.19 · avail_gst=−730,524.66
return_charges=−373,187.36 · shipping_diff=333,518 · final_PL=1,150,680.62
final_PL_with_GST=420,155.96
```
A clone that reproduces these 25 numbers from the raw files has replicated the system.

---

## What I need from you next

Upload these, ideally as-downloaded (unedited), covering **the same period** (orders 11-Dec-2024 → 26-Jul-2025, payments through 31-Jul-2025) so results can be diffed against this workbook:

1. ☐ **All Meesho payment files** for the window: every `*_SP_ORDER_ADS_REFERRAL_PAYMENT_FILE_PREVIOUS_PAYMENT_*.xlsx` (and any `CURRENT_PAYMENT` variant you use) — with **all sheets** intact (Order Payments, Ads Cost, Referral Payments, Compensation/Recovery details).
2. ☐ **All Orders exports**: every `Orders_*.xlsx/csv` for the window.
3. ☐ **The Returns/RTO report** from the supplier panel (the export containing courier partner, return type, AWB per sub-order) — any date range sample is enough to identify its schema; full window preferred.
4. ☐ **Claims/support data** if you have it (or confirm claims info comes only from the payments file).
5. ☐ **Your SKU cost list**: SKU, product cost, packaging cost, GST% and whether cost includes GST (the PP-sheet format shown in Section I.5 is the template).
6. ☐ **The courier rate card** the vendor applies (forward + return charge per courier/weight slab), if you have it — otherwise I will fit it from the data, and flag rows where the fit is ambiguous.
7. ☐ **One processed "Backup" file** produced by the vendor (from the `Backup\` folder next to this workbook), if you can get one — this converts every remaining inference into a provable diff.
8. ☐ Confirm three config facts: (a) your purchases carry no GST input credit (AN=0 as in this data)? (b) weight slab "Upto 500gm" applies to all SKUs? (c) do you use Meesho ads/referral programs going forward (referral is 0 in this snapshot)?

With items 1, 2 and 5 alone I can rebuild ~90% of the system and validate it against the golden numbers above; items 3 and 6 close the shipping-audit module; item 7 removes all remaining guesswork.
