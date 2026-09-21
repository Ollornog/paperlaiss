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

from kern import (auffaelligkeiten, config_uebernehmen, doc_hat_sich_geaendert,
                  doc_id_aus_webhook, feld_typ, merge_metadaten, verlauf)

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


PROP_DIR = os.path.join(os.path.dirname(LOG), "proposals")
# Eigenes Geheimnis fuer den Webhook — NICHT PANEL_TOKEN. Regel: ein Geheimnis, ein Bereich.
# Wer den Webhook kennt, soll damit nicht die Panel-API bedienen koennen.
REDO_SECRET = os.environ.get("REDO_SECRET", "")


def _cfg():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {}


def lade_vorschlaege():
    """Alle abgelegten Vorschlaege, neueste zuerst."""
    out = []
    for pfad in glob.glob(os.path.join(PROP_DIR, "*.json")):
        try:
            out.append(json.load(open(pfad, encoding="utf-8")))
        except Exception:
            continue          # eine kaputte Datei darf die Liste nicht sprengen
    out.sort(key=lambda v: v.get("ts", ""), reverse=True)
    return out


def raeume_ausloeser(doc_id, doc=None):
    """Ausloeser-Tag und Hinweisfeld entfernen — der Schleifenschutz des Vorschlagsmodus.

    Im Direktmodus macht das der Klassifizierer beim Schreiben. Im Vorschlagsmodus schreibt er
    nicht, also muss der ANSTOSS raeumen: sonst bleiben Tag und Feld stehen, und jedes weitere
    Update am Dokument loest den Webhook erneut aus. Gibt den gelesenen Hinweistext zurueck,
    damit er nicht verloren geht.
    """
    cfg = _cfg()
    doc = doc or api_get(f"/documents/{doc_id}/")
    hinweis = ""
    patch = {}

    redo_name = (cfg.get("redo_tag") or "").strip()
    if redo_name:
        tags = api_get("/tags/?page_size=1000")["results"]
        redo_id = next((t["id"] for t in tags if t["name"].strip().lower() == redo_name.lower()), None)
        if redo_id and redo_id in (doc.get("tags") or []):
            patch["tags"] = [t for t in doc["tags"] if t != redo_id]

    hinweis_name = (cfg.get("hinweis_field") or "").strip()
    if hinweis_name:
        felder = api_get("/custom_fields/?page_size=1000")["results"]
        hid = next((f["id"] for f in felder if f["name"].strip().lower() == hinweis_name.lower()), None)
        if hid:
            for c in (doc.get("custom_fields") or []):
                if c["field"] == hid:
                    hinweis = str(c.get("value") or "").strip()
            if hinweis:
                patch["custom_fields"] = [c for c in (doc.get("custom_fields") or [])
                                          if c["field"] != hid]
    if patch:
        api_send(f"/documents/{doc_id}/", patch, "PATCH")
    return hinweis


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
def run_classify(doc, force=True, force_ocr=False, source="manual", propose=False, hinweis=""):
    env = dict(os.environ)
    env.update({"CLASSIFY_DOC": str(doc), "PAPERLESS_API": BASE, "PAPERLESS_TOKEN": TOK,
                "MISTRAL_KEY": MISTRAL_KEY, "CLASSIFY_CONFIG": CONFIG, "CLASSIFY_LOG": LOG,
                "CLASSIFY_SOURCE": source})
    if force:
        env["CLASSIFY_FORCE"] = "1"
    if force_ocr:
        env["CLASSIFY_FORCE_OCR"] = "1"
    if propose:
        env["CLASSIFY_PROPOSE"] = "1"
    if hinweis:
        env["CLASSIFY_HINWEIS"] = hinweis
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


# ---------- Vorschlagsmodus ----------
# Die reine Logik steht in kern.py — dort ist sie ohne FastAPI testbar.


