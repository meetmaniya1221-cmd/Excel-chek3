# Meesho Hisab

Meesho seller payments ka poora hisab — reverse-engineered from a third-party
Excel system (see `docs/REVERSE_ENGINEERING.md`), rebuilt in Python, and served
as a small web portal.

## Portal live karne ke 3 tarike

**1. GitHub Codespaces — seedha is branch se, bina kuch install kiye**

GitHub par is repo me: green **Code** button → **Codespaces** tab →
**Create codespace**. Khulte hi portal khud start ho jata hai aur browser
preview me `:8000` par khul jata hai. (GitHub khud Python server host nahi
karta — Codespace hi "GitHub se live" chalane ka tarika hai; free quota
~120 ghante/mahina milta hai.)

**2. Internet par 24x7 (Render, free)**

[render.com](https://render.com) par account banao → **New → Blueprint** →
ye repo chuno — `render.yaml` sab set kar dega, ek public URL mil jayega.
`portal_data/` ke liye 1GB disk laga hua hai, isliye workspaces bane rahenge.
(Railway/Fly par bhi chalega — `Dockerfile` aur `Procfile` dono maujood hain.)

**Dhyan:** abhi login/password nahi hai — public URL jo bhi jaanta hai wo sab
workspaces dekh sakta hai. Isliye Render wala tarika tab tak sirf apne test ke
liye use karo jab tak login system nahi lagta (wo agla kaam hai).

**3. Apne computer par**

```bash
pip install -r requirements.txt
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
