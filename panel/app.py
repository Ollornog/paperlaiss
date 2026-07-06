#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paperlaiss Panel — schlankes FastAPI-Dashboard für den Klassifizierer + Ingest-API.

Kein Fork des ollornog-Flask-Panels: neu, klein, als eigenständiger paperlaiss-Baustein.
Eine übergeordnete Plattform (ChatWisMe) kann dieselben JSON-Endpunkte konsumieren.

Läuft als eigener Container im selben Docker-Netz wie Paperless, mit dem geteilten
scripts-Verzeichnis (classify.py + config + log + traces + running) als Volume.

ENV:
  PAPERLESS_API   http://webserver:8000/api
  PAPERLESS_TOKEN / MISTRAL_KEY   an classify.py durchgereicht (Re-Trigger + Ingest)
  CLASSIFY_DIR    Verzeichnis mit classify.py/-config/-log (default /scripts)
  PANEL_TOKEN     optional: Bearer-Token schützt die UI/API (leer = offen, für Prod TinyAuth/OIDC davor)
  INGEST_TOKENS   optional JSON {"<token>": "<Quelle-Tag>"} für die Ingest-API
"""
import os, json, re, glob, html, subprocess, datetime, urllib.request, urllib.error
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

CLASSIFY_DIR = os.environ.get("CLASSIFY_DIR", "/scripts")
CLASSIFY_PY = os.path.join(CLASSIFY_DIR, "classify.py")
CONFIG = os.environ.get("CLASSIFY_CONFIG", os.path.join(CLASSIFY_DIR, "classify-config.json"))
LOG = os.environ.get("CLASSIFY_LOG", os.path.join(CLASSIFY_DIR, "classify.log"))
TRACE_DIR = os.path.join(CLASSIFY_DIR, "traces")
RUN_DIR = os.path.join(CLASSIFY_DIR, "running")
BASE = os.environ.get("PAPERLESS_API", "http://webserver:8000/api")
TOK = os.environ.get("PAPERLESS_TOKEN", "")
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
PANEL_TOKEN = os.environ.get("PANEL_TOKEN", "")
try:
    INGEST_TOKENS = json.loads(os.environ.get("INGEST_TOKENS", "{}"))
except Exception:
    INGEST_TOKENS = {}

app = FastAPI(title="paperlaiss")


def _cfg():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {}


def guard(request: Request):
    """Optionaler Panel-Schutz (Bearer PANEL_TOKEN). Leer = offen."""
    if not PANEL_TOKEN:
        return
    auth = request.headers.get("authorization", "")
    cookie = request.cookies.get("panel_token", "")
    if auth == f"Bearer {PANEL_TOKEN}" or cookie == PANEL_TOKEN:
        return
    raise HTTPException(401, "Panel-Token nötig")


# ---------- Paperless-API ----------
def api_get(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Token {TOK}"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def api_send(path, data, method="POST"):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
        headers={"Authorization": f"Token {TOK}", "Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=30))


# ---------- Log-Parser ----------
LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (?:DRY )?(.*)$")
DOCRE = re.compile(r"\b(?:OK|DRY|skip|FEHLER|OCR-rescue|OCR-rescue-fail|patch-fail|repariert|repair-fehlgeschlagen|KI-OCR-fail)\s+(\d+)")


def parse_log(limit=400):
    events = []
    try:
        lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return events
    for ln in lines[-4000:]:
        m = LINE.match(ln)
        if not m:
            continue
        ts, rest = m.group(1), m.group(2)
        dm = DOCRE.search(rest)
        doc = dm.group(1) if dm else None
        if rest.startswith("OK "):
            kind = "ok"
        elif rest.startswith("FEHLER"):
            kind = "fehler"
        elif rest.startswith("repariert"):
            kind = "repariert"
        elif rest.startswith("OCR-rescue-fail") or "fehlgeschlagen" in rest or rest.startswith("patch-fail") or "fail" in rest:
            kind = "warn"
        elif rest.startswith("OCR-rescue"):
            kind = "ocr"
        elif rest.startswith("skip"):
            kind = "skip"
        else:
            kind = "info"
        events.append({"ts": ts, "kind": kind, "doc": doc, "msg": rest})
    return events[-limit:]


def compute_stats():
    ev = parse_log(4000)
    docs_ok = {e["doc"] for e in ev if e["kind"] == "ok" and e["doc"]}
    return {
        "klassifiziert": len(docs_ok),
        "ocr_rescues": sum(1 for e in ev if e["kind"] == "ocr"),
        "repariert": sum(1 for e in ev if e["kind"] == "repariert"),
        "fehler": sum(1 for e in ev if e["kind"] == "fehler"),
        "skips": sum(1 for e in ev if e["kind"] == "skip"),
    }


def running_jobs():
    jobs = []
    now = datetime.datetime.now()
    for p in sorted(glob.glob(os.path.join(RUN_DIR, "*.json"))):
        try:
            j = json.load(open(p))
            since = datetime.datetime.strptime(j.get("since", ""), "%Y-%m-%d %H:%M:%S")
            if (now - since).total_seconds() > 600:   # stale
                continue
            j["dauer"] = int((now - since).total_seconds())
            jobs.append(j)
        except Exception:
            pass
    return jobs


# ---------- classify.py Re-Trigger ----------
def run_classify(doc, force=True, force_ocr=False, source="manual"):
    env = dict(os.environ)
    env.update({"CLASSIFY_DOC": str(doc), "PAPERLESS_API": BASE, "PAPERLESS_TOKEN": TOK,
                "MISTRAL_KEY": MISTRAL_KEY, "CLASSIFY_CONFIG": CONFIG, "CLASSIFY_LOG": LOG,
                "CLASSIFY_SOURCE": source})
    if force:
        env["CLASSIFY_FORCE"] = "1"
    if force_ocr:
        env["CLASSIFY_FORCE_OCR"] = "1"
    try:
        r = subprocess.run(["python3", CLASSIFY_PY], env=env, capture_output=True, text=True, timeout=300)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, repr(e)


# ---------- Endpoints ----------
@app.get("/health")
def health():
    return {"ok": True, "config": os.path.exists(CONFIG), "classify": os.path.exists(CLASSIFY_PY)}


@app.get("/api/stats")
def stats(request: Request):
    guard(request)
    return compute_stats()


@app.get("/api/feed")
def feed(request: Request, limit: int = 120):
    guard(request)
    ev = parse_log(limit)
    return list(reversed(ev))


@app.get("/api/running")
def running(request: Request):
    guard(request)
    return {"jobs": running_jobs()}


@app.get("/api/trace/{doc_id}")
def trace(request: Request, doc_id: str):
    guard(request)
    p = os.path.join(TRACE_DIR, f"{doc_id}.json")
    if not os.path.exists(p):
        raise HTTPException(404, "kein Trace")
    return json.load(open(p))


@app.post("/api/reclassify")
async def reclassify(request: Request):
    guard(request)
    body = await request.json()
    doc = str(body.get("doc", "")).strip()
    if not doc.isdigit():
        raise HTTPException(400, "doc-ID nötig")
    mode = body.get("mode", "classify")
    rc, out = run_classify(doc, force=True, force_ocr=(mode == "ocr"))
    return {"ok": rc == 0, "doc": doc, "mode": mode, "output": out[-1500:]}


@app.get("/api/config")
def get_config(request: Request):
    guard(request)
    return _cfg()


@app.post("/api/config")
async def set_config(request: Request):
    guard(request)
    body = await request.json()
    cfg = _cfg()
    cfg.update(body)
    json.dump(cfg, open(CONFIG, "w"), ensure_ascii=False, indent=2)
    return {"ok": True, "config": cfg}


# ---------- Ingest-API (externe Scans / Herkunft) ----------
@app.post("/ingest")
async def ingest(file: UploadFile = File(...), title: str = Form(None),
                 x_ingest_token: str = Header(None)):
    """Datei + Quelle-Kennung (via Token) → Paperless post_document + Quelle-Tag."""
    source = INGEST_TOKENS.get(x_ingest_token or "")
    if not source:
        raise HTTPException(401, "gültiges X-Ingest-Token nötig")
    data = await file.read()
    # Quelle-Tag sicherstellen (anlegen falls fehlt)
    tag_id = None
    try:
        res = api_get(f"/tags/?name__iexact={urllib.request.quote(source)}")["results"]
        tag_id = res[0]["id"] if res else api_send("/tags/", {"name": source})["id"]
    except Exception:
        pass
    # Multipart an Paperless post_document
    boundary = "----paperlaissIngest"
    parts = []
    def field(name, value):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    field("title", title or file.filename or "Ingest")
    if tag_id:
        field("tags", str(tag_id))
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{file.filename}"\r\n'
                 f'Content-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f'--{boundary}--\r\n'.encode())
    body = b"".join(parts)
    req = urllib.request.Request(BASE + "/documents/post_document/", data=body,
        headers={"Authorization": f"Token {TOK}", "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            task = r.read().decode("utf-8", "replace").strip().strip('"')
        return {"ok": True, "source": source, "tag": source, "task": task}
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"Paperless-Upload fehlgeschlagen: {e.read().decode('utf-8','replace')[:300]}")


# ---------- Dashboard ----------
PAGE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>paperlaiss</title>
<style>
:root{color-scheme:light dark}
body{font-family:system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:14px 20px;background:#161a22;border-bottom:1px solid #262b36;display:flex;align-items:center;gap:12px}
header h1{font-size:18px;margin:0;font-weight:600}
.wrap{max-width:1000px;margin:0 auto;padding:18px 20px}
.banner{padding:10px 14px;border-radius:8px;background:#1b2130;margin-bottom:16px;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:20px}
.card{background:#161a22;border:1px solid #262b36;border-radius:10px;padding:14px}
.card .n{font-size:26px;font-weight:700}.card .l{font-size:12px;color:#9aa4b2;margin-top:2px}
h2{font-size:14px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.05em;margin:22px 0 8px}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:6px 8px;border-bottom:1px solid #20252f;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:520px}
.badge{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;font-weight:600}
.ok{background:#12331f;color:#4ade80}.fehler{background:#3a1520;color:#f87171}.repariert{background:#33290f;color:#fbbf24}
.ocr{background:#12283a;color:#60a5fa}.skip{background:#22262e;color:#8b95a3}.warn{background:#332409;color:#fb923c}.info{background:#22262e;color:#9aa4b2}
a{color:#7dd3fc;text-decoration:none}button{cursor:pointer;background:#2563eb;color:#fff;border:0;border-radius:6px;padding:6px 12px;font-size:13px}
button.sec{background:#374151}input,textarea{background:#0f1115;color:#e6e6e6;border:1px solid #303643;border-radius:6px;padding:6px 8px;font-family:inherit}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}
dialog{background:#161a22;color:#e6e6e6;border:1px solid #303643;border-radius:12px;max-width:760px;width:92%}
pre{white-space:pre-wrap;word-break:break-word;font-size:12px;background:#0f1115;padding:10px;border-radius:8px;max-height:60vh;overflow:auto}
</style></head><body>
<header><h1>🧠 paperlaiss</h1><span style="font-size:13px;color:#9aa4b2">Klassifizierer-Panel</span></header>
<div class=wrap>
  <div class=banner id=banner>…</div>
  <div class=cards id=cards></div>
  <h2>Manuell klassifizieren</h2>
  <div class=row>
    <input id=docid placeholder="Doc-ID" style="width:110px">
    <button onclick="rc('classify')">Neu klassifizieren</button>
    <button class=sec onclick="rc('ocr')">mit OCR erzwingen</button>
    <span id=rcout style="font-size:12px;color:#9aa4b2"></span>
  </div>
  <h2>Aktivität</h2>
  <table id=feed></table>
</div>
<dialog id=dlg><div style="padding:16px"><div class=row style="justify-content:space-between"><b id=dlgt></b><button class=sec onclick="dlg.close()">×</button></div><pre id=dlgc></pre></div></dialog>
<script>
const badge=k=>`<span class="badge ${k}">${k}</span>`;
async function j(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error(await r.text());return r.json()}
async function load(){
  try{
    const s=await j('/api/stats');
    document.getElementById('cards').innerHTML=Object.entries(
      {klassifiziert:'klassifiziert',ocr_rescues:'OCR-Rescues',repariert:'repariert',fehler:'Fehler',skips:'übersprungen'})
      .map(([k,l])=>`<div class=card><div class=n>${s[k]??0}</div><div class=l>${l}</div></div>`).join('');
  }catch(e){}
  try{
    const r=await j('/api/running');const jobs=r.jobs||[];
    document.getElementById('banner').textContent=jobs.length
      ? '⏳ Läuft gerade: '+jobs.map(x=>`Doc ${x.id} — ${x.stage} (${x.src}, ${x.dauer}s)`).join(' · ')
      : '💤 Idle';
  }catch(e){}
  try{
    const f=await j('/api/feed?limit=120');
    document.getElementById('feed').innerHTML=f.map(e=>{
      const d=e.doc?`<a href="#" onclick="showtrace('${e.doc}');return false">${e.doc}</a>`:'—';
      return `<tr><td style="color:#6b7280">${e.ts.slice(11)}</td><td>${badge(e.kind)}</td><td>${d}</td><td>${e.msg.replace(/</g,'&lt;')}</td></tr>`;
    }).join('');
  }catch(e){}
}
async function rc(mode){
  const doc=document.getElementById('docid').value.trim();if(!doc)return;
  document.getElementById('rcout').textContent='läuft…';
  try{const r=await j('/api/reclassify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({doc,mode})});
    document.getElementById('rcout').textContent=r.ok?'✓ fertig':'✗ Fehler';load();}
  catch(e){document.getElementById('rcout').textContent='✗ '+e.message}
}
async function showtrace(id){
  try{const t=await j('/api/trace/'+id);
    document.getElementById('dlgt').textContent='Trace Doc '+id;
    document.getElementById('dlgc').textContent=JSON.stringify(t,null,2);
    document.getElementById('dlg').showModal();}
  catch(e){alert('kein Trace für '+id)}
}
load();setInterval(load,6000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    guard(request)
    return PAGE
