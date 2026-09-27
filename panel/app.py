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
  EXPORT_*        Export-Knopf: EXPORT_MAX_DOKUMENTE (1000), EXPORT_MAX_MB (2000), EXPORT_AUFBEWAHRUNG_MIN
                  (20), EXPORT_SPEICHER_MB (10000, alle fertigen zusammen), EXPORT_PARALLEL (1), EXPORT_TMP; PAPERLESS_PUBLIC_URL für die Links nach Paperless
"""
import os, sys, json, re, glob, html, hmac, secrets, shutil, subprocess, datetime, tempfile, threading, time, traceback
import urllib.request, urllib.error, zoneinfo
from fastapi import BackgroundTasks, Body, FastAPI, Request, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from kern import (KORR_FELDER, sperre_oeffnen, korr_anzeige, knopf_annehmen, knopf_fortschritt, aktivitaet, auffaelligkeiten, auth_einstellungen, knopf_rechte, korr_eintrag,
                  config_uebernehmen, doc_id_aus_webhook, feld_typ, verlauf)
import exportlogik
import exportpdf
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

    Rechte und Besitzer bleiben wie in classify.schreibe_json (2026-09-27): alte Datei als
    Vorbild, sonst der Ordner — ein Lauf als root sperrt den Worker nicht mehr aus.
    """
    ordner = os.path.dirname(os.path.abspath(pfad)) or "."
    try:
        vorbild, bestand = os.stat(pfad), True
    except FileNotFoundError:
        vorbild, bestand = os.stat(ordner), False
    fd, tmp = tempfile.mkstemp(dir=ordner, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if bestand:
            os.chmod(tmp, vorbild.st_mode & 0o777)
        try:
            os.chown(tmp, vorbild.st_uid, vorbild.st_gid)   # nur als root wirksam
        except PermissionError:
            pass
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
def run_classify(doc, force=True, force_ocr=False, source="manual", hinweis=""):
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


# ---------- KI-Knopf und Korrespondenten-Abschnitt in Paperless ----------
# Die Knöpfe (deploy/paperless-knoepfe/) rufen das Panel DIREKT, ohne Tag, Feld und Workflow.
# Wer drückt, ist in Paperless angemeldet: sein Browser schickt die Paperless-Sitzung mit, und
# das Panel fragt damit bei Paperless nach, welche Dokumente dieser Nutzer ändern darf. Nur die
# werden verarbeitet — mit dem eigenen Token des Panels, aber nie über die Rechte des Nutzers
# hinaus.
KNOPF_ORIGINS = [o.strip().rstrip("/") for o in (os.environ.get("PAPERLAISS_KNOPF_ORIGIN") or "").split(",")
                 if o.strip()]
if KNOPF_ORIGINS:
    # Nur nötig, wenn Paperless und Panel NICHT unter derselben Adresse laufen (Testbett mit
    # zwei Ports). Mit Reverse-Proxy (Paperless /, Panel /paperlaiss) ist alles gleicher Ursprung.
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=KNOPF_ORIGINS, allow_credentials=True,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Paperlaiss"])
JOBS = {}          # doc_id → {"status": wartet|laeuft|fertig|fehler, "seit"}
_JOBS_LOCK = threading.Lock()


def _job(doc, **felder):
    with _JOBS_LOCK:
        JOBS.setdefault(doc, {}).update(felder)


def knopf_lauf(doc, hinweis):
    with PARALLEL:
        _job(doc, status="laeuft")
        rc, _ = run_classify(doc, force=True, force_ocr=True, source="knopf", hinweis=hinweis)
    _job(doc, status="fertig" if rc == 0 else "fehler")


def knopf_nutzer_rechte(request: Request, ids, art="documents"):
    """(erlaubt, verweigert) für den Nutzer, dessen Paperless-Sitzung die Anfrage trägt.

    `art` ist der Paperless-Endpunkt (documents, correspondents) — beide liefern `user_can_change`.
    """
    antwort = als_nutzer(request, f"/{art}/?id__in={','.join(str(i) for i in ids)}"
                                  f"&fields=id,user_can_change&page_size={len(ids)}")
    return knopf_rechte(antwort, ids)


def _knopf_sitzung(request: Request) -> str:
    """Die Paperless-Sitzung eines Knopf-Aufrufs (Cookie) — nach der Prüfung des eigenen Kopfs."""
    # Der eigene Kopf erzwingt beim Aufruf von einer fremden Seite eine CORS-Vorabfrage — die
    # nur freigegebene Paperless-Adressen bestehen. Ein blosses Formular kann ihn nicht setzen.
    if request.headers.get("x-paperlaiss") != "1":
        raise HTTPException(400, "Aufruf nur über die paperlaiss-Knöpfe")
    cookie = request.headers.get("cookie", "")
    if not cookie:
        raise HTTPException(401, "Keine Paperless-Sitzung — in Paperless anmelden")
    return cookie


def als_nutzer(request: Request, pfad, tolerant=False):
    """GET gegen Paperless MIT der Sitzung des Nutzers: Paperless antwortet nur mit dem, was er sehen
    darf. `tolerant`: fehlendes Recht auf eine Liste (403, etwa keine Korrespondenten sehen) ergibt
    eine leere Antwort statt eines Abbruchs — die Sitzung selbst ist dann schon geprüft."""
    cookie = _knopf_sitzung(request)
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(
            BASE + pfad, headers={"Cookie": cookie, "Accept": "application/json"}), timeout=20))
    except urllib.error.HTTPError as e:
        if tolerant and e.code == 403:
            return {"results": []}
        raise HTTPException(401 if e.code in (401, 403) else 502,
                            "Paperless kennt diese Sitzung nicht — in Paperless anmelden")


