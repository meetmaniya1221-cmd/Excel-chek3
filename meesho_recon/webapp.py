"""The reconciliation portal.

    python run_portal.py            ->  http://localhost:8000

One workspace per client. The flow on screen is the same two-step flow as the
CLI: upload the Meesho downloads, take the SKU cost sheet the portal hands back,
fill the one yellow column, upload it again, and the full report renders on the
page with the Excel available to download.

Storage is plain folders under portal_data/<token>/ — no database. This is an
office tool for the seller/accountant's own machine, not a public service.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from flask import (Flask, abort, redirect, render_template_string, request,
                   send_file, url_for)

from .config import Config
from .pipeline import process_workspace

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "portal_data"
ALLOWED = {".csv", ".xlsx", ".xls", ".xlsb", ".txt", ".zip", ".rar"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
_jobs: dict[str, threading.Thread] = {}


# ----------------------------------------------------------------- helpers --
def _ws(token: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{8}", token):
        abort(404)
    ws = DATA / token
    if not ws.exists():
        abort(404)
    return ws


def _meta(ws: Path) -> dict:
    f = ws / "meta.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _status(ws: Path) -> dict:
    f = ws / "status.json"
    return json.loads(f.read_text()) if f.exists() else {"state": "idle"}


def _result(ws: Path) -> dict | None:
    f = ws / "out" / "result.json"
    return json.loads(f.read_text()) if f.exists() else None


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ ()\-\[\]]+", "_", Path(name).name)[:180] or "file"


def _extract_archives(raw: Path):
    """Unpack every archive dropped into raw/, repeatedly (zips inside zips)."""
    for _ in range(4):
        archives = [p for p in raw.rglob("*") if p.suffix.lower() in (".zip", ".rar")]
        if not archives:
            return
        for arc in archives:
            dest = arc.with_suffix("")
            dest.mkdir(exist_ok=True)
            try:
                if arc.suffix.lower() == ".zip":
                    with zipfile.ZipFile(arc) as z:
                        for m in z.infolist():
                            tgt = (dest / m.filename).resolve()
                            if not str(tgt).startswith(str(dest.resolve())):
                                continue                    # zip-slip guard
                            if m.is_dir():
                                tgt.mkdir(parents=True, exist_ok=True)
                            else:
                                tgt.parent.mkdir(parents=True, exist_ok=True)
                                tgt.write_bytes(z.read(m))
                else:
                    tool = shutil.which("7z") or shutil.which("unrar")
                    if not tool:
                        continue        # leave the .rar; user can upload a zip
                    cmd = ([tool, "x", "-y", f"-o{dest}", str(arc)]
                           if "7z" in tool else [tool, "x", "-o+", str(arc), str(dest) + "/"])
                    subprocess.run(cmd, capture_output=True, timeout=300)
            finally:
                arc.unlink(missing_ok=True)


def _run_job(token: str, force: bool = False):
    ws = DATA / token
    def say(step):
        (ws / "status.json").write_text(json.dumps(
            {"state": "processing", "step": step,
             "at": datetime.now().isoformat(timespec="seconds")}))
    try:
        say("starting")
        result = process_workspace(ws / "raw", ws / "out", Config(),
                                   report_only=force, progress=say)
        (ws / "status.json").write_text(json.dumps(
            {"state": "error" if result.get("status") == "error" else "done",
             "message": result.get("message", "")}))
    except Exception as e:                                   # surfaced on the page
        (ws / "status.json").write_text(json.dumps({"state": "error", "message": str(e)}))


def _start(token: str, force: bool = False):
    t = _jobs.get(token)
    if t and t.is_alive():
        return
    (DATA / token / "status.json").write_text(json.dumps({"state": "processing",
                                                          "step": "queued"}))
    t = threading.Thread(target=_run_job, args=(token, force), daemon=True)
    _jobs[token] = t
    t.start()


def _inr(v):
    try:
        v = float(v)
    except Exception:
        return v
    neg, v = v < 0, abs(v)
    s = f"{v:,.0f}"
    return ("−₹" if neg else "₹") + s


app.jinja_env.filters["inr"] = _inr


# ------------------------------------------------------------------- pages --
BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title><style>
:root{--paper:#F6F7F5;--card:#fff;--ink:#1B2420;--mut:#5B6660;--acc:#0B6B57;
--soft:#E3EFEA;--line:#DDE2DD;--warn:#8F6400;--wsoft:#FFF6D8;--bad:#A63D2F;--bsoft:#F6E4DF}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.55 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:66rem;margin:0 auto;padding:1.4rem 1rem 4rem}
header{display:flex;align-items:baseline;gap:.8rem;border-bottom:2px solid var(--ink);
padding-bottom:.8rem;margin-bottom:1.2rem;flex-wrap:wrap}
header h1{font-family:Georgia,serif;font-size:1.5rem;margin:0}
header a{color:var(--acc);text-decoration:none;font-size:.85rem}
header .tok{margin-left:auto;font:.75rem ui-monospace,monospace;color:var(--mut)}
h2{font-family:Georgia,serif;font-size:1.15rem;margin:1.6rem 0 .6rem}
.card{background:var(--card);border:1px solid var(--line);padding:1rem 1.1rem;margin:.8rem 0}
.btn{display:inline-block;background:var(--acc);color:#fff;border:none;cursor:pointer;
padding:.55rem 1.1rem;font-size:.92rem;text-decoration:none;border-radius:3px}
.btn.sec{background:var(--card);color:var(--acc);border:1px solid var(--acc)}
.btn:disabled{opacity:.5}.mut{color:var(--mut);font-size:.85rem}
input[type=text]{padding:.5rem .6rem;border:1px solid var(--line);font-size:.95rem;min-width:16rem}
input[type=file]{font-size:.85rem}
.badge{display:inline-block;font:700 .68rem ui-monospace,monospace;padding:.1rem .45rem;
border-radius:2px;background:var(--soft);color:var(--acc);margin-right:.3rem}
.badge.w{background:var(--wsoft);color:var(--warn)}.badge.b{background:var(--bsoft);color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
background:var(--line);border:1px solid var(--line);margin:.8rem 0}
.stat{background:var(--card);padding:.7rem .8rem}
.stat b{display:block;font-family:Georgia,serif;font-size:1.25rem;font-variant-numeric:tabular-nums}
.stat.neg b{color:var(--bad)}.stat.pos b{color:var(--acc)}
.stat i{font-style:normal;font-size:.68rem;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.tw{overflow-x:auto;border:1px solid var(--line);background:var(--card);margin:.6rem 0}
table{border-collapse:collapse;width:100%;font-size:.82rem}
th{font:700 .68rem ui-monospace,monospace;text-transform:uppercase;letter-spacing:.05em;
text-align:right;color:var(--mut);border-bottom:2px solid var(--ink);padding:.45rem .6rem;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
td{border-bottom:1px solid var(--line);padding:.4rem .6rem;text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
td.neg{color:var(--bad)}td.pos{color:var(--acc)}
.note{border-left:3px solid var(--acc);background:var(--soft);padding:.6rem .9rem;margin:.8rem 0}
.note.w{border-color:var(--warn);background:var(--wsoft)}
.note.b{border-color:var(--bad);background:var(--bsoft)}
.steps{display:flex;gap:.5rem;flex-wrap:wrap;margin:.6rem 0 1rem}
.step{flex:1;min-width:150px;border:1px solid var(--line);background:var(--card);
padding:.5rem .7rem;font-size:.8rem;color:var(--mut)}
.step.on{border-color:var(--acc);color:var(--ink);box-shadow:inset 3px 0 0 var(--acc)}
.step b{display:block;font-size:.72rem;color:var(--acc)}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--soft);
border-top-color:var(--acc);border-radius:50%;animation:r 0.8s linear infinite;vertical-align:-2px}
@keyframes r{to{transform:rotate(360deg)}}
ul.files{margin:.4rem 0;padding-left:1.2rem;font-size:.85rem}
</style></head><body><div class="wrap">
<header><h1>Meesho Hisab</h1><a href="{{ url_for('home') }}">sab clients</a>
{% if token %}<span class="tok">workspace {{ token }}</span>{% endif %}</header>
{{ body | safe }}
</div></body></html>"""


