#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paperlaiss Panel — schlankes FastAPI-Dashboard für den Klassifizierer + Ingest-API.

Neu und klein, als eigenständiger paperlaiss-Baustein. Eine übergeordnete Plattform
kann dieselben JSON-Endpunkte konsumieren.

Läuft als eigener Container im selben Docker-Netz wie Paperless, mit dem geteilten
scripts-Verzeichnis (classify.py + config + log + traces + running) als Volume.

ENV:
  PAPERLESS_API   http://webserver:8000/api
  PAPERLESS_TOKEN / MISTRAL_KEY   an classify.py durchgereicht (Re-Trigger + Ingest)
  CLASSIFY_DIR    Verzeichnis mit classify.py/-config/-log (default /scripts)
  PANEL_TOKEN     optional: Bearer-Token schützt die UI/API (leer = offen, für Prod TinyAuth/OIDC davor)
  INGEST_TOKENS   optional JSON {"<token>": "<Quelle-Tag>"} für die Ingest-API
"""
import os, sys, json, re, glob, html, hmac, subprocess, datetime, tempfile, urllib.request, urllib.error
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

CLASSIFY_DIR = os.environ.get("CLASSIFY_DIR", "/scripts")
CLASSIFY_PY = os.path.join(CLASSIFY_DIR, "classify.py")
CONFIG = os.environ.get("CLASSIFY_CONFIG", os.path.join(CLASSIFY_DIR, "classify-config.json"))
LOG = os.environ.get("CLASSIFY_LOG", os.path.join(CLASSIFY_DIR, "classify.log"))
TRACE_DIR = os.path.join(CLASSIFY_DIR, "traces")
RUN_DIR = os.path.join(CLASSIFY_DIR, "running")
CORR_STORE = os.path.join(CLASSIFY_DIR, "correspondents.json")   # per Paperless-ID an Korrespondenten gebunden
BASE = os.environ.get("PAPERLESS_API", "http://webserver:8000/api")
TOK = os.environ.get("PAPERLESS_TOKEN", "")
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
PANEL_TOKEN = os.environ.get("PANEL_TOKEN", "")
# Ein fehlender Token oeffnet das Panel NICHT mehr. Wer bewusst ohne eigene Anmeldung
# betreiben will (z.B. weil ein Reverse-Proxy mit OIDC davorhaengt), setzt PANEL_AUTH=none.
PANEL_AUTH = os.environ.get("PANEL_AUTH", "").strip().lower()
try:
    INGEST_TOKENS = json.loads(os.environ.get("INGEST_TOKENS", "{}"))
except Exception:
    INGEST_TOKENS = {}

# Felder der Config, die Geheimnisse tragen koennen: werden nie ausgeliefert und nie
# ueber die API geschrieben. Sie gehoeren in die Umgebung (MISTRAL_KEY), nicht in eine
# Datei, die eine offene Weboberflaeche lesen kann.
GEHEIM_FELDER = ("api_key_text", "api_key_ocr")

app = FastAPI(title="paperlaiss")

if not PANEL_TOKEN and PANEL_AUTH != "none":
    print("paperlaiss-panel: PANEL_TOKEN fehlt — alle API-Aufrufe antworten mit 503. "
          "Token setzen, oder PANEL_AUTH=none wenn eine Anmeldung davorhaengt.", file=sys.stderr)


def schreibe_json(pfad, daten):
    """JSON atomar schreiben: erst in eine Nachbardatei, dann umbenennen.

    `json.dump(d, open(pfad, "w"))` kuerzt die Zieldatei SOFORT auf null. Bricht der
    Schreibvorgang danach ab — voller Datentraeger, Absturz, Neustart des Containers —,
    ist der alte Inhalt weg und der neue nie angekommen. Fuer den Korrespondent-Store
    heisst das: der gepflegte Kundenstamm ist futsch. os.replace ist auf POSIX atomar,
    es gibt also keinen Moment, in dem die Datei halb geschrieben dasteht.
    """
    ordner = os.path.dirname(os.path.abspath(pfad)) or "."
    fd, tmp = tempfile.mkstemp(dir=ordner, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pfad)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _cfg():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {}


def _cfg_oeffentlich():
    """Config ohne Geheimnisfelder — das, was eine Oberflaeche sehen darf."""
    return {k: v for k, v in _cfg().items() if k not in GEHEIM_FELDER}


def guard(request: Request):
    """Panel-Schutz (Bearer PANEL_TOKEN).

    Faellt GESCHLOSSEN aus: ohne Token antwortet das Panel mit 503 statt offen zu stehen.
    Bis 2026-09-21 war es umgekehrt („leer = offen") — im Testbett lief das Panel dadurch
    ohne jede Anmeldung im LAN, mit Lesezugriff auf die Korrespondent-Kontaktdaten und
    Schreibzugriff auf system_prompt (= Prompt-Injektion in jede kuenftige Klassifizierung).
    """
    if not PANEL_TOKEN:
        if PANEL_AUTH == "none":
            return                      # bewusst offen, Anmeldung haengt davor
        raise HTTPException(503, "Panel nicht konfiguriert: PANEL_TOKEN fehlt "
                                 "(oder PANEL_AUTH=none setzen, wenn eine Anmeldung davorhaengt).")
    auth = request.headers.get("authorization", "")
    cookie = request.cookies.get("panel_token", "")
    erwartet = f"Bearer {PANEL_TOKEN}"
    # compare_digest statt ==: gleiche Laufzeit unabhaengig davon, ab welchem Zeichen es abweicht
    if hmac.compare_digest(auth, erwartet) or hmac.compare_digest(cookie, PANEL_TOKEN):
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
    return _cfg_oeffentlich()


@app.post("/api/config")
async def set_config(request: Request):
    guard(request)
    body = await request.json()
    verboten = sorted(k for k in body if k in GEHEIM_FELDER)
    if verboten:
        raise HTTPException(400, f"Diese Felder gehören in die Umgebung, nicht in die Config: "
                                 f"{', '.join(verboten)} (MISTRAL_KEY als ENV setzen).")
    cfg = _cfg()
    cfg.update(body)
    schreibe_json(CONFIG, cfg)
    return {"ok": True, "config": _cfg_oeffentlich()}


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


# ---------- Korrespondent-Metadaten (Store, per Paperless-ID gekoppelt) ----------
# `ustid` hiess bis 2026-09-21 `uid` (Kollision mit vCard-UID, s. classify.py).
# `quelle`/`extern_id` sind der Platz fuer eine spaetere externe Stammdatenquelle:
# woher kam der Datensatz, und unter welcher Kennung wird er dort gefuehrt. Zwei
# Freitextfelder, kein Sync — solange es keine Quelle gibt, waere mehr Architektur ohne Anlass.
CORR_FIELDS = ("email", "domains", "telefon", "adresse", "kundennummer", "ustid",
               "kontext", "aliase", "quelle", "extern_id")
CORR_ALTNAMEN = {"ustid": "uid"}     # beim Lesen alter Stores


def load_corr_store():
    try:
        d = json.load(open(CORR_STORE))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_corr_store(d):
    schreibe_json(CORR_STORE, d)


@app.get("/api/correspondents")
def correspondents(request: Request):
    guard(request)
    store = load_corr_store()
    try:
        res = api_get("/correspondents/?page_size=2000")["results"]
    except Exception:
        res = []
    out = []
    for c in res:
        m = store.get(str(c["id"]), {})
        row = {"id": c["id"], "name": c["name"], "document_count": c.get("document_count", 0)}
        for f in CORR_FIELDS:
            # Altname beruecksichtigen, damit ein Store von vor der Umbenennung nicht
            # so aussieht, als waere das Feld leer (uid -> ustid, 2026-09-21).
            row[f] = m.get(f) or m.get(CORR_ALTNAMEN.get(f, ""), "") or ""
        out.append(row)
    out.sort(key=lambda x: (x["name"] or "").lower())
    return out


@app.post("/api/correspondents")
async def save_correspondent(request: Request):
    guard(request)
    b = await request.json()
    cid = str(b.get("id", "")).strip()
    if not cid.isdigit():
        raise HTTPException(400, "gültige Paperless-Korrespondent-id nötig")
    store = load_corr_store()
    vals = {f: str(b.get(f) or "").strip() for f in CORR_FIELDS}
    if any(vals.values()):
        store[cid] = vals
    else:
        store.pop(cid, None)   # alles leer → Eintrag entfernen (verwaist)
    save_corr_store(store)
    return {"ok": True, "id": cid}


CORR_PAGE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>paperlaiss — Korrespondenten</title>
<style>
:root{color-scheme:light dark}
body{font-family:system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:14px 20px;background:#161a22;border-bottom:1px solid #262b36;display:flex;align-items:center;gap:14px}
header h1{font-size:18px;margin:0;font-weight:600}a{color:#7dd3fc;text-decoration:none}
.wrap{max-width:1000px;margin:0 auto;padding:18px 20px}
input,textarea{background:#0f1115;color:#e6e6e6;border:1px solid #303643;border-radius:6px;padding:7px 9px;font-family:inherit;width:100%;box-sizing:border-box}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:7px 8px;border-bottom:1px solid #20252f}tr:hover{background:#151a22;cursor:pointer}
.muted{color:#6b7280}.pill{background:#22262e;color:#9aa4b2;border-radius:20px;padding:1px 8px;font-size:11px}
button{cursor:pointer;background:#2563eb;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:13px}button.sec{background:#374151}
dialog{background:#161a22;color:#e6e6e6;border:1px solid #303643;border-radius:12px;max-width:560px;width:92%}
label{display:block;font-size:12px;color:#9aa4b2;margin:10px 0 3px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
</style></head><body>
<header><h1>🧠 paperlaiss</h1><a href="/">← Dashboard</a><span class=muted>Korrespondenten</span></header>
<div class=wrap>
  <div class=row style="margin-bottom:12px"><input id=q placeholder="filtern…" oninput="render()" style="max-width:280px"></div>
  <table id=tbl></table>
</div>
<dialog id=dlg><form method=dialog style="padding:18px"><div style="display:flex;justify-content:space-between;align-items:center"><b id=dt></b><span class=muted id=dc></span></div>
  <div class=grid2>
    <div><label>E-Mail</label><input id=f_email></div>
    <div><label>Domains (Absender-Match, kommagetrennt)</label><input id=f_domains></div>
    <div><label>Telefon</label><input id=f_telefon></div>
    <div><label>Kundennummer</label><input id=f_kundennummer></div>
    <div><label>UID-Nr. (USt-IdNr.)</label><input id=f_ustid></div>
    <div><label>Quelle</label><input id=f_quelle placeholder="z.B. carddav, bmd — leer = hier gepflegt"></div>
    <div><label>Kennung in der Quelle</label><input id=f_extern_id></div>
    <div><label>Aliase (kommagetrennt)</label><input id=f_aliase></div>
  </div>
  <label>Adresse</label><input id=f_adresse>
  <label>Kontext (KI-Hinweis: was ist dieser Absender / welche Dokumente kommen von ihm)</label><textarea id=f_kontext rows=3></textarea>
  <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end"><button type=button class=sec onclick="dlg.close()">Abbrechen</button><button type=button onclick="save()">Speichern</button></div>
</form></dialog>
<script>
const F=["email","domains","telefon","adresse","kundennummer","ustid","kontext","aliase","quelle","extern_id"];
let DATA=[],cur=null;
async function load(){DATA=await (await fetch('/api/correspondents')).json();render()}
function render(){
  const q=document.getElementById('q').value.toLowerCase();
  const rows=DATA.filter(c=>!q||(c.name||'').toLowerCase().includes(q)||(c.kontext||'').toLowerCase().includes(q));
  document.getElementById('tbl').innerHTML=rows.map((c,i)=>{
    const has=F.some(f=>c[f]);const idx=DATA.indexOf(c);
    return `<tr onclick="edit(${idx})"><td><b>${c.name.replace(/</g,'&lt;')}</b> <span class=pill>${c.document_count} Docs</span></td>`+
      `<td class=muted>${(c.kontext||c.email||'').replace(/</g,'&lt;').slice(0,70)}</td>`+
      `<td style="text-align:right">${has?'✓ Metadaten':'<span class=muted>—</span>'}</td></tr>`;
  }).join('');
}
function edit(i){cur=DATA[i];document.getElementById('dt').textContent=cur.name;
  document.getElementById('dc').textContent='ID '+cur.id+' · '+cur.document_count+' Docs';
  F.forEach(f=>document.getElementById('f_'+f).value=cur[f]||'');document.getElementById('dlg').showModal();}
async function save(){
  const body={id:cur.id};F.forEach(f=>body[f]=document.getElementById('f_'+f).value);
  await fetch('/api/correspondents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  F.forEach(f=>cur[f]=body[f]);document.getElementById('dlg').close();render();
}
load();
</script></body></html>"""


@app.get("/korrespondenten", response_class=HTMLResponse)
def corr_page(request: Request):
    guard(request)
    return CORR_PAGE


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
<header><h1>🧠 paperlaiss</h1><a href="/korrespondenten" style="font-size:13px">Korrespondenten</a><span style="font-size:13px;color:#9aa4b2;margin-left:auto">Klassifizierer-Panel</span></header>
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