def _ids(werte):
    ids = sorted({int(x) for x in werte if str(x).strip().isdigit()})
    if not ids or len(ids) > 500:
        raise HTTPException(400, "1 bis 500 Dokument-IDs nötig")
    return ids


@app.post("/knopf", status_code=202)
async def knopf(request: Request, hintergrund: BackgroundTasks):
    """KI-Knopf: neu klassifizieren, immer mit Mistral-OCR, optional mit Hinweis."""
    body = await request.json()
    ids = _ids(body.get("docs") or [])
    hinweis = str(body.get("hinweis") or "").strip()[:2000]
    erlaubt, verweigert = knopf_nutzer_rechte(request, ids)
    # Prüfen und Belegen unter derselben Sperre: zwei gleichzeitige Klicks starten sonst beide.
    with _JOBS_LOCK:
        starten, schon = knopf_annehmen(JOBS, erlaubt)
        for doc in starten:
            JOBS.setdefault(doc, {}).update(status="wartet", seit=datetime.datetime.now().isoformat(timespec="seconds"))
    for doc in starten:
        hintergrund.add_task(knopf_lauf, doc, hinweis)
    return {"gestartet": starten, "laeuft_schon": schon, "verweigert": verweigert}


_KORR_LOCK = threading.Lock()


def _korr_store():
    try:
        d = json.load(open(CORR_STORE, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}


@app.get("/knopf/korrespondent/{cid}")
def korr_lesen(cid: int, request: Request):
    """Adressbuch-Eintrag für den paperlaiss-Abschnitt im Korrespondenten-Dialog von Paperless."""
    erlaubt, _ = knopf_nutzer_rechte(request, [cid], art="correspondents")
    return {"felder": [list(f) for f in KORR_FELDER], "werte": korr_anzeige(_korr_store().get(str(cid), {})),
            "darf_aendern": bool(erlaubt)}


@app.post("/knopf/korrespondent/{cid}")
async def korr_schreiben(cid: int, request: Request):
    erlaubt, _ = knopf_nutzer_rechte(request, [cid], art="correspondents")
    if not erlaubt:
        raise HTTPException(403, "Diesen Korrespondenten darfst du in Paperless nicht ändern")
    eingabe = await request.json()
    import fcntl
    # Dieselbe Sperre wie classify.py (stammdaten_schreiben): beide schreiben correspondents.json.
    with _KORR_LOCK, sperre_oeffnen(CORR_STORE + ".lock") as sperre:
        fcntl.flock(sperre, fcntl.LOCK_EX)
        store = _korr_store()
        eintrag = korr_eintrag(store.get(str(cid)), eingabe)
        if eintrag:
            store[str(cid)] = eintrag
        else:
            store.pop(str(cid), None)
        schreibe_json(CORR_STORE, store)
    return {"ok": True, "werte": eintrag}


@app.get("/knopf/status")
def knopf_status(request: Request, docs: str = ""):
    ids = _ids(docs.split(","))
    erlaubt, _ = knopf_nutzer_rechte(request, ids)
    with _JOBS_LOCK:
        status = {d: JOBS.get(d, {}).get("status", "unbekannt") for d in erlaubt}
    aus = {}
    for d, st in status.items():
        stufe = None
        if st == "laeuft":
            try:
                stufe = json.load(open(os.path.join(RUN_DIR, f"{d}.json"))).get("stage")
            except (OSError, ValueError):
                pass
        aus[str(d)] = knopf_fortschritt(st, stufe)
    return aus


# ---------- Export-Knopf: ein PDF oder einzeln (optional ZIP), mit Inhaltsverzeichnis ----------
# Rechte wie beim KI-Knopf, nur genügt hier LESEN: das Panel fragt mit der Paperless-Sitzung des
# Nutzers nach, und ein Dokument, das er nicht sehen darf, lehnt den ganzen Export ab — nicht still
# weglassen. Auch die Namen (Korrespondent, Typ, Felder) kommen über seine Sitzung; heruntergeladen
# werden die PDFs mit dem Token des Panels. Die Entscheidungen stehen getestet in exportlogik.py.
def _env_zahl(name, vorgabe):
    wert = (os.environ.get(name) or "").strip()
    return int(wert) if wert.isdigit() and int(wert) > 0 else vorgabe


EXPORT_MAX_DOKUMENTE = _env_zahl("EXPORT_MAX_DOKUMENTE", 1000)
EXPORT_MAX_MB = _env_zahl("EXPORT_MAX_MB", 2000)
EXPORT_AUFBEWAHRUNG = _env_zahl("EXPORT_AUFBEWAHRUNG_MIN", 20) * 60     # PO 2026-09-27: 20 min
EXPORT_SPEICHER_MB = _env_zahl("EXPORT_SPEICHER_MB", 10000)   # alle fertigen Exporte zusammen
EXPORT_TMP = os.environ.get("EXPORT_TMP") or tempfile.gettempdir()
EXPORT_PRAEFIX = "paperlaiss-export-"
EXPORT_WARTESCHLANGE = 5            # offene Exporte (wartend + laufend), danach 429
PAPERLESS_PUBLIC_URL = os.environ.get("PAPERLESS_PUBLIC_URL", "")
EXPORT_PARALLEL = threading.BoundedSemaphore(_env_zahl("EXPORT_PARALLEL", 1))
EXPORT_FELDER = ("id,title,correspondent,document_type,created,added,archive_serial_number,custom_fields,"
                 "archived_file_name,original_file_name,mime_type,page_count")
EXPORTE = {}       # job → {"status": wartet|laeuft|fertig|fehler, "docs", "ordner", "dateien", …}
_EXPORT_LOCK = threading.Lock()


def _jetzt():
    """Uhrzeit für Dateiname und Verzeichnis — in der Zeitzone von Paperless (PAPERLESS_TIME_ZONE),
    sonst TZ; der Container selbst läuft oft in UTC."""
    zone = (os.environ.get("PAPERLESS_TIME_ZONE") or os.environ.get("TZ") or "").strip()
    try:
        return datetime.datetime.now(zoneinfo.ZoneInfo(zone)) if zone else datetime.datetime.now().astimezone()
    except Exception:
        return datetime.datetime.now().astimezone()


class ExportAbbruch(Exception):
    """Ein Grund, den ganzen Export abzubrechen — mit einer Meldung für den Nutzer."""


def _export(job, **felder):
    with _EXPORT_LOCK:
        if job in EXPORTE:
            EXPORTE[job].update(felder)


def _export_entfernen(job):
    with _EXPORT_LOCK:
        j = EXPORTE.pop(job, None)
    if j and j.get("ordner"):
        shutil.rmtree(j["ordner"], ignore_errors=True)


def _export_aufraeumen():
    """Abgelaufene Exporte samt Dateien löschen (zusätzlich zum Zeitgeber je Export)."""
    frist = time.time() - EXPORT_AUFBEWAHRUNG
    with _EXPORT_LOCK:
        alt = [k for k, j in EXPORTE.items() if j["status"] in ("fertig", "fehler") and j.get("ende", j["seit"]) < frist]
    for k in alt:
        _export_entfernen(k)


def _export_speicher_begrenzen():
    """Liegen mehr fertige Exporte auf der Platte als EXPORT_SPEICHER_MB, die ältesten löschen."""
    with _EXPORT_LOCK:
        fertige = [(k, j.get("ende", j["seit"]), sum(g for _, _, g in j.get("dateien") or []))
                   for k, j in EXPORTE.items() if j["status"] == "fertig"]
    for k in exportlogik.speicher_ueberlauf(fertige, EXPORT_SPEICHER_MB * 1024 * 1024):
        _export_entfernen(k)


def _export_waisen_entfernen():
    """Beim Start: Exportordner eines früheren Prozesses gehören niemandem mehr."""
    for p in glob.glob(os.path.join(EXPORT_TMP, EXPORT_PRAEFIX + "*")):
        shutil.rmtree(p, ignore_errors=True)


_export_waisen_entfernen()


def export_lesbar(request: Request, ids, felder="id"):
    """Die Dokumente, die der Nutzer lesen darf (mit den gewünschten Feldern), und die übrigen."""
    antwort = als_nutzer(request, f"/documents/?id__in={','.join(str(i) for i in ids)}"
                                  f"&fields={felder}&page_size={len(ids)}")
    lesbar, verweigert = exportlogik.lese_rechte(antwort, ids)
    nach_id = {int(d["id"]): d for d in antwort.get("results", [])}
    return [nach_id[i] for i in lesbar], verweigert


def _verweigert_meldung(verweigert):
    return (f"Kein Leserecht in Paperless für {len(verweigert)} Dokument(e) "
            f"({', '.join(str(i) for i in verweigert[:20])}) — Export abgelehnt")


def export_namen(request: Request, doks):
    """Korrespondenten, Typen und benutzerdefinierte Felder — mit der Sitzung des Nutzers, damit
    kein Name im Export landet, den er in Paperless nicht sehen darf."""
    def liste(art, ids=None):
        if ids is not None and not ids:
            return []
        filter_ = f"id__in={','.join(str(i) for i in sorted(ids))}&" if ids else ""
        return als_nutzer(request, f"/{art}/?{filter_}page_size=100000", tolerant=True).get("results", [])
    korr = {d["correspondent"] for d in doks if d.get("correspondent")}
    typen = {d["document_type"] for d in doks if d.get("document_type")}
    return {"korrespondenten": {k["id"]: k.get("name", "") for k in liste("correspondents", korr)},
            "typen": {t["id"]: t.get("name", "") for t in liste("document_types", typen)},
            "felder": {f["id"]: f for f in liste("custom_fields")}}


@app.get("/knopf/export/optionen")
def export_optionen(request: Request):
    """Was der Export-Dialog anbietet: Variablen, benutzerdefinierte Felder, Grenzen."""
    als_nutzer(request, "/ui_settings/")                     # prüft die Sitzung
    felder = als_nutzer(request, "/custom_fields/?page_size=100000", tolerant=True).get("results", [])
    return {"variablen": [list(v) for v in exportlogik.VARIABLEN],
            "felder": sorted({f.get("name", "") for f in felder if f.get("name")}, key=str.casefold),
            "vorlage": exportlogik.VORLAGE_STANDARD,
            "grenzen": {"dokumente": EXPORT_MAX_DOKUMENTE, "mb": EXPORT_MAX_MB,
                        "aufbewahrung_min": EXPORT_AUFBEWAHRUNG // 60}}


@app.post("/knopf/export", status_code=202)
def export_starten(request: Request, hintergrund: BackgroundTasks, body: dict = Body(...)):
    """Export starten; läuft als Auftrag, Stand über GET /knopf/export/<job>."""
    _knopf_sitzung(request)                     # Kopf und Sitzung zuerst, vor jeder Prüfung des Auftrags
    auftrag, fehler = exportlogik.export_auftrag(body, max_dokumente=EXPORT_MAX_DOKUMENTE)
    if fehler:
        raise HTTPException(400, "; ".join(fehler))
    doks, verweigert = export_lesbar(request, auftrag["docs"], EXPORT_FELDER)
    if verweigert:
        raise HTTPException(403, _verweigert_meldung(verweigert))
    namen = export_namen(request, doks)
    feldnamen = [f.get("name", "") for f in namen["felder"].values()]
    if auftrag["art"] == "einzeln":
        fehler += exportlogik.vorlage_fehler(auftrag["vorlage"], feldnamen)
    s = auftrag["sortierung"]
    if s.lower().startswith(exportlogik.FELD) and exportlogik._feld_finden(s[len(exportlogik.FELD):].strip(), feldnamen) is None:
        fehler.append(f"Sortierung: benutzerdefiniertes Feld {s[len(exportlogik.FELD):].strip()!r} gibt es nicht")
    if fehler:
        raise HTTPException(400, "; ".join(fehler))
    basis = exportlogik.paperless_basis(PAPERLESS_PUBLIC_URL, request.headers.get("origin", ""), auftrag["basis"])
    _export_aufraeumen()
    with _EXPORT_LOCK:
        if sum(1 for j in EXPORTE.values() if j["status"] in ("wartet", "laeuft")) >= EXPORT_WARTESCHLANGE:
            raise HTTPException(429, "Zu viele Exporte gleichzeitig — bitte gleich noch einmal versuchen")
        job = secrets.token_urlsafe(18)
        EXPORTE[job] = {"status": "wartet", "docs": auftrag["docs"], "gesamt": len(doks), "fertig": 0,
                        "schritt": "wartet auf einen freien Platz", "meldung": "", "seit": time.time(),
                        "dateien": [], "uebersprungen": [], "ordner": None}
    hintergrund.add_task(export_lauf, job, auftrag, doks, namen, basis)
    return {"job": job, "anzahl": len(doks)}


def _pdf_laden(doc_id, original, pfad, summe, grenze):
    """Ein PDF mit dem Token des Panels herunterladen, in Blöcken, mit laufender Größengrenze.
    Rückgabe: neue Gesamtgröße. Kein PDF oder ein HTTP-Fehler: ValueError (Dokument überspringen)."""
    url = f"{BASE}/documents/{int(doc_id)}/download/" + ("?original=true" if original else "")
    kopf = b""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Token {TOK}"}),
                                    timeout=120) as r, open(pfad, "wb") as f:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                if len(kopf) < 1024:
                    kopf += block[:1024]
                summe += len(block)
                zu_gross = exportlogik.groesse_fehler(summe, grenze)
                if zu_gross:
                    raise ExportAbbruch(zu_gross)
                f.write(block)
    except urllib.error.HTTPError as e:
        raise ValueError(f"Paperless lieferte die Datei nicht (HTTP {e.code})")
    if b"%PDF-" not in kopf[:1024]:
        raise ValueError("Paperless lieferte kein PDF")
    return summe


def export_lauf(job, auftrag, doks, namen, basis):
    ordner = tempfile.mkdtemp(prefix=EXPORT_PRAEFIX, dir=EXPORT_TMP)
    _export(job, ordner=ordner)
    fehlen = []

    def uebersprungen():
        return [{"id": e["werte"]["id"], "titel": e["werte"]["titel"], "grund": e["grund"]} for e in fehlen]
    try:
        with EXPORT_PARALLEL:
            _export(job, status="laeuft", schritt="Dokumente laden")
            eintraege = []
            for d in doks:
                e = exportlogik.dokument_variablen(d, namen)
                e["dok"] = d
                eintraege.append(e)
            eintraege = exportlogik.sortieren(eintraege, auftrag["sortierung"], auftrag["absteigend"])
            enthalten, summe = [], 0
            for i, e in enumerate(eintraege):
                _export(job, fertig=i, schritt=f"Dokument {i + 1} von {len(eintraege)} laden")
                quelle, grund = exportlogik.pdf_quelle(e["dok"])
                if not quelle:
                    e["grund"] = grund
                    fehlen.append(e)
                    continue
                pfad = os.path.join(ordner, f"quelle-{int(e['werte']['id'])}.pdf")
                try:
                    summe = _pdf_laden(e["werte"]["id"], quelle == "original", pfad, summe, EXPORT_MAX_MB * 1024 * 1024)
                    e["seitenzahl"], e["outline_ok"] = exportpdf.pdf_pruefen(pfad)
                except ValueError as ex:
                    e["grund"] = str(ex)
                    fehlen.append(e)
                    continue
                e["pfad"] = pfad
                enthalten.append(e)
            _export(job, fertig=len(eintraege), uebersprungen=uebersprungen(), schritt="PDF zusammenstellen")
            if not enthalten:
                raise ExportAbbruch("Keines der gewählten Dokumente hat ein PDF")
            jetzt = _jetzt()
            seiten_gesamt = sum(e["seitenzahl"] for e in enthalten)
            unterzeile = (f"{len(enthalten)} Dokument{'e' if len(enthalten) != 1 else ''} · {seiten_gesamt} Seiten"
                          + (f" · {len(fehlen)} nicht enthalten" if fehlen else "")
                          + f" · erstellt {jetzt:%Y-%m-%d %H:%M} mit paperlaiss")
            stempel = jetzt.strftime("%Y-%m-%d %H%M")
            if auftrag["art"] == "ein":
                ziel = os.path.join(ordner, "export.pdf")
                exportpdf.ein_pdf(enthalten, fehlen, basis, ziel, inhalt=auftrag["inhalt"],
                                  mit_seitenzahlen=auftrag["seitenzahlen"], kopf="Inhaltsverzeichnis",
                                  unterzeile=unterzeile)
                dateien = [(exportlogik.export_dateiname("pdf", len(enthalten), stempel), ziel)]
            else:
                inhalt_name = (exportlogik.inhalt_dateiname(auftrag["nummerieren"], len(enthalten))
                               if auftrag["inhalt"] else None)
                namen_liste = exportlogik.dateinamen(enthalten, auftrag["vorlage"], auftrag["nummerieren"], inhalt_name)
                dateien = exportpdf.einzeln(
                    enthalten, fehlen, namen_liste, basis, ordner, inhalt=auftrag["inhalt"], inhalt_name=inhalt_name,
                    zip_name=(exportlogik.export_dateiname("zip", len(enthalten), stempel) if auftrag["zip"] else None),
                    kopf="Inhaltsverzeichnis", unterzeile=unterzeile)
            for e in enthalten:                         # Quellen, die nicht selbst Ergebnis sind
                if os.path.exists(e["pfad"]):
                    os.unlink(e["pfad"])
            _export(job, status="fertig", schritt="fertig", ende=time.time(),
                    dateien=[(n, p, os.path.getsize(p)) for n, p in dateien])
            _export_speicher_begrenzen()
    except ExportAbbruch as ex:
        _export(job, status="fehler", meldung=str(ex), uebersprungen=uebersprungen(), ende=time.time())
        shutil.rmtree(ordner, ignore_errors=True)
    except Exception as ex:
        traceback.print_exc()
        _export(job, status="fehler", meldung=f"Export fehlgeschlagen ({ex.__class__.__name__}) — Protokoll des Panels",
                uebersprungen=uebersprungen(), ende=time.time())
        shutil.rmtree(ordner, ignore_errors=True)
    # Aufräumen auch ohne weitere Anfrage: nach der Aufbewahrungszeit sind Auftrag und Dateien weg.
    t = threading.Timer(EXPORT_AUFBEWAHRUNG, _export_entfernen, [job])
    t.daemon = True
    t.start()


def _export_job(job: str, request: Request):
    """Den Auftrag holen — nur für eine Sitzung, die alle seine Dokumente (noch) lesen darf."""
    _knopf_sitzung(request)             # zuerst: ohne Sitzung verrät auch 404/200 nichts über Aufträge
    with _EXPORT_LOCK:
        j = dict(EXPORTE.get(job) or {}) if re.fullmatch(r"[A-Za-z0-9_-]{16,64}", job) else {}
    if not j:
        raise HTTPException(404, "Export unbekannt oder abgelaufen")
    _, verweigert = export_lesbar(request, j["docs"])
    if verweigert:
        raise HTTPException(403, _verweigert_meldung(verweigert))
    return j


@app.get("/knopf/export/{job}")
def export_status(job: str, request: Request):
    _export_aufraeumen()
    j = _export_job(job, request)
    return {"status": j["status"], "gesamt": j["gesamt"], "fertig": j["fertig"], "schritt": j["schritt"],
            "meldung": j["meldung"], "uebersprungen": j["uebersprungen"],
            "dateien": [{"name": n, "groesse": g} for n, _, g in j["dateien"]],
            "aufbewahrung_min": EXPORT_AUFBEWAHRUNG // 60}


@app.get("/knopf/export/{job}/datei/{nr}")
def export_datei(job: str, nr: int, request: Request):
    j = _export_job(job, request)
    if j["status"] != "fertig":
        raise HTTPException(409, "Export ist noch nicht fertig")
    if not 0 <= nr < len(j["dateien"]):
        raise HTTPException(404, "Keine solche Datei")
    name, pfad, _ = j["dateien"][nr]
    if not os.path.isfile(pfad):
        raise HTTPException(410, "Export abgelaufen — bitte neu exportieren")
    return FileResponse(pfad, filename=name,
                        media_type="application/zip" if name.endswith(".zip") else "application/pdf")


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


@app.get("/info", response_class=HTMLResponse)
def info_seite(request: Request):
    guard(request)
    return seite("Info", "/info", seiten.info())


@app.get("/einstellungen", response_class=HTMLResponse)
def einstellungen(request: Request):
    guard(request)
    return seite("Einstellungen", "/einstellungen", seiten.einstellungen())


@app.get("/trace/{doc_id}")
def trace_seite(doc_id: int, request: Request):
    """Alte Adresse: der Lauf öffnet sich jetzt als Dialog in der Aktivität."""
    guard(request)
    return RedirectResponse(huelle.u(f"/?doc={int(doc_id)}"))


@app.get("/ablauf", response_class=HTMLResponse)
def ablauf_seite(request: Request):
    guard(request)
    return seite("Ablauf & Prompt", "/ablauf", seiten.ablauf())


def _prompt_vorschau(entwurf: str | None = None):
    env = dict(os.environ)
    env.update({"CLASSIFY_PROMPT_VORSCHAU": "1", "PAPERLESS_API": BASE, "PAPERLESS_TOKEN": TOK,
                "CLASSIFY_CONFIG": CONFIG, "CLASSIFY_LOG": LOG})
    env.pop("CLASSIFY_PROMPT_ENTWURF", None)
    if entwurf is not None:
        env["CLASSIFY_PROMPT_ENTWURF"] = entwurf
    try:
        r = subprocess.run(["python3", CLASSIFY_PY], env=env, capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)
    except Exception as e:
        raise HTTPException(502, f"Vorschau fehlgeschlagen: {e!r}"[:300])


@app.get("/api/prompt-vorschau")
def api_prompt_vorschau(request: Request):
    """Der fertig eingesetzte Prompt gegen den aktuellen Bestand — von classify.py selbst
    gebaut, damit die Vorschau nie vom tatsaechlich gesendeten Prompt abweicht."""
    guard(request)
    return _prompt_vorschau()


@app.post("/api/prompt-vorschau")
async def api_prompt_entwurf(request: Request):
    """Live-Vorschau beim Bearbeiten: derselbe Weg mit dem noch nicht gespeicherten Prompt.
    Schreibt nichts."""
    guard(request)
    try:
        entwurf = (await request.json()).get("system_prompt")
    except Exception:
        raise HTTPException(400, "JSON mit system_prompt erwartet")
    if not isinstance(entwurf, str) or len(entwurf) > 50000:
        raise HTTPException(400, "system_prompt muss Text (bis 50000 Zeichen) sein")
    return _prompt_vorschau(entwurf)


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
