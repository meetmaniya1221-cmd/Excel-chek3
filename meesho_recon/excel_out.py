"""Excel writer -- produces a workbook laid out like the vendor's dashboards."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEAD_FILL = PatternFill("solid", fgColor="0B6B57")
HEAD_FONT = Font(name="Arial", size=9, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial", size=9)
TOTAL_FONT = Font(name="Arial", size=9, bold=True)
TOTAL_FILL = PatternFill("solid", fgColor="E3EFEA")
THIN = Side(style="thin", color="DDE2DD")
BORDER = Border(bottom=THIN)

MONEY_FMT = '#,##0.00;[Red](#,##0.00);-'
INT_FMT = '#,##0;[Red](#,##0);-'
PCT_FMT = '0.00%'
PCT_COLS = {"RTO %", "DTO %", "Return %"}
INT_COLS = {"Total Order", "Delivered", "RTO", "Customer Return", "Exchange",
            "Cancelled", "Recovery Qty", "Claim Qty", "P.Count"}


def _write_sheet(writer, name: str, df: pd.DataFrame, total_row: bool = True):
    if df is None or df.empty:
        return
    df.to_excel(writer, sheet_name=name[:31], index=False, startrow=1)
    ws = writer.sheets[name[:31]]

    for j, col in enumerate(df.columns, start=1):
        cell = ws.cell(row=2, column=j)
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        width = max(len(str(col)) + 2, 11)
        ws.column_dimensions[get_column_letter(j)].width = min(width, 34)

        fmt = PCT_FMT if col in PCT_COLS else INT_FMT if col in INT_COLS else MONEY_FMT
        if pd.api.types.is_numeric_dtype(df[col]):
            for i in range(len(df)):
                c = ws.cell(row=3 + i, column=j)
                c.number_format, c.font, c.border = fmt, BODY_FONT, BORDER
        else:
            for i in range(len(df)):
                c = ws.cell(row=3 + i, column=j)
                c.font, c.border = BODY_FONT, BORDER

    if total_row and len(df):
        r = len(df) + 3
        ws.cell(row=r, column=1, value="TOTAL").font = TOTAL_FONT
        ws.cell(row=r, column=1).fill = TOTAL_FILL
        for j, col in enumerate(df.columns, start=1):
            cell = ws.cell(row=r, column=j)
            cell.fill, cell.font = TOTAL_FILL, TOTAL_FONT
            if j > 1 and pd.api.types.is_numeric_dtype(df[col]) and col not in PCT_COLS:
                letter = get_column_letter(j)
                cell.value = f"=SUM({letter}3:{letter}{len(df) + 2})"
                cell.number_format = INT_FMT if col in INT_COLS else MONEY_FMT

    ws.freeze_panes = "B3"
    ws.auto_filter.ref = f"A2:{get_column_letter(len(df.columns))}{len(df) + 2}"


def write_report(path: Path, *, kpis: dict, sku: pd.DataFrame, state: pd.DataFrame,
                 suborder: pd.DataFrame | None = None,
                 overcharge: pd.DataFrame | None = None,
                 pending: pd.DataFrame | None = None,
                 exceptions: pd.DataFrame | None = None,
                 validation: pd.DataFrame | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        kdf = pd.DataFrame({"KPI": list(kpis), "Value": list(kpis.values())})
        _write_sheet(writer, "Summary", kdf, total_row=False)
        ws = writer.sheets["Summary"]
        for i, k in enumerate(kpis):
            c = ws.cell(row=3 + i, column=2)
            c.number_format = PCT_FMT if "%" in k else MONEY_FMT

        _write_sheet(writer, "SKU Report", sku)
        _write_sheet(writer, "State Report", state)
        if suborder is not None:
            _write_sheet(writer, "Sub Order Report", suborder)
        if overcharge is not None:
            _write_sheet(writer, "Extra Charge", overcharge)
        if pending is not None:
            _write_sheet(writer, "Pending Payments", pending, total_row=False)
        if exceptions is not None:
            _write_sheet(writer, "Exceptions", exceptions, total_row=False)
        if validation is not None:
            _write_sheet(writer, "Validation", validation, total_row=False)
    return path


# --------------------------------------------------------------------------
# Step 1 of the two-step flow: the SKU cost sheet the seller fills in.
# --------------------------------------------------------------------------

INPUT_FILL = PatternFill("solid", fgColor="FFF6D8")     # cells the seller edits
INPUT_FONT = Font(name="Arial", size=10, color="0000FF")
NOTE_FONT = Font(name="Arial", size=9, italic=True, color="5B6660")
TITLE_FONT = Font(name="Arial", size=13, bold=True, color="0B6B57")

COST_HELP = [
    "Fill the yellow Final Cost column for every SKU below, then send this file back.",
    "",
    "Final Cost   your total landed cost for ONE unit -- product, packaging and",
    "             anything else you spend to get it ready to ship, as a single",
    "             number. Nothing else to break out.",
    "",
    "Product Name / Orders / Delivered / Avg Settlement per Delivered come from",
    "your own data -- do not edit them. Rows are sorted by order volume, so the",
    "SKUs at the top move the profit number the most.",
    "",
    "Avg Settlement per Delivered is what Meesho actually paid you for one",
    "delivered unit, after its commission and fees. Your Final Cost must sit",
    "clearly below that number, because RTO and returns still have to be paid",
    "for out of the margin the delivered units earn.",
    "",
    "Leave a row blank only if you genuinely do not sell it; blank rows are",
    "reported as unpriced and their profit will be overstated.",
]


def write_cost_template(path: Path, skus: pd.DataFrame,
                        existing: dict[str, dict] | None = None) -> Path:
    """Write the fill-in-the-costs workbook.

    `skus` needs: sku, product_name, orders, delivered, avg_sale.
    `existing` pre-fills costs already known from an earlier round, so a seller
    who adds new SKUs next month only fills the new rows.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = existing or {}

    cols = ["SKU", "Final Cost", "Product Name", "Orders", "Delivered",
            "Avg Settlement per Delivered"]
    rows = []
    for _, r in skus.iterrows():
        prev = existing.get(str(r["sku"]), {})
        rows.append({
            "SKU": r["sku"],
            "Final Cost": prev.get("unit_cost", None),
            "Product Name": str(r.get("product_name", ""))[:70],
            "Orders": r.get("orders", 0),
            "Delivered": r.get("delivered", 0),
            "Avg Settlement per Delivered": r.get("avg_sale", 0),
        })
    df = pd.DataFrame(rows, columns=cols)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="SKU Costs", index=False, startrow=3)
        ws = writer.sheets["SKU Costs"]

        ws.cell(row=1, column=1,
                value="SKU Costs — fill the yellow Final Cost column and send back")
        ws.cell(row=1, column=1).font = TITLE_FONT
        ws.cell(row=2, column=1,
                value=f"{len(df)} SKUs from your uploaded data · "
                      "profit cannot be calculated until these are filled")
        ws.cell(row=2, column=1).font = NOTE_FONT

        widths = [30, 14, 54, 10, 11, 20]
        for j, (col, w) in enumerate(zip(cols, widths), start=1):
            c = ws.cell(row=4, column=j)
            c.fill, c.font = HEAD_FILL, HEAD_FONT
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(j)].width = w

        for i in range(len(df)):
            r = 5 + i
            for j in range(1, len(cols) + 1):
                c = ws.cell(row=r, column=j)
                c.border = BORDER
                if j == 2:                            # the one column the seller fills
                    c.fill, c.font = INPUT_FILL, INPUT_FONT
                    c.number_format = MONEY_FMT
                else:
                    c.font = BODY_FONT
                    if j in (4, 5):
                        c.number_format = INT_FMT
                    elif j == 6:
                        c.number_format = MONEY_FMT

        ws.freeze_panes = "A5"
        ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{len(df) + 4}"

        help_df = pd.DataFrame({"How to fill this sheet": COST_HELP})
        help_df.to_excel(writer, sheet_name="Instructions", index=False)
        hw = writer.sheets["Instructions"]
        hw.column_dimensions["A"].width = 96
        hw.cell(row=1, column=1).font = HEAD_FONT
        hw.cell(row=1, column=1).fill = HEAD_FILL
        for i in range(len(COST_HELP)):
            hw.cell(row=2 + i, column=1).font = BODY_FONT
    return path