def page(title, body, token=None):
    return render_template_string(BASE, title=title,
                                  body=render_template_string(body), token=token)


@app.get("/")
def home():
    DATA.mkdir(exist_ok=True)
    rows = []
    for d in sorted(DATA.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if d.is_dir() and re.fullmatch(r"[a-f0-9]{8}", d.name):
            m = _meta(d)
            res = _result(d) or {}
            rows.append({"token": d.name, "name": m.get("name", d.name),
                         "state": res.get("status", "new"),
                         "when": datetime.fromtimestamp(d.stat().st_mtime)
                                         .strftime("%d %b %Y %H:%M")})
    body = """
<div class="card"><h2 style="margin-top:0">Naya client shuru karo</h2>
<form method="post" action="{{ url_for('new_ws') }}">
<input type="text" name="name" placeholder="Client / firm ka naam (e.g. Kesri Enterprise)" required>
<button class="btn">Start</button></form>
<p class="mut">Ek client = ek workspace. Data, cost sheet aur report sab usi me rehta hai —
agle mahine wahi workspace dobara kholo, purani SKU costs yaad rahengi.</p></div>
{% if rows %}<h2>Chal rahe clients</h2>
<div class="tw"><table><tr><th>Client</th><th>Status</th><th>Last activity</th><th></th></tr>
{% for r in rows %}<tr><td>{{ r.name }}</td>
<td style="text-align:left">{% if r.state == 'ready' %}<span class="badge">REPORT READY</span>
{% elif r.state == 'needs_costs' %}<span class="badge w">COST SHEET PENDING</span>
{% else %}<span class="badge b">NAYA</span>{% endif %}</td>
<td style="text-align:left">{{ r.when }}</td>
<td><a class="btn sec" href="/w/{{ r.token }}">kholo</a></td></tr>{% endfor %}
</table></div>{% endif %}"""
    return render_template_string(BASE, title="Meesho Hisab", token=None,
                                  body=render_template_string(body, rows=rows))


@app.post("/new")
def new_ws():
    token = secrets.token_hex(4)
    ws = DATA / token
    (ws / "raw").mkdir(parents=True)
    (ws / "out").mkdir()
    (ws / "meta.json").write_text(json.dumps(
        {"name": request.form.get("name", "").strip() or token,
         "created": datetime.now().isoformat(timespec="seconds")}))
    return redirect(f"/w/{token}")


@app.get("/w/<token>")
def workspace(token):
    ws = _ws(token)
    meta, status, result = _meta(ws), _status(ws), _result(ws)
    raw_files = sorted(p.name for p in (ws / "raw").rglob("*") if p.is_file())
    state = result.get("status") if result else None
    body = """
<h2 style="margin-top:0">{{ meta.get('name', token) }}</h2>
<div class="steps">
<div class="step {{ 'on' if not state else '' }}"><b>STEP 1</b>Meesho ki files upload karo
(payment / orders / returns / claims — zip bhi chalega)</div>
<div class="step {{ 'on' if state == 'needs_costs' else '' }}"><b>STEP 2</b>SKU cost sheet
download karo, Final Cost bharo, wapis upload karo</div>
<div class="step {{ 'on' if state == 'ready' else '' }}"><b>STEP 3</b>Hisab yahin screen par —
poori Excel report bhi download karo</div>
</div>

{% if status.state == 'processing' %}
<div class="note"><span class="spin"></span>&nbsp; Calculation chal raha hai —
<b id="step">{{ status.step }}</b> … page khud refresh hoga.</div>
<script>
async function poll(){
  const r = await fetch('/w/{{ token }}/status'); const s = await r.json();
  if (s.state === 'processing'){ document.getElementById('step').textContent = s.step || '…';
    setTimeout(poll, 1500); } else { location.reload(); }
}
setTimeout(poll, 1500);
</script>
{% elif status.state == 'error' %}
<div class="note b"><b>Dikkat:</b> {{ status.message }}</div>
{% endif %}

<div class="card">
<h2 style="margin-top:0">Files</h2>
<form method="post" action="/w/{{ token }}/upload" enctype="multipart/form-data">
<input type="file" name="files" multiple required>
<button class="btn">Upload</button>
<span class="mut">payment zip/xlsx · Orders csv · returns csv · claims csv — jo bhi hai, sab ek saath</span>
</form>
{% if raw_files %}<ul class="files">{% for f in raw_files %}<li>{{ f }}</li>{% endfor %}</ul>
<form method="post" action="/w/{{ token }}/process">
<button class="btn" {{ 'disabled' if status.state == 'processing' else '' }}>Hisab lagao</button>
</form>{% else %}<p class="mut">Abhi koi file nahi.</p>{% endif %}
</div>

{% if state == 'needs_costs' %}
<div class="note w"><b>{{ result.counts.unpriced_skus }} SKU ki cost chahiye</b>
(kul {{ result.counts.skus }} SKU mile). Neeche se sheet download karo, sirf yellow
<b>Final Cost</b> column bharo, aur wapis upload kar do — hisab khud chal jayega.</div>
<p><a class="btn" href="/w/{{ token }}/cost-sheet">SKU cost sheet download</a>
<form method="post" action="/w/{{ token }}/upload" enctype="multipart/form-data"
 style="display:inline-block;margin-left:.6rem">
<input type="file" name="files" accept=".xlsx" required>
<button class="btn sec">Bhari hui sheet upload</button></form></p>
{% if result.counts.unpriced_skus < result.counts.skus %}
<form method="post" action="/w/{{ token }}/process?force=1" style="margin-top:.4rem">
<button class="btn sec">In {{ result.counts.unpriced_skus }} SKU ke bina hi report banao</button>
<span class="mut">unka profit zyada dikhega</span></form>
{% endif %}
{% if result.top_skus %}
<div class="tw"><table><tr><th>SKU</th><th>Orders</th><th>Avg settlement / delivered</th></tr>
{% for s in result.top_skus %}<tr><td>{{ s.sku }}</td><td>{{ s.orders }}</td>
<td>{{ s.avg_sale | inr }}</td></tr>{% endfor %}</table></div>
{% endif %}
{% endif %}

{% if state == 'ready' %}
{% set b = result.bridge %}
<h2>Hisab</h2>
<div class="grid">
<div class="stat"><b>{{ b.orders }}</b><i>orders (final)</i></div>
<div class="stat"><b>{{ b.delivered }}</b><i>delivered</i></div>
<div class="stat"><b>{{ b.rto }}</b><i>RTO</i></div>
<div class="stat"><b>{{ b.customer_return }}</b><i>customer return</i></div>
<div class="stat"><b>{{ b.pending_payments }}</b><i>payment pending orders</i></div>
</div>
<div class="grid">
<div class="stat"><b>{{ b.settlement | inr }}</b><i>bank settlement</i></div>
<div class="stat"><b>{{ b.purchase | inr }}</b><i>product cost</i></div>
<div class="stat"><b>{{ b.ads | inr }}</b><i>ads</i></div>
<div class="stat {{ 'neg' if b.operating_pl < 0 else 'pos' }}"><b>{{ b.operating_pl | inr }}</b><i>operating P&amp;L</i></div>
<div class="stat"><b>{{ b.gst | inr }}</b><i>GST @ settlement</i></div>
<div class="stat {{ 'neg' if b.final_pl < 0 else 'pos' }}"><b>{{ b.final_pl | inr }}</b><i>FINAL P&amp;L</i></div>
</div>
<p><a class="btn" href="/w/{{ token }}/report.xlsx">Poori Excel report download</a>
<a class="btn sec" href="/w/{{ token }}/cost-sheet">cost sheet (update ke liye)</a>
{% if b.in_flight %}<span class="mut">&nbsp;{{ b.in_flight }} orders abhi raste me —
hisab me nahi gine.</span>{% endif %}</p>

{% if result.counts.unpriced_skus %}
<div class="note w">{{ result.counts.unpriced_skus }} SKU bina cost ke hain — unka profit
zyada dikh raha hai. Cost sheet update karke dobara "Hisab lagao".</div>
{% endif %}

<h2>SKU ka hisab <span class="mut">(ghata pehle)</span></h2>
<div class="tw"><table>
<tr><th>SKU</th><th>Orders</th><th>Del.</th><th>RTO</th><th>Ret.</th><th>RTO %</th>
<th>Settle/unit</th><th>Cost/unit</th><th>Margin/unit</th><th>Net P&amp;L</th></tr>
{% for s in result.sku_table %}
<tr><td>{{ s.sku }}</td><td>{{ s.orders }}</td><td>{{ s.delivered }}</td><td>{{ s.rto }}</td>
<td>{{ s.ret }}</td><td>{{ '%.0f' % (s.rto_pct * 100) }}%</td>
<td>{{ s.settle_per | inr }}</td><td>{{ s.cost_per | inr }}</td>
<td class="{{ 'neg' if s.margin_per < 0 else 'pos' }}">{{ s.margin_per | inr }}</td>
<td class="{{ 'neg' if s.net < 0 else 'pos' }}">{{ s.net | inr }}</td></tr>
{% endfor %}</table></div>

{% if result.state_table %}
<h2>State ka hisab</h2>
<div class="tw"><table>
<tr><th>State</th><th>Orders</th><th>Delivered</th><th>RTO</th><th>RTO %</th>
<th>Settlement</th><th>Net P&amp;L</th></tr>
{% for s in result.state_table[:25] %}
<tr><td>{{ s.state }}</td><td>{{ s.orders }}</td><td>{{ s.delivered }}</td>
<td>{{ s.rto }}</td><td>{{ '%.0f' % (s.rto_pct * 100) }}%</td>
<td>{{ s.settle | inr }}</td>
<td class="{{ 'neg' if s.net < 0 else 'pos' }}">{{ s.net | inr }}</td></tr>
{% endfor %}</table></div>
{% endif %}
{% endif %}
"""
    return render_template_string(BASE, title=meta.get("name", token), token=token,
                                  body=render_template_string(
                                      body, token=token, meta=meta, status=status,
                                      result=result, state=state, raw_files=raw_files))


@app.post("/w/<token>/upload")
def upload(token):
    ws = _ws(token)
    saved = 0
    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        name = _safe_name(f.filename)
        if Path(name).suffix.lower() not in ALLOWED:
            continue
        # a filled cost sheet goes in under its canonical name so the engine finds it
        if "sku_cost" in name.lower().replace(" ", "_"):
            name = "SKU_COSTS.xlsx"
        f.save(ws / "raw" / name)
        saved += 1
    _extract_archives(ws / "raw")
    if saved:
        _start(token)                      # uploading implies "calculate"
    return redirect(f"/w/{token}")


@app.post("/w/<token>/process")
def process(token):
    _ws(token)
    _start(token, force=request.args.get("force") == "1")
    return redirect(f"/w/{token}")


@app.get("/w/<token>/status")
def status(token):
    return _status(_ws(token))


@app.get("/w/<token>/cost-sheet")
def cost_sheet(token):
    ws = _ws(token)
    f = ws / "out" / "SKU_COSTS.xlsx"
    if not f.exists():
        abort(404)
    name = _meta(ws).get("name", token).replace(" ", "_")
    return send_file(f, as_attachment=True, download_name=f"SKU_COSTS_{name}.xlsx")


@app.get("/w/<token>/report.xlsx")
def report(token):
    ws = _ws(token)
    f = ws / "out" / "report.xlsx"
    if not f.exists():
        abort(404)
    name = _meta(ws).get("name", token).replace(" ", "_")
    return send_file(f, as_attachment=True, download_name=f"Hisab_{name}.xlsx")


def main():
    DATA.mkdir(exist_ok=True)
    print("\n  Meesho Hisab portal  ->  http://localhost:8000\n")
    app.run(host="0.0.0.0", port=8000, debug=False)


if __name__ == "__main__":
    main()
