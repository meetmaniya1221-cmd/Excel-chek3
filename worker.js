/* Meesho Hisab — processing worker.
 *
 * Loads Pyodide (Python compiled to WebAssembly), installs the pure-Python
 * deps, pulls the meesho_recon package straight from this same GitHub Pages
 * site, and runs the exact engine the CLI uses. Everything happens inside the
 * visitor's browser: no file ever leaves their machine.
 */
"use strict";

/* Pyodide comes from ./pyodide/ when a mirror is checked in next to the site
 * (lets the portal run fully offline); otherwise from the public CDN. */
const CDN = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
const HERE = self.location.href.replace(/worker\.js.*$/, "");

function hasLocalPyodide() {
  try {
    const x = new XMLHttpRequest();          // sync HEAD: workers may importScripts only at top level
    x.open("HEAD", HERE + "pyodide/pyodide.js", false);
    x.send();
    return x.status === 200;
  } catch (e) { return false; }
}
const LOCAL = hasLocalPyodide();
const INDEX_URL = LOCAL ? HERE + "pyodide/" : CDN;
importScripts(INDEX_URL + "pyodide.js");

const PKG_FILES = ["__init__.py", "config.py", "ingest.py", "engine.py",
                   "reports.py", "excel_out.py", "validate.py", "cli.py",
                   "pipeline.py"];

let pyodideReady = null;

function status(step) { postMessage({ type: "status", step }); }

async function boot() {
  status("Python engine load ho raha hai (pehli baar ~30s)");
  const py = await loadPyodide({ indexURL: INDEX_URL });
  status("pandas / numpy load ho rahe hain");
  await py.loadPackage(["pandas", "numpy"]);
  status("openpyxl install ho raha hai");
  let wheels;
  try {
    const mf = await fetch(HERE + "wheels/manifest.json");
    if (!mf.ok) throw 0;
    wheels = (await mf.json()).map((n) => HERE + "wheels/" + n);
  } catch (e) {
    wheels = null;                                    // no local wheels -> PyPI
  }
  if (wheels) {
    await py.loadPackage(wheels);
  } else {
    await py.loadPackage(["micropip"]);
    await py.runPythonAsync(`
import micropip
await micropip.install(["openpyxl", "et-xmlfile", "pyxlsb"])
`);
  }
  status("hisab engine download ho raha hai");
  py.FS.mkdirTree("/app/meesho_recon");
  for (const f of PKG_FILES) {
    const r = await fetch(`meesho_recon/${f}?v=1`);
    if (!r.ok) throw new Error(`engine file ${f} nahi mila (${r.status})`);
    py.FS.writeFile(`/app/meesho_recon/${f}`, await r.text());
  }
  self.pyStatus = (s) => status(s);
  py.runPython(`
import sys
sys.path.insert(0, "/app")
import js, json, base64, shutil, zipfile
from pathlib import Path
import pandas as _pd

from meesho_recon import reports as _reports
from meesho_recon.config import Config
from meesho_recon.pipeline import process_workspace

# Browser build trims the two very large styled sheets: openpyxl under wasm is
# ~5x slower than native and the per-cell styling of 6-12k rows would take
# minutes. The on-screen tables and the desktop CLI carry the full detail.
_orig_exceptions = _reports.exceptions
_reports.suborder_report = lambda df: _pd.DataFrame()
_reports.exceptions = lambda df: _orig_exceptions(df).head(300)

RAW, OUT = Path("/work/raw"), Path("/work/out")

def _extract(raw):
    for _ in range(4):
        zips = [p for p in raw.rglob("*") if p.suffix.lower() == ".zip"]
        if not zips:
            break
        for arc in zips:
            dest = arc.with_suffix("")
            dest.mkdir(exist_ok=True)
            try:
                with zipfile.ZipFile(arc) as z:
                    for m in z.infolist():
                        tgt = (dest / m.filename).resolve()
                        if not str(tgt).startswith(str(dest.resolve())):
                            continue
                        if m.is_dir():
                            tgt.mkdir(parents=True, exist_ok=True)
                        else:
                            tgt.parent.mkdir(parents=True, exist_ok=True)
                            tgt.write_bytes(z.read(m))
            finally:
                arc.unlink()

def run_job(force):
    shutil.rmtree("/work", ignore_errors=True)
    RAW.mkdir(parents=True); OUT.mkdir(parents=True)
    skipped_rar = []
    up = Path("/upload")
    for src in sorted(up.iterdir()):
        name = src.name
        low = name.lower().replace(" ", "_")
        if low.endswith(".rar"):
            skipped_rar.append(name); src.unlink(); continue
        if "sku_cost" in low:
            name = "SKU_COSTS.xlsx"
        (RAW / name).write_bytes(src.read_bytes())
        src.unlink()
    _extract(RAW)
    js.pyStatus("files padh raha hai")
    result = process_workspace(RAW, OUT, Config(), report_only=bool(force),
                               progress=lambda s: js.pyStatus(s))
    if skipped_rar:
        result.setdefault("warnings", []).append(
            ".rar browser me nahi khulta — inko zip banake dobara upload karo: "
            + ", ".join(skipped_rar))
    out = {"result": result, "cost_b64": None, "report_b64": None}
    cs = OUT / "SKU_COSTS.xlsx"
    if cs.exists():
        out["cost_b64"] = base64.b64encode(cs.read_bytes()).decode()
    rp = OUT / "report.xlsx"
    if result.get("status") == "ready" and rp.exists():
        js.pyStatus("Excel report ban rahi hai")
        out["report_b64"] = base64.b64encode(rp.read_bytes()).decode()
    return json.dumps(out)
`);
  return py;
}

onmessage = async (ev) => {
  const msg = ev.data;
  if (msg.type !== "run") return;
  try {
    if (!pyodideReady) pyodideReady = boot();
    const py = await pyodideReady;

    // drop the uploaded bytes straight into the WASM filesystem; Python then
    // works with ordinary files and no byte buffers cross the FFI boundary
    try { py.FS.mkdir("/upload"); } catch (e) {}
    for (const f of msg.files)
      py.FS.writeFile("/upload/" + f.name, new Uint8Array(f.buf));
    const runJob = py.globals.get("run_job");
    const raw = runJob(!!msg.force);
    runJob.destroy();
    const out = JSON.parse(raw);
    postMessage({ type: "done", ...out });
  } catch (e) {
    postMessage({ type: "error", message: String(e && e.message || e) });
  }
};