@app.post("/redo")
async def redo(request: Request, x_redo_secret: str = Header(None)):
    """Webhook-Ziel fuer den Paperless-Workflow: erzeugt einen VORSCHLAG statt zu schreiben.

    Reihenfolge ist der Schleifenschutz: erst Ausloeser-Tag und Hinweisfeld raeumen (und den
    Hinweistext dabei mitnehmen), dann klassifizieren. Andersherum blieben Tag und Feld bei
    einem verworfenen Vorschlag stehen und jedes weitere Update feuerte den Webhook erneut.
    """
    if not REDO_SECRET:
        raise HTTPException(503, "REDO_SECRET nicht gesetzt — der Webhook ist nicht konfiguriert.")
    if not hmac.compare_digest(x_redo_secret or "", REDO_SECRET):
        raise HTTPException(403, "falsches Redo-Secret")
    # Paperless sendet je nach Einstellung anders: `use_params=true` als Query-Parameter
    # oder Formularfeld, `as_json=true` mit `body` als (doppelt kodiertes) JSON. Statt eine
    # Form vorzuschreiben, werden alle drei gelesen — der Betreiber soll den Workflow
    # einrichten koennen, wie er mag.
    roh = (await request.body()).decode("utf-8", "replace")
    doc_id = None
    for kandidat in (request.query_params.get("doc_id"),
                     request.query_params.get("document_id"),
                     request.query_params.get("id")):
        if kandidat and str(kandidat).strip().isdigit():
            doc_id = int(kandidat)
            break
    if not doc_id and roh:
        doc_id = doc_id_aus_webhook(roh)
    if not doc_id and roh:
        # Formularfeld (application/x-www-form-urlencoded)
        from urllib.parse import parse_qs
        for schluessel, werte in parse_qs(roh).items():
            if schluessel in ("doc_id", "document_id", "id") and werte and werte[0].strip().isdigit():
                doc_id = int(werte[0])
                break
    if not doc_id:
        # Sagen, was ankam — sonst sucht man im Dunkeln, welche Webhook-Form eingestellt ist.
        print(f"redo: keine Dokument-ID. query={dict(request.query_params)} "
              f"body={roh[:200]!r}", file=sys.stderr)
        raise HTTPException(400, "keine Dokument-ID im Webhook gefunden "
                                 "(weder Query-Parameter noch Rumpf enthielten eine)")
    hinweis = raeume_ausloeser(doc_id)
    rc, out = run_classify(doc_id, force=True, source="redo", propose=True, hinweis=hinweis)
    return {"ok": rc == 0, "doc": doc_id, "hinweis": bool(hinweis), "output": out[-800:]}


@app.get("/api/proposals")
def get_proposals(request: Request):
    guard(request)
    return {"vorschlaege": lade_vorschlaege()}


@app.post("/api/proposals/{doc_id}/annehmen")
def annehmen(doc_id: int, request: Request):
    """Den abgelegten Patch ausfuehren — aber nur, wenn das Dokument sich nicht geaendert hat."""
    guard(request)
    pfad = os.path.join(PROP_DIR, f"{doc_id}.json")
    if not os.path.exists(pfad):
        raise HTTPException(404, "kein Vorschlag zu diesem Dokument")
    vorschlag = json.load(open(pfad, encoding="utf-8"))
    doc = api_get(f"/documents/{doc_id}/")
    if doc_hat_sich_geaendert(vorschlag, doc):
        raise HTTPException(409, "Das Dokument wurde seit dem Vorschlag geändert. "
                                 "Bitte neu klassifizieren, damit nichts überschrieben wird.")
    api_send(f"/documents/{doc_id}/", vorschlag["patch"], "PATCH")
    os.remove(pfad)
    return {"ok": True, "doc": doc_id, "angewendet": sorted(vorschlag["patch"].keys())}


@app.post("/api/proposals/{doc_id}/verwerfen")
def verwerfen(doc_id: int, request: Request):
    guard(request)
    pfad = os.path.join(PROP_DIR, f"{doc_id}.json")
    if not os.path.exists(pfad):
        raise HTTPException(404, "kein Vorschlag zu diesem Dokument")
    os.remove(pfad)
    return {"ok": True, "doc": doc_id}


def _log_zeilen(max_zeilen=20000):
    try:
        return open(LOG, encoding="utf-8", errors="replace").read().splitlines()[-max_zeilen:]
    except OSError:
        return []


@app.get("/api/verlauf")
def api_verlauf(request: Request, tage: int = 30):
    """Täglicher Verlauf plus die Auffälligkeiten — was lief, was schieflief, was gelöst ist."""
    guard(request)
    zeilen = _log_zeilen()
    auff = auffaelligkeiten(zeilen)
    return {"verlauf": verlauf(zeilen, tage=tage),
            "auffaelligkeiten": auff[:60],
            "offen": sum(1 for a in auff if not a["geloest"])}


