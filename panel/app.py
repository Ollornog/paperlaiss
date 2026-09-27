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
  PANEL_TOKEN     Bearer-Token (bzw. Cookie panel_token) für UI/API; fehlt er, antwortet das Panel 503
  PANEL_AUTH      leer = PANEL_TOKEN · none = Anmeldung hängt davor · tinysesam = eigene Anmeldeseite
                  (PocketID/OIDC über PANEL_OIDC_*, Passwort nur mit PANEL_PASSWORD_LOGIN=1;
                  alle Variablen: README, Abschnitt Panel-Anmeldung)
  INGEST_TOKENS   optional JSON {"<token>": "<Quelle-Tag>"} für die Ingest-API
"""
import os, sys, json, re, glob, html, hmac, subprocess, datetime, tempfile, threading, urllib.request, urllib.error
from fastapi import BackgroundTasks, FastAPI, Request, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from kern import (aktivitaet, auffaelligkeiten, auth_einstellungen, ausloeser_auswerten,
                  config_uebernehmen, doc_id_aus_webhook, feld_typ, verlauf)
import huelle
import seiten

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
# Aussehen: vendortes C22 (scripts/vendor-c22.sh). Ohne Anmeldung, wie das Logo — die
# Anmeldeseite braucht es, bevor jemand angemeldet ist, und es enthält nichts Schützenswertes.
_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC):
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

AUTH = auth_einstellungen(os.environ)
if AUTH["fehler"]:
    sys.exit("paperlaiss-panel: Anmeldung falsch konfiguriert — " + "; ".join(AUTH["fehler"]))
SESAM = None
if AUTH["modus"] == "tinysesam":
    # Erst hier importiert: wer PANEL_AUTH nicht auf tinysesam stellt, braucht das Paket nicht.
    from tinysesam import TinySesam, TinySesamConfig
    os.makedirs(os.path.dirname(os.path.abspath(AUTH["tinysesam"]["db_path"])), exist_ok=True)
    SESAM = TinySesam(TinySesamConfig(**AUTH["tinysesam"]))
    if AUTH["admin"]:
        # Legt das Konto nur an, solange die Datenbank leer ist — ein spaeter geaendertes
        # Passwort in der Umgebung ueberschreibt also nichts.
        SESAM.ensure_admin(*AUTH["admin"])
    app.include_router(SESAM.router())
elif not PANEL_TOKEN and PANEL_AUTH != "none":
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


# Eigenes Geheimnis fuer den Webhook — NICHT PANEL_TOKEN. Regel: ein Geheimnis, ein Bereich.
# Wer den Webhook kennt, soll damit nicht die Panel-API bedienen koennen.
REDO_SECRET = os.environ.get("REDO_SECRET", "")


def _cfg():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {}


def raeume_ausloeser(doc_id, doc=None):
    """Auslöser lesen und entfernen, BEVOR der Lauf startet — der Schleifenschutz.

    Der Lauf dauert mit OCR leicht eine Minute. Stuenden Tag und Feld so lange noch am Dokument,
    loeste jede Bearbeitung in dieser Zeit den Webhook erneut aus. Gibt (modus, hinweis) zurueck;
    die Entscheidung steht in kern.ausloeser_auswerten().
    """
    cfg = _cfg()
    doc = doc or api_get(f"/documents/{doc_id}/")

    def tag_id(name):
        name = (name or "").strip().lower()
        if not name:
            return None
        return next((t["id"] for t in api_get("/tags/?page_size=1000")["results"]
                     if t["name"].strip().lower() == name), None)

    hinweis_fid = None
    hinweis_name = (cfg.get("hinweis_field") or "").strip().lower()
    if hinweis_name:
        hinweis_fid = next((f["id"] for f in api_get("/custom_fields/?page_size=1000")["results"]
                            if f["name"].strip().lower() == hinweis_name), None)
    modus, hinweis, patch = ausloeser_auswerten(doc.get("tags"), doc.get("custom_fields"),
                                                tag_id(cfg.get("redo_tag")), tag_id(cfg.get("ocr_tag")),
                                                hinweis_fid, tag_id(cfg.get("marker_tag")))
    if patch:
        api_send(f"/documents/{doc_id}/", patch, "PATCH")
    return modus, hinweis


def _cfg_oeffentlich():
    """Die WIRKSAME Config ohne Geheimnisfelder — Datei plus Vorgaben des Klassifizierers.

    Nur die Datei zu zeigen hiesse: jeder Wert, der noch auf seiner Vorgabe steht (ocr_regeln,
    ocr_tag …), fehlte in der Oberflaeche und liesse sich nicht einstellen. Die Vorgaben kennt
    nur classify.py selbst, also fragt das Panel dort (CLASSIFY_DUMP_CONFIG=1).
    """
    env = dict(os.environ, CLASSIFY_DUMP_CONFIG="1", CLASSIFY_CONFIG=CONFIG, CLASSIFY_LOG=LOG)
    try:
        r = subprocess.run(["python3", CLASSIFY_PY], env=env, capture_output=True, text=True, timeout=30)
        wirksam = json.loads(r.stdout)
    except Exception:
        wirksam = _cfg()          # Rückfall: wenigstens die Datei
    return {k: v for k, v in wirksam.items() if k not in GEHEIM_FELDER}


def guard(request: Request):
    """Panel-Schutz (Bearer PANEL_TOKEN).

    Faellt GESCHLOSSEN aus: ohne Token antwortet das Panel mit 503 statt offen zu stehen.
    Bis 2026-09-21 war es umgekehrt („leer = offen") — im Testbett lief das Panel dadurch
    ohne jede Anmeldung im LAN, mit Lesezugriff auf die Korrespondent-Kontaktdaten und
    Schreibzugriff auf system_prompt (= Prompt-Injektion in jede kuenftige Klassifizierung).
    """
    if SESAM is not None:
        # Ein gesetzter PANEL_TOKEN bleibt als Zugang fuer Skripte gueltig.
        if PANEL_TOKEN and _token_passt(request):
            return
        SESAM.require_user(request)     # Browser → Anmeldeseite, API-Aufrufe → 401
        return
    if not PANEL_TOKEN:
        if PANEL_AUTH == "none":
            return                      # bewusst offen, Anmeldung haengt davor
        raise HTTPException(503, "Panel nicht konfiguriert: PANEL_TOKEN fehlt "
                                 "(oder PANEL_AUTH=none setzen, wenn eine Anmeldung davorhaengt).")
    if _token_passt(request):
        return
    raise HTTPException(401, "Panel-Token nötig")


def seite(titel, aktiv, inhalt):
    """Eine Panel-Seite in der C22-Hülle — gleiche Navigation überall, die aktive hinterlegt."""
    return HTMLResponse(huelle.seite(titel, aktiv, inhalt, abmelden=SESAM is not None))


def _token_passt(request: Request) -> bool:
    if not PANEL_TOKEN:
        return False                    # sonst passt ein fehlendes Cookie auf einen leeren Token
    auth = request.headers.get("authorization", "")
    cookie = request.cookies.get("panel_token", "")
    # compare_digest statt ==: gleiche Laufzeit unabhaengig davon, ab welchem Zeichen es abweicht
    return (hmac.compare_digest(auth, f"Bearer {PANEL_TOKEN}")
            or hmac.compare_digest(cookie, PANEL_TOKEN))


# ---------- Paperless-API ----------
def api_get(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Token {TOK}"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def api_send(path, data, method="POST"):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
        headers={"Authorization": f"Token {TOK}", "Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=30))


# ---------- Log-Parser ----------
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
def run_classify(doc, force=True, force_ocr=False, source="manual", hinweis="", nur_ocr=False):
    env = dict(os.environ)
    env.update({"CLASSIFY_DOC": str(doc), "PAPERLESS_API": BASE, "PAPERLESS_TOKEN": TOK,
                "MISTRAL_KEY": MISTRAL_KEY, "CLASSIFY_CONFIG": CONFIG, "CLASSIFY_LOG": LOG,
                "CLASSIFY_SOURCE": source})
    if force:
        env["CLASSIFY_FORCE"] = "1"
    if force_ocr:
        env["CLASSIFY_FORCE_OCR"] = "1"
    if hinweis:
        env["CLASSIFY_HINWEIS"] = hinweis
    if nur_ocr:
        env["CLASSIFY_NUR_OCR"] = "1"
    try:
        r = subprocess.run(["python3", CLASSIFY_PY], env=env, capture_output=True, text=True, timeout=300)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, repr(e)


# ---------- Endpoints ----------
@app.get("/logo.png")
def logo():
    # Ohne guard(): die Anmeldeseite zeigt das Bild, bevor jemand angemeldet ist.
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "paperlaiss.png"),
                        media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
def health():
    return {"ok": True, "config": os.path.exists(CONFIG), "classify": os.path.exists(CLASSIFY_PY)}


_TYPEN = {"zeit": 0.0, "namen": {}}


def typ_namen():
    """Dokumenttyp-ID → Name für die Aktivitätsliste; fünf Minuten zwischengespeichert."""
    import time
    if time.time() - _TYPEN["zeit"] > 300:
        try:
            _TYPEN["namen"] = {str(t["id"]): t["name"]
                               for t in api_get("/document_types/?page_size=1000")["results"]}
            _TYPEN["zeit"] = time.time()
        except Exception:
            pass
    return _TYPEN["namen"]


@app.get("/api/aktivitaet")
def api_aktivitaet(request: Request, art: str = "", tag: str = "", doc: str = "",
                   seite: int = 1, je: int = 100):
    """Aktivitätsliste, gefiltert und in Seiten (Vorgabe 100). Logik: kern.aktivitaet()."""
    guard(request)
    d = aktivitaet(_log_zeilen(), art=art or None, tag=tag or None,
                   doc=int(doc) if doc.strip().isdigit() else None, seite=seite, je=min(max(je, 10), 500))
    d["typen"] = typ_namen()
    return d


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


# Wie viele Laeufe aus Paperless gleichzeitig laufen. Eine Mehrfachauswahl in Paperless schickt je
# Dokument einen Webhook; ohne Grenze starteten 50 markierte Dokumente 50 OCR-Laeufe auf einmal —
# Mistral drosselt dann, und der Container haelt 50 Prozesse offen.
PARALLEL = threading.BoundedSemaphore(max(1, int(os.environ.get("PANEL_PARALLEL") or 2)))


def run_classify_begrenzt(*args, **kwargs):
    with PARALLEL:
        return run_classify(*args, **kwargs)


# ---------- Neu klassifizieren aus Paperless ----------
# Die reine Logik steht in kern.py — dort ist sie ohne FastAPI testbar.


@app.post("/redo", status_code=202)
async def redo(request: Request, hintergrund: BackgroundTasks, x_redo_secret: str = Header(None)):
    """Webhook-Ziel fuer den Paperless-Workflow: neu klassifizieren, IMMER mit Mistral-OCR.

    Wer den Knopf drueckt, will genau dieses Dokument neu gelesen haben — also OCR, auch wenn
    der vorhandene Text den Regeln genuegt. Der optionale Hinweis geht als Zusatz in den Prompt.
    Geschrieben wird direkt. Der Lauf startet im Hintergrund (202): mit OCR dauert er laenger,
    als Paperless auf die Antwort eines Webhooks wartet.
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
    modus, hinweis = raeume_ausloeser(doc_id)
    if modus is None:
        # Der Workflow feuert bei JEDER Aenderung, die zu einem Ausloeser passt — auch bei der,
        # mit der wir die Ausloeser gerade selbst entfernt haben. Dann gibt es nichts zu tun.
        return {"ok": True, "doc": doc_id, "gestartet": False}
    hintergrund.add_task(run_classify_begrenzt, doc_id, force=True, force_ocr=True, source="redo",
                         hinweis=hinweis, nur_ocr=(modus == "nur_ocr"))
    return {"ok": True, "doc": doc_id, "modus": modus, "hinweis": bool(hinweis), "gestartet": True}


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


@app.get("/einstellungen", response_class=HTMLResponse)
def einstellungen(request: Request):
    guard(request)
    return seite("Einstellungen", "/einstellungen", seiten.einstellungen())


@app.get("/trace/{doc_id}")
def trace_seite(doc_id: int, request: Request):
    """Alte Adresse: der Lauf öffnet sich jetzt als Dialog in der Aktivität."""
    guard(request)
    return RedirectResponse(f"/?doc={int(doc_id)}")


@app.get("/ablauf", response_class=HTMLResponse)
def ablauf_seite(request: Request):
    guard(request)
    return seite("Ablauf & Prompt", "/ablauf", seiten.ablauf())


@app.get("/api/prompt-vorschau")
def api_prompt_vorschau(request: Request):
    """Der fertig eingesetzte Prompt gegen den aktuellen Bestand — von classify.py selbst
    gebaut, damit die Vorschau nie vom tatsaechlich gesendeten Prompt abweicht."""
    guard(request)
    env = dict(os.environ)
    env.update({"CLASSIFY_PROMPT_VORSCHAU": "1", "PAPERLESS_API": BASE, "PAPERLESS_TOKEN": TOK,
                "CLASSIFY_CONFIG": CONFIG, "CLASSIFY_LOG": LOG})
    try:
        r = subprocess.run(["python3", CLASSIFY_PY], env=env, capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)
    except Exception as e:
        raise HTTPException(502, f"Vorschau fehlgeschlagen: {e!r}"[:300])


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
    # Gegen die WIRKSAME Config umwandeln (kennt auch Schlüssel, die nur als Vorgabe existieren),
    # aber nur die geschickten Schlüssel in die Datei schreiben — sonst stünden nach dem ersten
    # Speichern alle Vorgaben fest in der Datei, und eine spätere bessere Vorgabe wirkte nie.
    neu, uebergangen = config_uebernehmen(_cfg_oeffentlich(), body)
    ausgelassen = {u.split(" ", 1)[0] for u in uebergangen}
    datei = _cfg()
    for k in body:
        if k in neu and k not in ausgelassen:
            datei[k] = neu[k]
    schreibe_json(CONFIG, datei)
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


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    guard(request)
    return seite("Aktivität", "/", seiten.aktivitaet())
