# Meesho Hisab

Meesho seller payments ka poora hisab — reverse-engineered from a third-party
Excel system (see `docs/REVERSE_ENGINEERING.md`), rebuilt in Python, and served
as a small web portal.

## Portal chalane ka tarika

```bash
pip install flask pandas openpyxl numpy
python run_portal.py            # -> http://localhost:8000
```

### Flow (3 steps)

1. **Upload** — client ka naam daal kar workspace banao, phir Meesho supplier
   panel ki files upload karo: payment zip/xlsx, `Orders_*.csv`, returns CSVs
   (completed/lost/in-transit/ofd), claims CSV. Zip ke andar zip bhi chalega.
2. **Cost sheet** — portal har SKU ki sheet deta hai; sirf yellow **Final Cost**
   column bharo (ek unit ka total landed cost) aur wapis upload karo.
   Agle mahine purani costs yaad rehti hain — sirf naye SKU bharne padte hain.
3. **Hisab** — usi page par: orders/delivered/RTO/return, bank settlement,
   product cost, ads, GST (settlement ka 5%), FINAL P&L, SKU-wise aur
   state-wise tables, pending-payment count — aur poori Excel report download.

### Rules (sab `docs/` me proof ke saath)

- Sub-order ka payment = us sub-order ke saare settlement transactions ka sum
- Product cost sirf un units par lagta hai jo customer tak pahunchi; RTO/return
  wapas aa jata hai — cost tabhi lagta hai jab returns file me "lost" likha ho
- GST = bank settlement ka 5% (net of return reversals); detailed GST model
  bhi config me available hai
- Per-order hisab sirf final-state orders par (in-transit orders alag gine
  jaate hain)
- TCS 0.5% / TDS 0.1% cross-check har row par

### CLI (bina portal ke)

```bash
python -m meesho_recon.cli --data ./raw_folder --out report.xlsx
```

`meesho_recon/config.py` me har rate/policy ek jagah hai.