@app.get("/api/config/schema")
def config_schema(request: Request):
    """Welches Eingabeelement passt zu welchem Schlüssel — abgeleitet aus dem aktuellen Wert.

    So muss die Oberfläche nicht jeden Schlüssel kennen: ein neuer Konfigurationswert erscheint
    von selbst mit dem passenden Feld, statt vergessen zu werden.
    """
    guard(request)
    cfg = _cfg_oeffentlich()
    return {"felder": [{"name": k, "typ": feld_typ(v), "wert": v} for k, v in sorted(cfg.items())],
            "geheim": list(GEHEIM_FELDER)}


EINST_PAGE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>paperlaiss — Einstellungen</title>
<style>
:root{color-scheme:dark}
body{background:#0f1115;color:#e6e6e6;font:14px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0}
header{display:flex;gap:14px;align-items:center;padding:14px 20px;border-bottom:1px solid #20252f}
h1{font-size:16px;margin:0}a{color:#60a5fa;text-decoration:none}
.wrap{max-width:860px;margin:20px auto;padding:0 16px}
.f{background:#161a22;border:1px solid #303643;border-radius:10px;padding:12px 14px;margin-bottom:10px}
.f label{display:block;font-size:13px;color:#e6e6e6;margin-bottom:6px;font-weight:600}
.f .hilfe{font-size:12px;color:#6b7280;margin-bottom:6px}
input[type=text],textarea{background:#0f1115;color:#e6e6e6;border:1px solid #303643;border-radius:6px;
  padding:8px 10px;font-family:inherit;font-size:13px;width:100%;box-sizing:border-box}
textarea{min-height:90px;resize:vertical}
input[type=checkbox]{width:16px;height:16px;vertical-align:-2px}
button{cursor:pointer;background:#2563eb;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-size:13px}
.leiste{position:sticky;bottom:0;background:#0f1115;border-top:1px solid #20252f;padding:12px 0;
  display:flex;gap:12px;align-items:center}
.muted{color:#6b7280}.warn{color:#fcd34d}
</style></head><body>
<header><h1>Einstellungen</h1><a href="/">← Dashboard</a>
  <span class=muted style="margin-left:auto;font-size:12px">classify-config.json</span></header>
<div class=wrap><div id=z>lädt…</div>
  <div class=leiste><button onclick="sichern()">Speichern</button><span id=meld class=muted></span></div>
</div>
<script>
let FELDER=[];
function txt(v){return String(v==null?'':v).replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]))}
const HILFE={
  system_prompt:'Leer = eingebauter Standardprompt. Hier gehört der installationseigene Kontext hin — NICHT in den Code.',
  korrespondent_beispiele:'Beispielpaare für den Abgleich, z.B. [["Mustrmann GmbH","Mustermann"]]. Hilft bei OCR-Fehlern mehr als jede Beschreibung.',
  manual_fields:'Felder, die die KI NIE anfasst — rein manuell gepflegt.',
  reserved_tags:'Tags, die die KI nie vergibt und die beim Schreiben erhalten bleiben.',
  nachbearbeitung:'Pfad zu einem Skript, das nach dem Schreiben läuft. Die Naht für alles, was nur diese Installation braucht.',
  tagging_enabled:'Aus: die KI vergibt keine inhaltlichen Tags.',
  ocr_always:'OCR bei JEDEM Dokument — kostet, auch wenn der Text gut ist.',
};
fetch('/api/config/schema').then(r=>r.json()).then(d=>{
  FELDER=d.felder;
  document.getElementById('z').innerHTML=FELDER.map(f=>{
    const h=HILFE[f.name]?`<div class=hilfe>${txt(HILFE[f.name])}</div>`:'';
    let e;
    if(f.typ==='bool') e=`<input type=checkbox id="f_${f.name}" ${f.wert?'checked':''}>`;
    else if(f.typ==='text') e=`<textarea id="f_${f.name}">${txt(f.wert)}</textarea>`;
    else if(f.typ==='json') e=`<textarea id="f_${f.name}">${txt(JSON.stringify(f.wert,null,1))}</textarea>`;
    else e=`<input type=text id="f_${f.name}" value="${txt(f.wert)}">`;
    return `<div class=f><label for="f_${f.name}">${txt(f.name)} <span class=muted>(${f.typ})</span></label>${h}${e}</div>`;
  }).join('')+
  `<p class=muted style="font-size:12px">Nicht hier: ${d.geheim.join(', ')} — Schlüssel gehören in die Umgebung, nicht in eine Datei, die eine Weboberfläche lesen kann.</p>`;
});
async function sichern(){
  const meld=document.getElementById('meld'); meld.className='muted'; meld.textContent='speichere…';
  const body={};
  FELDER.forEach(f=>{
    const el=document.getElementById('f_'+f.name);
    body[f.name] = f.typ==='bool' ? el.checked : el.value;
  });
  try{
    const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)});
    if(!r.ok) throw new Error(await r.text());
    const d=await r.json();
    if((d.uebergangen||[]).length){
      meld.className='warn';
      meld.textContent='gespeichert, aber übergangen: '+d.uebergangen.join(', ');
    } else { meld.textContent='✓ gespeichert'; }
  }catch(e){ meld.className='warn'; meld.textContent=String(e.message||e).slice(0,160); }
}
</script></body></html>"""


@app.get("/einstellungen", response_class=HTMLResponse)
def einstellungen(request: Request):
    guard(request)
    return EINST_PAGE


TRACE_PAGE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>paperlaiss — Lauf __ID__</title>
<style>
:root{color-scheme:dark}
body{background:#0f1115;color:#e6e6e6;font:14px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0}
header{display:flex;gap:14px;align-items:center;padding:14px 20px;border-bottom:1px solid #20252f}
h1{font-size:16px;margin:0}a{color:#60a5fa;text-decoration:none}
.wrap{max-width:1000px;margin:20px auto;padding:0 16px}
.schritt{background:#161a22;border:1px solid #303643;border-radius:10px;margin-bottom:12px;overflow:hidden}
.schritt>summary{padding:12px 14px;cursor:pointer;font-weight:600;list-style:none;display:flex;gap:10px;align-items:center}
.schritt>summary::-webkit-details-marker{display:none}
.schritt>summary::before{content:'▸';color:#6b7280}
.schritt[open]>summary::before{content:'▾'}
.inhalt{padding:0 14px 14px}
pre{white-space:pre-wrap;word-break:break-word;font-size:12px;background:#0f1115;padding:10px;
    border-radius:8px;max-height:44vh;overflow:auto;margin:6px 0}
.muted{color:#6b7280;font-weight:400}
.marke{background:#22262e;color:#9aa4b2;border-radius:20px;padding:1px 9px;font-size:11px;font-weight:400}
.marke.ok{background:#064e3b;color:#6ee7b7}.marke.warn{background:#78350f;color:#fcd34d}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:8px 0;font-size:13px}
dt{color:#9aa4b2}dd{margin:0}
</style></head><body>
<header><h1>Lauf __ID__</h1><a href="/">← Dashboard</a><span class=muted id=ts></span></header>
<div class=wrap id=z>lädt…</div>
<script>
const ID=__ID__;
function txt(v){return String(v==null?'':v).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
function pre(o){return '<pre>'+txt(typeof o==='string'?o:JSON.stringify(o,null,2))+'</pre>'}
function schritt(titel,marke,inhalt,offen){
  return `<details class=schritt ${offen?'open':''}><summary>${txt(titel)}`+
         (marke?` <span class="marke ${marke[1]||''}">${txt(marke[0])}</span>`:'')+
         `</summary><div class=inhalt>${inhalt}</div></details>`;
}
fetch('/api/trace/'+ID).then(r=>r.json()).then(d=>{
  if(d.error){document.getElementById('z').innerHTML='<p class=muted>Kein Trace zu diesem Dokument.</p>';return}
  document.getElementById('ts').textContent=d.ts||'';
  let h='';
  const o=d.ocr||{};
  h+=schritt('1 · OCR', [o.triggered?'nachgeholt':'übersprungen', o.triggered?'warn':''],
     `<dl><dt>Grund</dt><dd>${txt(o.grund)}</dd>`+
     (o.chars?`<dt>Zeichen</dt><dd>${txt(o.chars)}</dd>`:'')+
     (o.ki_meldet_unlesbar!==undefined?`<dt>KI meldet unlesbar</dt><dd>${txt(o.ki_meldet_unlesbar)} `+
       `<span class=muted>(Heuristik stimmt zu: ${txt(o.heuristik_stimmt_zu)})</span></dd>`:'')+
     `</dl>`+(o.excerpt?pre(o.excerpt):''));
  if(d.pass0) h+=schritt('2 · Absender vorab', null, pre(d.pass0));
  const p1=d.pass1||{};
  h+=schritt('3 · Klassifizierung', null,
     `<div class=muted>System-Prompt (${(p1.system||'').length} Zeichen)</div>${pre(p1.system||'')}`+
     `<div class=muted>Dokument (gekürzt)</div>${pre(p1.user||'')}`+
     `<div class=muted>Antwort</div>${pre(p1.response||{})}`);
  const k=d.correspondent||{};
  h+=schritt('4 · Korrespondent', [k.ergebnis&&k.ergebnis.startsWith('exakt')?'exakt':'zugeordnet',
     k.ergebnis&&k.ergebnis.startsWith('NEU')?'warn':'ok'],
     `<dl><dt>Vorschlag</dt><dd>${txt(k.vorschlag)}</dd><dt>Ergebnis</dt><dd>${txt(k.ergebnis)}</dd></dl>`+
     (k.pass2?`<div class=muted>Rückfrage ans Modell</div>${pre(k.pass2)}`:''), true);
  const w=d.writeback||{};
  h+=schritt('5 · Zurückgeschrieben', [w.modus==='vorschlag'?'als Vorschlag':'geschrieben',
     w.modus==='vorschlag'?'warn':'ok'], pre(w), true);
  const rep=d.repair||[];
  if(rep.length) h+=schritt(`6 · Reparatur (${rep.length} Runden)`,
     [rep[rep.length-1].ok?'gelöst':'gescheitert', rep[rep.length-1].ok?'ok':'warn'], pre(rep), true);
  document.getElementById('z').innerHTML=h;
});
</script></body></html>"""


@app.get("/trace/{doc_id}", response_class=HTMLResponse)
def trace_seite(doc_id: int, request: Request):
    """Der Lauf Schritt für Schritt — was die KI sah, was sie antwortete, was geschrieben wurde.

    `/api/trace/{id}` liefert dasselbe als JSON. Für die Fehlersuche ist die Frage aber fast immer
    „an welcher Stelle ist es gekippt", und die beantwortet eine gegliederte Ansicht schneller als
    ein 4000-Zeichen-Block.
    """
    guard(request)
    return TRACE_PAGE.replace("__ID__", str(int(doc_id)))


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
    # Typsicher zurückwandeln: ein Formular liefert Text, die Konfiguration braucht Zahlen,
    # Wahrheitswerte und Listen. Was sich nicht umwandeln lässt, wird übergangen und gemeldet —
    # ein Tippfehler darf keinen Schlüssel zerstören.
    cfg, uebergangen = config_uebernehmen(_cfg(), body)
    schreibe_json(CONFIG, cfg)
    return {"ok": True, "config": _cfg_oeffentlich(), "uebergangen": uebergangen}


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


@app.post("/api/correspondents/merge")
async def merge_correspondents(request: Request):
    """Mehrere Korrespondenten zu einem verschmelzen: Dokumente umhängen, Dubletten löschen.

    Warum das ins Panel gehört: Der Korrespondent-Feedback-Loop verhindert neue Dubletten, räumt
    aber keine alten auf. Über die Paperless-Oberfläche ist das Handarbeit pro Dokument.

    Der Metadaten-Store hängt an der Paperless-ID, nicht am Namen — das Verschmelzen ist deshalb
    ein Zusammenführen von Einträgen und kein Umbenennen von Schlüsseln.
    """
    guard(request)
    body = await request.json()
    ids = [int(x) for x in (body.get("ids") or []) if str(x).strip().isdigit()]
    ziel = int(body["ziel"]) if str(body.get("ziel", "")).strip().isdigit() else None
    if len(ids) < 2 or ziel is None or ziel not in ids:
        raise HTTPException(400, "mindestens zwei IDs und ein Ziel aus dieser Auswahl nötig")

    alle = {c["id"]: c for c in api_get("/correspondents/?page_size=2000")["results"]}
    fehlend = [i for i in ids if i not in alle]
    if fehlend:
        raise HTTPException(404, f"unbekannte Korrespondenten: {fehlend}")

    quellen = [i for i in ids if i != ziel]
    umgehaengt = 0
    for dup in quellen:
        docs = api_get(f"/documents/?correspondent__id__in={dup}&fields=id&page_size=2000")["results"]
        dids = [d["id"] for d in docs]
        if dids:
            api_send("/documents/bulk_edit/", {"documents": dids, "method": "set_correspondent",
                                               "parameters": {"correspondent": ziel}}, "POST")
            umgehaengt += len(dids)

    # Erst den Store zusammenführen, DANN löschen: bricht etwas dazwischen ab, sind die
    # Metadaten gerettet und die Dublette steht noch da — der umgekehrte Fall wäre Datenverlust.
    store = load_corr_store()
    verschmolzen = merge_metadaten(store.get(str(ziel), {}),
                                   [store.get(str(q), {}) for q in quellen])
    if verschmolzen:
        store[str(ziel)] = verschmolzen
    for q in quellen:
        store.pop(str(q), None)
    save_corr_store(store)

    geloescht = []
    for dup in quellen:
        try:
            api_send(f"/correspondents/{dup}/", {}, "DELETE")
            geloescht.append(dup)
        except Exception as e:
            # Nicht abbrechen: die Dokumente hängen bereits am Ziel, eine übrig gebliebene
            # leere Dublette ist ein Schönheitsfehler, kein Datenverlust.
            print(f"merge: {dup} nicht löschbar: {e!r}", file=sys.stderr)
    return {"ok": True, "ziel": ziel, "name": alle[ziel]["name"],
            "umgehaengt": umgehaengt, "geloescht": geloescht,
            "nicht_geloescht": [q for q in quellen if q not in geloescht]}


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
  <div class=row style="margin-bottom:12px">
    <input id=q placeholder="filtern…" oninput="render()" style="max-width:280px">
    <span id=msel class=muted style="font-size:13px"></span>
    <button id=mbtn style="display:none" onclick="merge()">Zusammenführen</button>
  </div>
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
const SEL=new Set();
function render(){
  const q=document.getElementById('q').value.toLowerCase();
  const rows=DATA.filter(c=>!q||(c.name||'').toLowerCase().includes(q)||(c.kontext||'').toLowerCase().includes(q));
  document.getElementById('tbl').innerHTML=rows.map((c,i)=>{
    const has=F.some(f=>c[f]);const idx=DATA.indexOf(c);
    return `<tr><td style="width:28px" onclick="event.stopPropagation()"><input type=checkbox ${SEL.has(c.id)?'checked':''} onchange="pick(${c.id},this.checked)"></td>`+
      `<td onclick="edit(${idx})"><b>${c.name.replace(/</g,'&lt;')}</b> <span class=pill>${c.document_count} Docs</span></td>`+
      `<td class=muted onclick="edit(${idx})">${(c.kontext||c.email||'').replace(/</g,'&lt;').slice(0,70)}</td>`+
      `<td style="text-align:right" onclick="edit(${idx})">${has?'✓ Metadaten':'<span class=muted>—</span>'}</td></tr>`;
  }).join('');
  const n=SEL.size;
  document.getElementById('msel').textContent = n ? `${n} ausgewählt` : '';
  document.getElementById('mbtn').style.display = n>=2 ? '' : 'none';
}
function pick(id,an){ an?SEL.add(id):SEL.delete(id); render(); }

async function merge(){
  const ids=[...SEL];
  const namen=ids.map(i=>(DATA.find(c=>c.id===i)||{}).name).filter(Boolean);
  // Das Ziel muss der Mensch wählen: seine Metadaten bleiben, seine Kundennummer gewinnt.
  const wahl=prompt(`Welcher Eintrag soll bleiben?\n\n`+
    namen.map((n,i)=>`${i+1}) ${n}`).join('\n')+`\n\nNummer eingeben:`);
  const nr=parseInt(wahl,10);
  if(!nr||nr<1||nr>ids.length) return;
  const ziel=ids[nr-1];
  const rest=namen.filter((_,i)=>i!==nr-1).join(', ');
  if(!confirm(`„${namen[nr-1]}" behalten.\n\nDokumente von ${rest} werden umgehängt, `+
              `diese Einträge danach gelöscht.\n\nFortfahren?`)) return;
  const el=document.getElementById('msel'); el.textContent='führe zusammen…';
  try{
    const r=await fetch('/api/correspondents/merge',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({ids,ziel})});
    if(!r.ok) throw new Error(await r.text());
    const d=await r.json();
    el.textContent=`${d.umgehaengt} Dokumente auf „${d.name}" umgehängt`;
    SEL.clear(); await load();
  }catch(e){ el.textContent=String(e.message||e).slice(0,140); }
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
.bars{display:flex;gap:3px;align-items:flex-end;height:90px;margin:10px 0 4px}
/* max-width, damit wenige Tage nicht die ganze Breite fuellen: bei zwei Eintraegen sah der
   Verlauf sonst aus wie zwei Bloecke statt wie ein Verlauf. */
.bars .t{flex:1;display:flex;flex-direction:column-reverse;gap:1px;min-width:4px;max-width:26px}
.bars .t .leer{background:#20252f;height:2px}
.bars i{display:block;border-radius:1px}
.bars .ok{background:#2563eb}.bars .ocr{background:#7c3aed}.bars .err{background:#dc2626}
.legende{display:flex;gap:14px;font-size:12px;color:#9aa4b2;margin-bottom:6px}
.legende b{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}
.auff{font-size:12px;border-left:2px solid #dc2626;padding:4px 10px;margin:4px 0;background:#161a22}
.auff.geloest{border-color:#059669;opacity:.55}
.vk{background:#161a22;border:1px solid #303643;border-radius:10px;padding:14px;margin-bottom:10px}
.vk h3{margin:0 0 4px;font-size:15px}
.vk .hinweis{background:#1f2937;border-left:3px solid #2563eb;padding:8px 10px;border-radius:0 6px 6px 0;margin:8px 0;font-size:13px}
.vk dl{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;margin:8px 0 0;font-size:13px}
.vk dt{color:#9aa4b2}.vk dd{margin:0}
.vk .akt{display:flex;gap:8px;margin-top:12px;align-items:center}
.muted{color:#6b7280}.pill{background:#22262e;color:#9aa4b2;border-radius:20px;padding:1px 8px;font-size:11px}
</style></head><body>
<header><h1>🧠 paperlaiss</h1><a href="/korrespondenten" style="font-size:13px">Korrespondenten</a><a href="/einstellungen" style="font-size:13px">Einstellungen</a><span style="font-size:13px;color:#9aa4b2;margin-left:auto">Klassifizierer-Panel</span></header>
<div class=wrap>
  <div class=banner id=banner>…</div>
  <div class=cards id=cards></div>
  <h2>Verlauf <span class=pill id=voffen style="display:none"></span></h2>
  <div id=verlauf class=muted style="font-size:13px">lädt…</div>

  <h2>Manuell klassifizieren</h2>
  <div class=row>
    <input id=docid placeholder="Doc-ID" style="width:110px">
    <button onclick="rc('classify')">Neu klassifizieren</button>
    <button class=sec onclick="rc('ocr')">mit OCR erzwingen</button>
    <span id=rcout style="font-size:12px;color:#9aa4b2"></span>
  </div>
  <h2>Vorschläge <span class=pill id=vzahl style="display:none"></span></h2>
  <div id=vorschlaege><div class=muted style="font-size:13px">Keine offenen Vorschläge.</div></div>

  <h2>Aktivität</h2>
  <table id=feed></table>
</div>
<dialog id=dlg><div style="padding:16px"><div class=row style="justify-content:space-between"><b id=dlgt></b><button class=sec onclick="dlg.close()">×</button></div><pre id=dlgc></pre></div></dialog>
<script>
const badge=k=>`<span class="badge ${k}">${k}</span>`;
async function j(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error(await r.text());return r.json()}
function txt(v){return String(v==null?'':v).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}

async function ladeVerlauf(){
  let d; try{ d = await j('/api/verlauf'); }catch(e){ return; }
  const v=d.verlauf||[];
  const z=document.getElementById('verlauf');
  if(!v.length){ z.innerHTML='<span class=muted>Noch keine Läufe im Log.</span>'; return; }
  const max=Math.max(...v.map(t=>(t.klassifiziert||0)+(t.ocr||0)+(t.fehler||0)),1);
  const h=v.map(t=>{
    const k=t.klassifiziert||0,o=t.ocr||0,f=t.fehler||0;
    const px=n=>Math.round(n/max*84);
    return `<div class=t title="${t.tag}: ${k} klassifiziert, ${o} OCR, ${f} Fehler">`+
      (f?`<i class=err style="height:${px(f)}px"></i>`:'')+
      (o?`<i class=ocr style="height:${px(o)}px"></i>`:'')+
      (k?`<i class=ok style="height:${px(k)}px"></i>`:'')+
      (!(k||o||f)?`<i class=leer></i>`:'')+`</div>`;
  }).join('');
  const offen=d.offen||0;
  const marke=document.getElementById('voffen');
  marke.style.display = offen ? '' : 'none';
  marke.textContent = offen + ' offen';
  const auff=(d.auffaelligkeiten||[]).slice(0,8).map(a=>
    `<div class="auff ${a.geloest?'geloest':''}">${txt(a.ts)} `+
    (a.doc?`<a href="/trace/${txt(a.doc)}">#${txt(a.doc)}</a> `:'')+
    `${txt(a.text)}${a.geloest?' <span class=muted>— später gelöst</span>':''}</div>`).join('');
  z.innerHTML=`<div class=legende><span><b class=ok style="background:#2563eb"></b>klassifiziert</span>`+
    `<span><b style="background:#7c3aed"></b>OCR</span><span><b style="background:#dc2626"></b>Fehler</span>`+
    `<span class=muted style="margin-left:auto">${v[0].tag} – ${v[v.length-1].tag}</span></div>`+
    `<div class=bars>${h}</div>`+(auff?`<div style="margin-top:10px">${auff}</div>`:'');
}

async function ladeVorschlaege(){
  let d;
  try{ d = await j('/api/proposals'); }catch(e){ return; }
  const v = d.vorschlaege||[];
  const zahl=document.getElementById('vzahl');
  zahl.style.display = v.length ? '' : 'none';
  zahl.textContent = v.length;
  const ziel=document.getElementById('vorschlaege');
  if(!v.length){ ziel.innerHTML='<div class=muted style="font-size:13px">Keine offenen Vorschläge.</div>'; return; }
  ziel.innerHTML = v.map(p=>{
    const L=p.lesbar||{};
    const felder=Object.entries(L.felder||{}).filter(([k,w])=>w!=='behalten');
    return `<div class=vk id="vk${p.id}">
      <h3>#${p.id} · ${txt(L.titel)}</h3>
      <div class=muted style="font-size:12px">${txt(p.ts)} · ausgelöst durch ${txt(p.quelle)}</div>
      ${p.hinweis?`<div class=hinweis>Dein Hinweis: „${txt(p.hinweis)}"</div>`:''}
      <dl>
        ${L.korrespondent?`<dt>Korrespondent</dt><dd>${txt(L.korrespondent)}</dd>`:''}
        ${L.dokumenttyp?`<dt>Dokumenttyp</dt><dd>${txt(L.dokumenttyp)}</dd>`:''}
        ${L.datum?`<dt>Datum</dt><dd>${txt(L.datum)}</dd>`:''}
        ${(L.neue_tags||[]).length?`<dt>neue Tags</dt><dd>${(L.neue_tags||[]).map(txt).join(', ')}</dd>`:''}
        ${felder.length?`<dt>Felder</dt><dd>${felder.map(([k,w])=>`${txt(k)} = <b>${txt(w)}</b>`).join('<br>')}</dd>`:''}
        ${L.zusammenfassung?`<dt>Zusammenfassung</dt><dd>${txt(L.zusammenfassung)}</dd>`:''}
      </dl>
      <div class=akt>
        <button onclick="entscheide(${p.id},'annehmen')">Übernehmen</button>
        <button class=sec onclick="entscheide(${p.id},'verwerfen')">Verwerfen</button>
        <span class=muted id="vm${p.id}" style="font-size:12px"></span>
      </div></div>`;
  }).join('');
}

async function entscheide(id, was){
  const meld=document.getElementById('vm'+id);
  meld.textContent='…';
  try{
    await j(`/api/proposals/${id}/${was}`,{method:'POST'});
    document.getElementById('vk'+id).remove();
    await ladeVorschlaege(); await load();
  }catch(e){
    // 409 = das Dokument hat sich seit dem Vorschlag geaendert. Das ist kein Fehler,
    // sondern der Schutz davor, eine Handkorrektur stillschweigend zu ueberschreiben.
    // Zeichenklassen ausgeschrieben statt als Kurzform: dieser HTML-Block ist ein
    // normaler Python-String, Kurzformen mit Rueckstrich loesen dort eine SyntaxWarning aus.
    meld.textContent = String(e.message||e).replace(/^[0-9]+[ ]*/,'').slice(0,160);
  }
}

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
      // Auf die gegliederte Ansicht statt in einen JSON-Block: bei der Fehlersuche ist die
      // Frage fast immer "an welcher Stelle ist es gekippt".
      const d=e.doc?`<a href="/trace/${e.doc}">${e.doc}</a>`:'—';
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

load(); ladeVorschlaege(); ladeVerlauf();
setInterval(ladeVorschlaege, 15000);setInterval(ladeVerlauf, 60000);setInterval(load,6000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    guard(request)
    return PAGE
