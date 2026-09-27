#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paperlaiss — grounded Dokumenten-Klassifizierer für Paperless-ngx (ersetzt paperless-ai).

Läuft als Paperless POST_CONSUME_SCRIPT (oder manuell/per Panel). Mandantenunabhängig:
alle Feld-/Tag-Referenzen werden per NAME gegen die Paperless-API aufgelöst — keine
hartkodierten IDs, keine Secrets im Code (Token/Key kommen aus ENV bzw. der Config).

Features:
  - Korrespondent-Feedback-Loop (Token-Match + Pass-2-LLM-Auflösung, verhindert Dubletten)
  - OCR-Rescue via Mistral-OCR bei schwachem/Müll-Text (+ needs_ocr aus Pass 1)
  - Custom-Field-Voll-Steuerung (Wert / null=leeren / "BEHALTEN"), typgerecht
  - Dokumentdatum-Prüfung (echtes Ausstellungsdatum statt referenzierter Daten)
  - Self-Repair-Loop (Ping-Pong mit dem Paperless-Fehler bis der PATCH sitzt)
  - Trace + Live-Marke fürs Panel

Bewusst NICHT enthalten: Vertrags-/Geräte-Verknüpfung, owner-/Rechte-Setzen
(macht der Paperless-Konsumpfad / post-consume.sh), Steuer-Automatik, Personen-Routing.

Secrets NUR aus ENV/Config: PAPERLESS_TOKEN, MISTRAL_KEY (bzw. config api_key_text/_ocr).

Env-Schalter:
  DOCUMENT_ID / CLASSIFY_DOC   Doc-ID (Post-Consume setzt DOCUMENT_ID)
  CLASSIFY_DRY=1               nur ausgeben, nichts schreiben
  CLASSIFY_FORCE=1             auch schon-klassifizierte (Marker-Tag) neu machen
  CLASSIFY_FORCE_OCR=1         Mistral-OCR erzwingen (+ content immer ersetzen)
  CLASSIFY_NO_OCR=1            OCR komplett aus (günstiger Bestandslauf)
  CLASSIFY_NUR_OCR=1           nur den Text per Mistral-OCR neu lesen, NICHT klassifizieren
  CLASSIFY_HINWEIS=<text>      Freitext des Nutzers, wenn der Anstoss ihn schon gelesen hat
  CLASSIFY_SOURCE=redo|manual|bulk   nur fürs Trace/Log
  CLASSIFY_DUMP_DEFAULTS=1     Default-Prompt/Config als JSON ausgeben (fürs Panel)
  CLASSIFY_PROMPT_VORSCHAU=1   fertig eingesetzten Pass-1-Prompt als JSON ausgeben (fürs Panel)
  CLASSIFY_DUMP_CONFIG=1       wirksame Config (Datei + Vorgaben, ohne Schlüssel) als JSON (fürs Panel)
"""
import os, sys, json, re, unicodedata, urllib.request, urllib.error, difflib, datetime, base64, traceback, tempfile, subprocess

BASE = os.environ.get("PAPERLESS_API", "http://localhost:8000/api")
TOK = os.environ.get("PAPERLESS_TOKEN", "")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_OCR = "https://api.mistral.ai/v1/ocr"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.environ.get("CLASSIFY_LOG", os.path.join(SCRIPT_DIR, "classify.log"))
CONFIG = os.environ.get("CLASSIFY_CONFIG", os.path.join(SCRIPT_DIR, "classify-config.json"))

DRY = os.environ.get("CLASSIFY_DRY") == "1"
FORCE = os.environ.get("CLASSIFY_FORCE") == "1"
FORCE_OCR = os.environ.get("CLASSIFY_FORCE_OCR") == "1"
NO_OCR = os.environ.get("CLASSIFY_NO_OCR") == "1"
NUR_OCR = os.environ.get("CLASSIFY_NUR_OCR") == "1"
SOURCE = os.environ.get("CLASSIFY_SOURCE", "")

# --- Config (vom Panel schreibbar, mit Defaults) ---
CFG = {
    "enabled": True,
    "model": "mistral-small-latest",
    "ocr_model": "mistral-ocr-latest",
    "ocr_enabled": True,
    "ocr_always": False,
    "ocr_min_len": 300,
    "temperature": 0.1,
    "content_max_len": 7000,
    # Defaults:
    "tagging_enabled": False,          # KI vergibt KEINE inhaltlichen Tags (Firmen-DMS: Tags sind manuelle Status/Richtung)
    "marker_tag": "ai-processed",      # gesetzt nach Klassifizierung + Skip-Signal
    "unsicher_tag": "",                # optional: Flag-Tag bei Unsicherheit / KI-Tag-Vorschlag
    "redo_tag": "",                    # optional: Redo-Auslöser-Tag (wird nach Verarbeitung entfernt)
    "ocr_tag": "",                     # optional: Auslöser „nur Text per OCR neu lesen" (Panel entfernt ihn)
    "summary_field": "",               # optional: longtext-Feld für adaptive Zusammenfassung
    "hinweis_field": "",               # optional: Nutzer-Feedback-Feld für Redo (nach Gebrauch geleert)
    "mail_context_field": "",          # optional: Herkunft-Kontext (Mail-/Chat-Anschreiben) fürs Prompt
    "mail_from_field": "",             # optional: Absender-Mail → Korrespondent-Domain-Match
    "manual_fields": [],               # Custom-Field-Namen, die die KI NIE anfasst (rein manuell gepflegt, z.B. Bezahlt-Am)
    "reserved_tags": [],               # Namen, die die KI NIE vergibt + die beim Writeback erhalten bleiben (Status/Quelle/Marker)
    "system_prompt": "",               # leer = DEFAULT_PROMPT
    # Beispielpaare für den Korrespondent-Abgleich (Pass 2), z.B.
    #   [["Mustrmann GmbH", "Mustermann"], ["ACME Vers", "ACME"]]
    # Few-Shot-Beispiele tragen bei OCR-Fehlern mehr als jede Beschreibung — "Mustrmann"
    # → "Mustermann" ist ein Muster, das man zeigen, nicht erklären kann. Sie gehören in die
    # Config und nicht in den Code, weil es echte Namen der jeweiligen Installation sind.
    "korrespondent_beispiele": [],
    # Pfad zu einem Skript, das NACH dem Writeback laeuft — die Naht fuer alles, was zu einer
    # einzelnen Installation gehoert und nicht in einen mandantenneutralen Klassifizierer:
    # Verknuepfungen in ein Fremdsystem, Rechte, hauseigene Sonderregeln. Es bekommt JSON auf
    # stdin und darf scheitern, ohne den Lauf mitzureissen.
    "nachbearbeitung": "",
    "tag_descriptions": {},            # merged über TAG_DESC (nur relevant wenn tagging_enabled)
    "api_key_text": "",                # leer = ENV MISTRAL_KEY
    "api_key_ocr": "",
}
# Fehler beim Laden werden gesammelt und weiter unten protokolliert — hier oben gibt es
# log() noch nicht. Eine kaputte Config darf NICHT still zu Standardwerten fuehren: dann
# faellt der installationsspezifische Prompt weg, manual_fields ist leer, und der Lauf sieht
# aeusserlich normal aus, waehrend er gegen die falsche Taxonomie arbeitet.
_CFG_FEHLER = None
try:
    CFG.update(json.load(open(CONFIG)))
except FileNotFoundError:
    pass                      # keine Config = Standardwerte, das ist der vorgesehene Fall
except Exception as _e:
    _CFG_FEHLER = f"{CONFIG} nicht lesbar ({_e!r}) — es gelten die Standardwerte!"

MODEL = CFG["model"]
OCR_MODEL = CFG["ocr_model"]
_ENV_KEY = os.environ.get("MISTRAL_KEY", "")
KEY_TEXT = CFG.get("api_key_text") or _ENV_KEY
KEY_OCR = CFG.get("api_key_ocr") or _ENV_KEY

# Optionale Panel-Stores (Korrespondent-Hinweise/Aliase/E-Mail-Domains) — fehlen = leer
_STORE_FEHLER = []


def _load_json(name, default):
    """Einen Store laden. Fehlt die Datei, ist das normal — ist sie KAPUTT, ist es ein Befund.

    Ohne die Unterscheidung verschwindet ein gepflegter Korrespondent-Store bei einem einzigen
    Tippfehler lautlos, und die Klassifizierung laeuft ohne Grounding weiter.
    """
    pfad = os.path.join(SCRIPT_DIR, name)
    try:
        v = json.load(open(pfad))
    except FileNotFoundError:
        return default
    except Exception as e:
        _STORE_FEHLER.append(f"{name} nicht lesbar ({e!r}) — wird ignoriert")
        return default
    if not isinstance(v, type(default)):
        _STORE_FEHLER.append(f"{name} hat den falschen Aufbau ({type(v).__name__}) — wird ignoriert")
        return default
    return v
# Korrespondent-Metadaten-Store (im Panel gepflegt), an Paperless-Korrespondenten per ID gebunden:
#   {"<paperless_id>": {email, domains, telefon, adresse, kundennummer, ustid, kontext,
#                        aliase, quelle, extern_id}}
# `ustid` hiess bis 2026-09-21 `uid`. Umbenannt, weil `UID` in vCard (RFC 6350 §6.7.6) der
# globale Datensatzschluessel ist, hier aber die Umsatzsteuer-Identifikationsnummer gemeint
# war — eine stille Kollision, sobald je ein Adressbuch angebunden wird. Alte Stores werden
# beim Lesen weiter verstanden.
CORR_META = _load_json("correspondents.json", {})
for _f in _STORE_FEHLER:
    log(f"STORE: {_f}")


def cmeta(cid):
    m = CORR_META.get(str(cid))
    return m if isinstance(m, dict) else {}


def cfull_hint(c):  # Kontext + harte Kennungen (Kundennr/UID) fürs KI-Grounding
    m = cmeta(c["id"]); parts = []
    if m.get("kontext"):
        parts.append(str(m["kontext"]).strip())
    if m.get("kundennummer"):
        parts.append("Kundennr " + str(m["kundennummer"]).strip())
    ustid = m.get("ustid") or m.get("uid")     # uid = Altname vor 2026-09-21
    if ustid:
        parts.append("UID " + str(ustid).strip())
    return "; ".join(p for p in parts if p)


def calias(c):
    return str(cmeta(c["id"]).get("aliase") or "").strip()


def log(m):
    try:
        with open(LOG, "a") as f:
            f.write(f"{datetime.datetime.now():%F %T} {'DRY ' if DRY else ''}{m}\n")
    except Exception as e:
        # Letzte Instanz: wenn nicht einmal das Log schreibbar ist, nach stderr —
        # das landet im post-consume-Log von Paperless und ist damit auffindbar.
        print(f"classify: Log nicht schreibbar ({e!r}): {m}", file=sys.stderr)


if _CFG_FEHLER:
    log(f"KONFIGURATION: {_CFG_FEHLER}")
    print(f"classify: {_CFG_FEHLER}", file=sys.stderr)

TRACE_DIR = os.path.join(os.path.dirname(LOG), "traces")
RUN_DIR = os.path.join(os.path.dirname(LOG), "running")
TRACE = {}


def schreibe_json(pfad, daten):
    """JSON atomar schreiben: erst in eine Nachbardatei, dann umbenennen.

    `json.dump(d, open(pfad, "w"))` kürzt die Zieldatei sofort auf null; bricht der Vorgang
    danach ab, steht dort eine halbe Datei. Bei einem Trace heisst das: die Panel-Ansicht
    zeigt kaputtes JSON statt des letzten brauchbaren Standes.
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


def save_trace(did, extra=None):
    if DRY or not did:
        return
    try:
        os.makedirs(TRACE_DIR, exist_ok=True)
        t = dict(TRACE); t["id"] = did; t["ts"] = f"{datetime.datetime.now():%F %T}"
        if extra:
            t.update(extra)
        schreibe_json(os.path.join(TRACE_DIR, f"{did}.json"), t)
    except Exception as e:
        # NICHT still verschlucken. Bis 2026-09-21 stand hier `pass` — auf einer Instanz
        # entstanden dadurch ueber zwei Monate keine Traces, ohne dass es jemandem auffiel.
        # Ein Trace ist Diagnose, kein Selbstzweck: faellt er aus, muss man es SEHEN.
        log(f"trace-fail {did}: {e!r}")


def nachbearbeiten(did, patch, erfolg, lesbar):
    """Ein installationseigenes Skript nach dem Writeback aufrufen.

    Warum es das gibt: Ohne diese Naht muss jede Installation, die mehr braucht als
    Klassifizierung — eine Verknuepfung in ein Fremdsystem, eine hauseigene Regel — den
    Klassifizierer forken. Genau so sind vier auseinanderlaufende Staende desselben Codes
    entstanden. Mit der Naht bleibt der Kern ueberall gleich, und das Eigene liegt daneben.

    Das Skript bekommt auf stdin:
      {"doc_id": 915, "erfolg": true, "patch": {…}, "lesbar": {…}, "quelle": "redo",
       "dry": false}
    Es laeuft mit denselben Umgebungsvariablen (PAPERLESS_TOKEN, PAPERLESS_API …), kann also
    selbst die API benutzen. Seine Ausgabe geht ins Log.

    Es darf scheitern: ein Fehler dort wird protokolliert, beendet aber NICHT den Lauf — die
    Klassifizierung ist zu diesem Zeitpunkt bereits geschrieben, und eine Zusatzaufgabe darf
    kein Dokument unklassifiziert zuruecklassen.
    """
    skript = (CFG.get("nachbearbeitung") or "").strip()
    if not skript or DRY:
        return
    if not os.path.exists(skript):
        log(f"nachbearbeitung-fehlt {did}: {skript} nicht gefunden")
        return
    eingabe = json.dumps({"doc_id": int(did), "erfolg": bool(erfolg), "patch": patch,
                          "lesbar": lesbar, "quelle": SOURCE or "auto",
                          "dry": DRY}, ensure_ascii=False)
    try:
        r = subprocess.run([sys.executable, skript], input=eingabe, text=True,
                           capture_output=True, timeout=120, env=os.environ.copy())
        ausgabe = ((r.stdout or "") + (r.stderr or "")).strip().replace("\n", " | ")[:300]
        if r.returncode == 0:
            if ausgabe:
                log(f"nachbearbeitung {did}: {ausgabe}")
        else:
            log(f"nachbearbeitung-fail {did} (exit {r.returncode}): {ausgabe}")
    except subprocess.TimeoutExpired:
        log(f"nachbearbeitung-timeout {did}: {skript} nach 120 s abgebrochen")
    except Exception as e:
        log(f"nachbearbeitung-fail {did}: {e!r}")


def mark_running(did, stage="Start"):
    if DRY or not did:
        return
    try:
        os.makedirs(RUN_DIR, exist_ok=True)
        p = os.path.join(RUN_DIR, f"{did}.json")
        since = json.load(open(p)).get("since") if os.path.exists(p) else f"{datetime.datetime.now():%F %T}"
        schreibe_json(p, {"id": did, "since": since, "stage": stage,
                          "src": "manuell" if (FORCE or FORCE_OCR) else "auto"})
    except Exception as e:
        # Wie beim Trace: ein stilles `pass` laesst die „laeuft gerade"-Anzeige monatelang
        # ausfallen, ohne dass es jemand bemerkt. Ein Lauf scheitert daran NICHT.
        log(f"running-fail {did}: {e!r}")


def unmark_running(did):
    try:
        if did:
            os.remove(os.path.join(RUN_DIR, f"{did}.json"))
    except FileNotFoundError:
        pass                      # nie markiert oder schon weg — kein Befund
    except Exception as e:
        log(f"unrunning-fail {did}: {e!r}")


def set_stage(did, s):
    TRACE["_stage"] = s
    mark_running(did, s)


def get(path, raw=False):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Token {TOK}"})
    r = urllib.request.urlopen(req, timeout=45)
    return r.read() if raw else json.load(r)


def send(path, data, method="PATCH"):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
        headers={"Authorization": f"Token {TOK}", "Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=45))


def mistral_chat(messages, max_tokens=900):
    body = {"model": MODEL, "temperature": CFG["temperature"], "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}, "messages": messages}
    req = urllib.request.Request(MISTRAL_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY_TEXT}", "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=120))
    raw = r["choices"][0]["message"]["content"]
    return json.loads(raw), raw


def mistral(system, user, max_tokens=900):
    return mistral_chat([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens)[0]


def mistral_ocr(did):
    pdf = get(f"/documents/{did}/download/", raw=True)  # Archiv = immer PDF (auch bei Bild-Originalen)
    b64 = base64.b64encode(pdf).decode()
    body = {"model": OCR_MODEL, "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"}}
    req = urllib.request.Request(MISTRAL_OCR, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY_OCR}", "Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=180))
    return "\n\n".join(p.get("markdown", "") for p in resp.get("pages", [])).strip()


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]', ' ', s).strip()


TOKENS = [' der ', 'die ', 'und ', 'fur', 'rechnung', 'datum', 'betrag', 'gmbh', 'fahrzeug',
          'kennzeichen', 'kunde', 'lieferung', 'auftrag', 'sehr', 'geehrt', 'herr', 'frau',
          'strasse', 'nummer', 'gultig', 'summe', 'netto', 'brutto', 'ust']
LEGAL = {"gmbh", "ag", "kg", "ohg", "mbh", "ug", "co", "kgaa", "se", "ev", "ltd", "limited",
         "llc", "inc", "sa", "srl", "sarl", "bv", "og", "gesmbh", "online", "group", "holding",
         "deutschland", "germany", "austria", "oesterreich", "international", "services", "service", "the", "und"}


def ctoks(s):
    return [w for w in norm(s).split() if w and w not in LEGAL]


# Regeln, nach denen ein Text als zu schwach gilt und per OCR neu gelesen wird. Einstellbar
# unter "ocr_regeln" in der Config; fehlende Schluessel nehmen diese Vorgaben.
OCR_REGELN_VORGABE = {
    "min_zeichen": None,              # None = ocr_min_len (aeltere Configs)
    "min_schluesselwoerter": 2,       # so viele Allerweltswoerter muessen vorkommen …
    # Wörtlich, MIT Leerzeichen: ' der ' soll „der" als Wort treffen, nicht „oder" oder „Kinder".
    # (PR #58 hatte sie per strip() gekürzt — die Regel wurde dadurch unbemerkt lockerer.)
    "schluesselwoerter": list(TOKENS),
    "max_zeichen_je_wort": 40,        # … und auf so viele Zeichen mindestens ein echtes Wort
    "max_muell_anteil": 0.25,         # Anteil von Zeichen, die in keinem Text vorkommen (Zeichensalat)
    # Nach Pass 1 (die KI hat den Text gesehen):
    "nach_ki_meldung": True,          # KI meldet needs_ocr → OCR nachholen, Pass 1 wiederholen
    "wenn_kein_typ": False,           # kein Dokumenttyp erkannt → ebenso
    "wenn_kein_korrespondent": False, # kein Korrespondent erkannt → ebenso
}
_NORMALE_ZEICHEN = set(".,:;-–/()[]€$%&+'\"!?#*_@=<>|§°")


def ocr_regeln(cfg):
    r = {**OCR_REGELN_VORGABE, **(cfg.get("ocr_regeln") or {})}
    if r["min_zeichen"] is None:
        r["min_zeichen"] = cfg.get("ocr_min_len", 300)
    return r


def ocr_gruende(content, cfg):
    """Warum der Text vor Pass 1 per OCR neu gelesen werden soll — leer heisst: gar nicht.

    Die Gruende statt eines Ja/Nein, weil genau das im Trace stehen muss: „Text zu kurz"
    fuehrt zu einer anderen Frage als „60 % Zeichensalat".
    """
    r = ocr_regeln(cfg)
    c = (content or "").strip()
    if len(c) < r["min_zeichen"]:
        return [f"zu kurz ({len(c)} < {r['min_zeichen']} Zeichen)"]
    gruende = []
    cl = c.lower()
    treffer = sum(1 for t in r["schluesselwoerter"] if t.strip() and t.lower() in cl)
    if treffer < r["min_schluesselwoerter"]:
        gruende.append(f"zu wenig bekannte Wörter ({treffer} < {r['min_schluesselwoerter']})")
    woerter = re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", c)
    if len(woerter) < len(c) / r["max_zeichen_je_wort"]:
        gruende.append(f"zu wenig Wörter ({len(woerter)} auf {len(c)} Zeichen)")
    sichtbar = [z for z in c if not z.isspace()]
    muell = sum(1 for z in sichtbar if not z.isalnum() and z not in _NORMALE_ZEICHEN)
    if sichtbar and muell / len(sichtbar) > r["max_muell_anteil"]:
        gruende.append(f"Zeichensalat ({muell * 100 // len(sichtbar)} % Sonderzeichen)")
    return gruende


def ocr_nachhol_gruende(prop, cfg):
    """Warum nach Pass 1 doch noch OCR laufen soll: die KI meldet Muell, oder eine Regel greift."""
    r = ocr_regeln(cfg)
    gruende = []
    if r["nach_ki_meldung"] and prop.get("needs_ocr"):
        gruende.append("KI meldet unlesbaren Text")
    if r["wenn_kein_typ"] and not prop.get("document_type"):
        gruende.append("kein Dokumenttyp erkannt")
    if r["wenn_kein_korrespondent"] and not prop.get("correspondent"):
        gruende.append("kein Korrespondent erkannt")
    return gruende


def bad_ocr(content):
    return bool(ocr_gruende(content, CFG))


# Themen-Tag-Beschreibungen (nur relevant wenn tagging_enabled). Primär via Config gepflegt.
TAG_DESC = {}

DEFAULT_PROMPT = (
    "Du klassifizierst ein Dokument für ein Dokumentenarchiv. "
    "Antworte AUSSCHLIESSLICH als gültiges JSON. Deutsch mit echten Umlauten.\n"
    "DOKUMENTTYPEN (wähle GENAU EINEN oder null): {TYPES}\n\n"
    "{TAGBLOCK}"
    "Korrespondent = ABSENDER/Aussteller (Firma/Behörde/Person), NICHT der Archiv-Inhaber selbst. Kurzer gängiger Markenname.\n"
    "JSON-KEYS: document_type (String|null), correspondent (String|null), "
    "korrespondent_kontext (1 kurzer Satz: was ist dieser Absender / welche Dokumente kommen von ihm — nur bei NEUEM Korrespondent, sonst null), "
    "needs_ocr (true wenn Text unbrauchbar/Müll), "
    "fields (Objekt, siehe VERFÜGBARE FELDER). "
    "Ein Feld nur füllen, wenn das Dokument den Wert konkret hergibt — nichts hineinraten; im Zweifel null lassen. "
    "document_date = tatsächliches Ausstellungs-/Erstellungsdatum des Dokuments 'YYYY-MM-DD', NICHT nur im Text erwähnte/referenzierte Daten; null wenn unklar."
)


def is_null(raw):
    return raw is None or (isinstance(raw, str) and raw.strip().lower() in ("", "null", "none", "-", "—", "n/a", "kein", "unbekannt"))


def sel_label(f, val):
    for o in (f.get("extra_data") or {}).get("select_options", []):
        if o.get("id") == val:
            return o.get("label")
    return val


def coerce_field(f, v):
    t = f["data_type"]
    try:
        if t == "integer":
            s = re.sub(r"[^\d-]", "", str(v)); return int(s) if s not in ("", "-") else None
        if t == "float":
            return float(str(v).replace(",", ".").strip())
        if t == "monetary":
            m = re.search(r"\d+[.,]?\d*", str(v)); return "EUR" + m.group(0).replace(",", ".") if m else None
        if t == "boolean":
            return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "ja", "1", "yes", "wahr")
        if t == "date":
            m = re.match(r"\d{4}-\d{2}-\d{2}", str(v).strip()); return m.group(0) if m else None
        if t == "url":
            return str(v).strip()
        if t == "select":
            for o in (f.get("extra_data") or {}).get("select_options", []):
                if norm(str(v)) == norm(o.get("label", "")):
                    return o.get("id")
            return None
        return str(v).strip()
    except (ValueError, TypeError):
        return None


def beispiel_text(paare, max_paare=6):
    """Few-Shot-Beispiele für den Korrespondent-Abgleich als Prompt-Baustein.

    Nimmt [["Mustrmann GmbH", "Mustermann"], …] und macht daraus " (z.B. 'a'='b', …)".
    Unbrauchbare Einträge (falsche Länge, leer, kein Text) werden übergangen statt zu
    scheitern — die Config pflegt ein Mensch, ein Tippfehler dort darf keinen
    Klassifizierungslauf abbrechen.
    """
    gut = []
    for eintrag in (paare or []):
        if not isinstance(eintrag, (list, tuple)) or len(eintrag) != 2:
            continue
        a, b = (str(x).strip() for x in eintrag)
        if a and b:
            gut.append((a, b))
    if not gut:
        return ""
    return " (z.B. " + ", ".join(f"'{a}'='{b}'" for a, b in gut[:max_paare]) + ")"


def fehler_mit_feldnamen(err, cfs, cfields):
    """Paperless-Fehlermeldung so umschreiben, dass Feldnamen darin stehen.

    Bei Custom-Field-Fehlern schlüsselt Paperless nach **Listen-Index** der gesendeten
    `custom_fields`, nicht nach Feld-ID und nicht nach Name — bei Fehlern an Position 2 und 3
    kommt `{"custom_fields": {"1": {…}, "2": {…}}}` zurück. Diesen Text roh an ein Modell zu
    geben und es um Korrektur „mit denselben Feldnamen" zu bitten, kann nicht funktionieren:
    das Modell sieht Zahlen, kennt die gesendete Reihenfolge nicht und rät. Bis 2026-09-21
    endete das regelmäßig damit, dass nach vier Runden ohne Custom Fields gespeichert wurde.

    Gibt den Originaltext zurück, wenn er sich nicht als JSON lesen lässt oder keine
    Index-Schlüssel enthält — eine unverständliche Meldung ist besser als eine falsch geratene.
    """
    try:
        daten = json.loads(err)
    except (ValueError, TypeError):
        return err
    if not isinstance(daten, dict) or "custom_fields" not in daten:
        return err
    cf_fehler = daten["custom_fields"]
    name_je_id = {f["id"]: f["name"] for f in cfields}

    def benenne(idx):
        try:
            fid = cfs[int(idx)]["field"]
        except (ValueError, TypeError, IndexError, KeyError):
            return None
        return name_je_id.get(fid)

    teile = []
    if isinstance(cf_fehler, dict):
        for idx, detail in cf_fehler.items():
            name = benenne(idx)
            teile.append(f"Feld '{name}': {json.dumps(detail, ensure_ascii=False)}" if name
                         else f"Eintrag {idx}: {json.dumps(detail, ensure_ascii=False)}")
    elif isinstance(cf_fehler, list):
        # Listenform: Position = Index, leere Einträge sind fehlerfrei
        for idx, detail in enumerate(cf_fehler):
            if not detail:
                continue
            name = benenne(idx)
            teile.append(f"Feld '{name}': {json.dumps(detail, ensure_ascii=False)}" if name
                         else f"Eintrag {idx}: {json.dumps(detail, ensure_ascii=False)}")
    if not teile:
        return err
    rest = {k: v for k, v in daten.items() if k != "custom_fields"}
    text = " | ".join(teile)
    return f"{text} | weitere: {json.dumps(rest, ensure_ascii=False)}" if rest else text


def _behalten(cfs, cur_vals, fid):
    """Bestehende Feldzuordnung unverändert übernehmen — auch wenn ihr Wert LEER ist.

    Paperless löscht jede Zuordnung, die in der gesendeten `custom_fields`-Liste fehlt. Ein
    Feld mit leerem Wert steht in `cur_vals` als `{fid: None}`: der Schlüssel existiert, der
    Wert ist None. Die frühere Prüfung `cur_vals.get(fid) is not None` konnte beides nicht
    unterscheiden und liess leere Zuordnungen fallen.

    Das traf ausgerechnet die geschützten Felder: ein manuelles Feld wie „Bezahlt-Am", das
    ein post-consume-Skript bewusst LEER anlegt, damit es in der Eingabemaske erscheint,
    verschwand nach dem ersten Klassifizierungslauf wieder. Aufgefallen 2026-09-21 bei einem
    Lauf gegen echte Dokumente im Testbett.
    """
    if fid in cur_vals:
        cfs.append({"field": fid, "value": cur_vals[fid]})
        return True
    return False


def build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds=None):
    """KI-Entscheidung je Feld → custom_fields-Liste.

    Drei Quellen entscheiden über ein Feld, und sie dürfen sich nicht vermischen:
      flds        was die KI vorschlägt (Wert / null / "BEHALTEN")
      skip_fids   Felder, die die KI NICHT setzen darf (manuelle, Mail-Kontext, Hinweis) —
                  ihr bisheriger Wert wird unverändert übernommen
      code_flds   {fid: wert}, was der Klassifizierer SELBST setzt, auch für Felder aus
                  skip_fids. None heißt „Zuordnung entfernen" (Paperless löscht alles, was
                  in der gesendeten Liste fehlt). Eigener Kanal, damit ein halluzinierter
                  Feldname der KI nie ein geschütztes Feld erreichen kann.
    summary_fid wird ausschließlich am Ende angehängt — nie in der Schleife.

    Bis 2026-09-21 warf skip_fids alle drei in einen Topf, der nur „behalten" konnte. Folge:
    das Hinweisfeld wurde nie geleert (der Redo-Trigger feuerte dadurch erneut) und die
    Zusammenfassung landete zweimal in der Liste. Beides in tests/test_classify.py festgehalten.
    """
    code_flds = code_flds or {}
    cfs, flog = [], {}
    for f in cfields:
        fid, name, t = f["id"], f["name"], f["data_type"]
        if fid == summary_fid:
            continue                            # wird unten gesetzt, genau einmal
        if fid in code_flds:                    # der Klassifizierer selbst entscheidet
            v = code_flds[fid]
            if v is None:
                flog[name] = "entfernt"         # nicht anhängen ⇒ Zuordnung fällt weg
            else:
                cfs.append({"field": fid, "value": v}); flog[name] = v
            continue
        if fid in skip_fids or t == "documentlink":
            _behalten(cfs, cur_vals, fid)       # unverändert, auch leer
            continue
        if name not in flds:                    # von KI nicht erwähnt → behalten
            _behalten(cfs, cur_vals, fid)
            continue
        raw = flds[name]
        if isinstance(raw, str) and raw.strip().upper() in ("BEHALTEN", "KEEP"):
            if _behalten(cfs, cur_vals, fid):
                flog[name] = "behalten"
        elif is_null(raw):
            flog[name] = "geleert"
        else:
            v = coerce_field(f, raw)
            if v is not None:
                cfs.append({"field": fid, "value": v}); flog[name] = v
            elif _behalten(cfs, cur_vals, fid):
                flog[name] = "behalten(unparsebar)"
    if summary and summary_fid:
        cfs.append({"field": summary_fid, "value": summary})
    return cfs, flog


def patch_doc(did, patch):
    try:
        send(f"/documents/{did}/", patch, "PATCH")
        return True, None
    except urllib.error.HTTPError as e:
        try:
            return False, e.read().decode("utf-8", "replace")[:900]
        except Exception:
            return False, repr(e)
    except Exception as e:
        return False, repr(e)


def resolve_tag(tagid_by_norm, name):
    return tagid_by_norm.get(norm(name)) if name else None


def summary_aus(prop):
    """Die Zusammenfassung aus der KI-Antwort — auch unter den Schluesseln aelterer Prompts.

    Der eingebaute Prompt verlangt `summary`. Bestandsprompts verlangen `summary_long` bzw.
    `summary_short`, und das Modell haelt sich an den Prompt. Ohne den Rueckfall bleibt das
    Zusammenfassungsfeld bei ihnen still leer (bis 2026-09-27 so im Repo).
    """
    for k in ("summary", "summary_long", "summary_short"):
        v = prop.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def baue_system(tpl, types, taglines):
    """Setzt Typen und Tags in den System-Prompt ein. taglines=None heisst: Tagging aus.

    Zwei Platzhalter fuer die Tags, weil es zwei Generationen von Prompts gibt: {TAGBLOCK}
    (der ganze Block samt Anweisung) und das aeltere {TAGS} (nur die Liste, die Anweisung steht
    im Prompt selbst). Bis 2026-09-27 kannte der Code nur {TAGBLOCK} — ein Prompt mit {TAGS}
    lief weiter, bekam aber still keine Tag-Liste, und die KI vergab keinen einzigen Tag.
    Enthaelt ein Prompt bei aktivem Tagging keinen der beiden, wird der Block angehaengt,
    statt das Tagging wortlos ausfallen zu lassen.
    """
    if taglines is None:
        tagblock = ""
        taglines = ""
    else:
        tagblock = ("TAGS — nutze NUR exakte Namen aus dieser Liste, 1-3 wirklich zutreffende, den spezifischsten:\n"
                    + taglines + "\n"
                    "Wenn WIRKLICH kein Tag passt, gib in new_tags 1-2 kurze Vorschläge (sonst leeres Array). Sonst KEINE Tags erfinden.\n"
                    "JSON zusätzlich: tags (Array bestehender Namen), new_tags (Array).\n\n")
    platz = "{TAGBLOCK}" in tpl or "{TAGS}" in tpl
    system = (tpl.replace("{TYPES}", ", ".join(sorted(types)))
                 .replace("{TAGBLOCK}", tagblock).replace("{TAGS}", taglines))
    if tagblock and not platz:
        system += "\n" + tagblock
    return system


def nur_ocr(did, doc):
    """Nur den Text neu lesen (OCR-Knopf in Paperless) — Metadaten bleiben, wie sie sind.

    Der OCR-Tag geht erst mit dem Ergebnis weg, in DEMSELBEN Schreibvorgang: daran erkennt der
    Knopf, dass der Lauf fertig ist — auch wenn der neue Text dem alten gleicht. Auch bei einem
    Fehler kommt er weg, sonst haengt der Knopf bis zur Zeitueberschreitung.
    """
    content = doc.get("content") or ""
    mark_running(did, "OCR")
    TRACE["trigger"] = "OCR aus Paperless (nur Text)"
    patch = {}
    ocr_name = norm(CFG.get("ocr_tag") or "")
    if ocr_name:
        ocr_id = next((t["id"] for t in get("/tags/?page_size=1000")["results"]
                       if norm(t["name"]) == ocr_name), None)
        if ocr_id in (doc.get("tags") or []):
            patch["tags"] = [t for t in doc["tags"] if t != ocr_id]
    try:
        new = mistral_ocr(did)
    except Exception as e:
        new = ""
        TRACE["ocr"] = {"triggered": True, "grund": "nur Text neu lesen", "error": repr(e)}
        log(f"OCR-neu-fail {did}: {e!r}")
    if len(new) > 40:
        patch["content"] = new
        TRACE["ocr"] = {"triggered": True, "grund": "nur Text neu lesen", "chars": len(new),
                        "vorher": len(content), "excerpt": new[:8000]}
        log(f"OCR-neu {did}: {len(content)} → {len(new)} Zeichen")
    elif "ocr" not in TRACE:
        TRACE["ocr"] = {"triggered": True, "grund": "nur Text neu lesen",
                        "verworfen": f"OCR lieferte nur {len(new)} Zeichen"}
        log(f"OCR-neu-fail {did}: OCR lieferte nur {len(new)} Zeichen, Text bleibt")
    if patch and not DRY:
        send(f"/documents/{did}/", patch, "PATCH")
    TRACE["_stage"] = "fertig"
    save_trace(did)


def typ_setzen(dt_id, bisher, ausdruecklich):
    """Welchen Dokumenttyp schreiben — oder keinen (None).

    Automatisch nur, wenn noch keiner gesetzt ist: den Typ vergeben oft Paperless-Workflows
    („Rechnung erkennen") oder ein Mensch, und die soll ein Hintergrundlauf nicht ueberstimmen.
    Beim ausdruecklichen Neu-Klassifizieren (Knopf in Paperless, Panel) darf die KI ihn aendern —
    genau dafuer drueckt man den Knopf, oft mit dem Hinweis „das ist eine Gutschrift".
    """
    if not dt_id or dt_id == bisher:
        return None
    if bisher and not ausdruecklich:
        return None
    return dt_id


def reservierte_tags(cfg):
    """Tags, die die KI nie vergibt und die beim Schreiben erhalten bleiben (normalisiert):
    die konfigurierten plus Marker-, Unsicher- und Ausloeser-Tag."""
    reserved = {norm(x) for x in (cfg.get("reserved_tags") or [])}
    for extra in (cfg.get("marker_tag"), cfg.get("unsicher_tag"), cfg.get("redo_tag"), cfg.get("ocr_tag")):
        if extra:
            reserved.add(norm(extra))
    return reserved


FELD_ANWEISUNG = (
    "\nFülle im fields-Objekt JEDES unter VERFÜGBARE FELDER gelistete Feld mit GENAU einer Wahl: "
    "(a) korrekter Wert passend zum Typ; (b) null = leeren (Feld trifft sicher nicht zu ODER bestehender Wert ist falsch); "
    "(c) \"BEHALTEN\" = bestehenden Wert unverändert lassen, wenn du unsicher bist. "
    "Bei Auswahl-Feldern exakt ein gelistetes Label. Zusätzlich document_date 'YYYY-MM-DD' = tatsächliches "
    "Dokumentdatum (NICHT nur referenzierte Daten); null wenn unklar. "
    "needs_ocr NUR true, wenn der INHALT wirklich unlesbar ist (Zeichensalat, leer, offensichtlich kaputtes OCR); "
    "bei knappem, aber lesbarem Text (aus dem du Felder extrahieren konntest) IMMER false.")
SUMMARY_ANWEISUNG = (
    "\nGib ausserdem summary = TLDR, Länge an das Dokument angepasst: Rechnung/Beleg/kurzer Bescheid → 1 knapper Satz; "
    "Vertrag/Brief → 2-3 Sätze; langer Bericht → 4-6 Sätze. Keine Floskeln, direkt zur Sache.")


def pass1_system(cfg, types, tags_all, reserved, mit_summary):
    """Der System-Prompt von Pass 1, genau so, wie er an das Modell geht.

    Eine Funktion fuer den Lauf UND die Vorschau im Panel: zeigte die Vorschau einen selbst
    nachgebauten Prompt, saehe man dort etwas anderes als das, was die KI bekommt.
    """
    if cfg.get("tagging_enabled"):
        td = {**TAG_DESC, **(cfg.get("tag_descriptions") or {})}
        taglines = "\n".join(f"- {t['name']}: {td.get(t['name'], t['name'])}"
                             for t in tags_all if norm(t["name"]) not in reserved)
    else:
        taglines = None
    tpl = cfg.get("system_prompt") or DEFAULT_PROMPT
    system = baue_system(tpl, types, taglines)
    if "VERFÜGBARE FELDER" not in system and "VERFUEGBARE FELDER" not in system:
        system += FELD_ANWEISUNG
    if mit_summary:
        system += SUMMARY_ANWEISUNG
    return system


def prompt_vorschau():
    """Fuer das Panel: der fertig eingesetzte System-Prompt gegen den aktuellen Bestand,
    plus die Einstellungen, die den Ablauf steuern. Liest nur, schreibt nichts."""
    types = {t["name"]: t["id"] for t in get("/document_types/?page_size=1000")["results"]}
    tags_all = get("/tags/?page_size=1000")["results"]
    cfields = get("/custom_fields/?page_size=200")["results"]
    summary_fid = resolve_field(cfields, CFG["summary_field"])
    return {
        "system": pass1_system(CFG, types, tags_all, reservierte_tags(CFG), bool(summary_fid)),
        "eigener_prompt": bool(CFG.get("system_prompt")),
        "typen": len(types), "tags": len(tags_all), "felder": len(cfields),
        "ki_felder": [f["name"] for f in cfields
                      if f["id"] != summary_fid and f["name"] not in (CFG.get("manual_fields") or [])
                      and f.get("data_type") != "documentlink"
                      and norm(f["name"]) not in {norm(CFG.get(k) or "") for k in
                                                   ("hinweis_field", "mail_context_field", "mail_from_field")}],
        "einstellungen": {k: CFG.get(k) for k in (
            "model", "ocr_model", "temperature", "content_max_len", "ocr_enabled", "ocr_always",
            "tagging_enabled", "marker_tag", "unsicher_tag", "redo_tag", "summary_field",
            "hinweis_field", "manual_fields", "nachbearbeitung")},
        "ocr_regeln": {k: v for k, v in ocr_regeln(CFG).items() if k != "schluesselwoerter"},
    }


def resolve_field(cfields, name):
    if not name:
        return None
    return next((f["id"] for f in cfields if norm(f["name"]) == norm(name)), None)


def main():
    did = os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID")
    if not did:
        return
    if not TOK:
        # Laut scheitern statt still zurueckzukehren: ein fehlender Token ist ein
        # Konfigurationsfehler, kein ueberspringbares Dokument. Exit 2 macht ihn im
        # post-consume-Log von Paperless sichtbar, statt ihn in einer Logzeile zu begraben.
        log("FEHLER: PAPERLESS_TOKEN nicht gesetzt (ENV)")
        raise SystemExit(2)
    if not CFG["enabled"] and not DRY:
        log(f"skip {did}: Klassifizierer im Panel deaktiviert"); return

    doc = get(f"/documents/{did}/")
    content = doc.get("content") or ""
    title = doc.get("title") or ""
    tag_ids_on = list(doc.get("tags", []))

    if NUR_OCR:
        return nur_ocr(did, doc)

    tags_all = get("/tags/?page_size=1000")["results"]
    tagname_by_id = {t["id"]: t["name"] for t in tags_all}
    tagid_by_norm = {norm(t["name"]): t["id"] for t in tags_all}

    marker_id = resolve_tag(tagid_by_norm, CFG["marker_tag"])
    unsicher_id = resolve_tag(tagid_by_norm, CFG["unsicher_tag"])
    redo_id = resolve_tag(tagid_by_norm, CFG["redo_tag"])

    if marker_id in tag_ids_on and not DRY and not FORCE and not FORCE_OCR:
        log(f"skip {did}: schon klassifiziert (Marker '{CFG['marker_tag']}')"); return
    mark_running(did, "Start")

    reserved = reservierte_tags(CFG)

    # --- OCR-Rescue: schwacher/Müll-Text → Mistral-OCR ---
    ocr_note = ""
    set_stage(did, "OCR-Rescue")
    TRACE["ocr"] = {"triggered": False, "grund": "Text ausreichend"}
    vorher = ocr_gruende(content, CFG)
    ocr_versucht = False
    if CFG["ocr_enabled"] and not NO_OCR and (FORCE_OCR or CFG["ocr_always"] or vorher):
        ocr_versucht = True
        grund = ("neu klassifizieren aus Paperless" if FORCE_OCR and SOURCE == "redo"
                 else "manuell erzwungen" if FORCE_OCR else "immer-OCR" if CFG["ocr_always"]
                 else "; ".join(vorher))
        try:
            new = mistral_ocr(did)
            if FORCE_OCR or CFG["ocr_always"] or len(new) > max(len(content), 40) * 1.1 or (len(content) < 40 and len(new) > 40):
                if not DRY:
                    send(f"/documents/{did}/", {"content": new}, "PATCH")
                content = new; ocr_note = f"OCR-rescue({len(new)})"
                TRACE["ocr"] = {"triggered": True, "grund": grund, "chars": len(new), "excerpt": new[:8000]}
                log(f"OCR-rescue {did}: {len(new)} Zeichen")
            else:
                TRACE["ocr"] = {"triggered": True, "grund": grund, "verworfen": "neuer Text nicht besser", "chars": len(new)}
        except Exception as e:
            TRACE["ocr"] = {"triggered": True, "grund": grund, "error": repr(e)}
            log(f"OCR-rescue-fail {did}: {e!r}")

    if len(content.strip()) < 20:
        log(f"skip {did}: kein Text nach OCR"); return

    types = {t["name"]: t["id"] for t in get("/document_types/?page_size=1000")["results"]}
    corrs = get("/correspondents/?page_size=2000")["results"]
    cfields = get("/custom_fields/?page_size=200")["results"]
    cur_vals = {c["field"]: c.get("value") for c in doc.get("custom_fields", [])}

    summary_fid = resolve_field(cfields, CFG["summary_field"])
    hinweis_fid = resolve_field(cfields, CFG["hinweis_field"])
    mailctx_fid = resolve_field(cfields, CFG["mail_context_field"])
    mailfrom_fid = resolve_field(cfields, CFG["mail_from_field"])
    # Felder, die NICHT von der KI gesteuert werden (behalten): Sonderfelder + manuelle Felder
    manual_fids = {resolve_field(cfields, n) for n in (CFG.get("manual_fields") or [])}
    skip_fids = {x for x in (summary_fid, hinweis_fid, mailctx_fid, mailfrom_fid, *manual_fids) if x}

    _NL = chr(10)
    mail_ktx = (cur_vals.get(mailctx_fid) or "").strip() if mailctx_fid else ""
    mail_from = (cur_vals.get(mailfrom_fid) or "").strip() if mailfrom_fid else ""
    mail_block = ("HERKUNFT-KONTEXT (Nachricht/Anschreiben zu diesem Dokument — für Absender und Einordnung nutzen):" + _NL + mail_ktx + _NL + _NL) if mail_ktx else ""
    TRACE["mail"] = ({"from": mail_from or None, "hat_kontext": bool(mail_ktx)} if (mail_ktx or mail_from) else None)

    # Der Hinweis kann aus zwei Richtungen kommen: aus dem Custom Field (normaler Weg) oder
    # aus der Umgebung. Letzteres braucht der Vorschlagsmodus: dort raeumt der Anstoss Tag und
    # Feld, bevor der Lauf startet — sonst bliebe der Ausloeser bei einem verworfenen Vorschlag
    # stehen. Der gelesene Text wird dabei durchgereicht, damit er nicht verloren geht.
    hinweis = os.environ.get("CLASSIFY_HINWEIS", "").strip()
    if not hinweis and hinweis_fid:
        hinweis = (cur_vals.get(hinweis_fid) or "").strip()
    hint_block = (f"WICHTIGER NUTZER-HINWEIS (was zuletzt falsch war — bitte korrigieren):\n{hinweis}\n\n" if hinweis else "")

    # Korrespondent-Metadaten (Panel-Store, per ID an Paperless gebunden) fürs Prompt
    _c_by_id = {c["id"]: c for c in corrs}
    _c_by_norm = {norm(c["name"]): c for c in corrs}
    def _khint(nm):
        c = _c_by_norm.get(norm(nm)) if nm else None
        return cfull_hint(c) if c else ""
    cname = (_c_by_id.get(doc.get("correspondent")) or {}).get("name") if doc.get("correspondent") else None
    chint = _khint(cname) if cname else ""
    corr_hint_block = f"HINWEIS zum Korrespondenten '{cname}': {chint}\n\n" if chint else ""
    TRACE["corr_hint"] = ({"korrespondent": cname, "hinweis": chint} if chint else None)

    # --- Pass 0: Absender extrahieren → fokussierte Korrespondent-Kandidaten ---
    set_stage(did, "Absender")
    p0_name = ""
    if mail_from:   # Absender-Domain → Korrespondent (aus dem Metadaten-Store: email/domains)
        _dom = mail_from.split("@")[-1].strip().lower().strip(">")
        for c in corrs:
            _m = cmeta(c["id"]); _doms = str(_m.get("domains") or _m.get("email") or "").lower()
            if _doms and _dom and (_dom in _doms or mail_from.lower() in _doms):
                p0_name = c["name"]; break
    if not p0_name:
        try:
            _p0 = mistral('Extrahiere NUR den Absender/Aussteller (Firma/Behörde/Person). Antworte NUR JSON {"correspondent": <Name|null>}.',
                          mail_block + 'TITEL: ' + title + _NL + _NL + 'INHALT:' + _NL + content[:2500], 150)
        except Exception as e:
            log(f"pass0-fail {did}: {e!r}")   # ohne Absender weiter, aber sichtbar
            _p0 = {}
        p0_name = (_p0.get("correspondent") or "").strip()
    kand = []
    if p0_name:
        _at = ctoks(p0_name); _ak = " ".join(_at)
        def _ks(c):
            names = [c["name"]] + [a.strip() for a in calias(c).split(",") if a.strip()]
            best = 0.0
            for nm in names:
                bt = ctoks(nm)
                if not _at or not bt:
                    continue
                ov = len(set(_at) & set(bt)) / min(len(set(_at)), len(set(bt)))
                best = max(best, ov, difflib.SequenceMatcher(None, _ak, " ".join(bt)).ratio())
            return best
        kand = [c for sc, c in sorted(((_ks(c), c) for c in corrs), key=lambda x: -x[0])[:8] if sc >= 0.3]
    def _kalias_c(c):
        a = calias(c)
        return (" (auch: " + a + ")") if a else ""
    kand_lines = _NL.join("- " + c["name"] + _kalias_c(c) + ((" [Kontext: " + cfull_hint(c) + "]") if cfull_hint(c) else "") for c in kand)
    kand_block = (("MÖGLICHE KORRESPONDENTEN (wähle im Feld correspondent GENAU einen dieser Namen; nur wenn wirklich keiner passt einen neuen):" + _NL + kand_lines + _NL + _NL) if kand else "")
    TRACE["pass0"] = {"vorschlag": p0_name, "kandidaten": [c["name"] for c in kand]}
    TRACE["trigger"] = ("Redo mit Nutzer-Hinweis" if hinweis else "Redo aus Paperless" if SOURCE == "redo"
                        else "Bestands-Durchlauf" if SOURCE == "bulk"
                        else "manuell (Panel)" if (FORCE or FORCE_OCR) else "automatisch (Post-Consume)")
    TRACE["hinweis"] = hinweis or None

    # KI-gesteuerte Felder (alles ausser documentlink + den optionalen Sonderfeldern)
    ai_flds = [f for f in cfields if f["id"] not in skip_fids and f["data_type"] != "documentlink"]
    def fspec(f):
        t = f["data_type"]
        if t == "select":
            th = "Auswahl: " + " | ".join(o["label"] for o in (f.get("extra_data") or {}).get("select_options", []))
        else:
            th = {"string": "Text", "longtext": "Text", "integer": "Ganzzahl", "float": "Zahl",
                  "monetary": "Betrag z.B. EUR12.34", "boolean": "true/false", "date": "YYYY-MM-DD", "url": "URL"}.get(t, t)
        cur = cur_vals.get(f["id"]); cur = sel_label(f, cur) if t == "select" else cur
        return f"- {f['name']} ({th}), aktuell: {cur if cur not in (None, '') else '—'}"
    fieldspec = "\n".join(fspec(f) for f in ai_flds)
    meta = (f"METADATEN:\n- Hinzugefügt am: {(doc.get('added') or '')[:10]}\n"
            f"- Aktuelles Dokumentdatum (evtl. falsch): {(doc.get('created') or '')[:10]}\n"
            f"- Originaldateiname: {doc.get('original_file_name') or '—'}\n")

    set_stage(did, "Pass 1")
    system = pass1_system(CFG, types, tags_all, reserved, bool(summary_fid))
    user_msg = (f"{hint_block}{corr_hint_block}{kand_block}{mail_block}{meta}\n"
                f"VERFÜGBARE FELDER (im fields-Objekt je Feld: Wert / null=leeren / \"BEHALTEN\"=unsicher):\n{fieldspec}\n\n"
                f"TITEL: {title}\n\nINHALT:\n{content[:CFG['content_max_len']]}")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
    prop, assistant_raw = mistral_chat(messages, 1200)

    # OCR-Nachlauf: die KI hat den Text gesehen und haelt ihn fuer Muell (oder eine Regel nach
    # Pass 1 greift). Dann einmal per OCR neu lesen und Pass 1 in DERSELBEN Unterhaltung
    # wiederholen. Nur, wenn vor Pass 1 noch kein OCR lief — sonst zahlte man zweimal fuer
    # dasselbe Dokument. (Bis 2026-09-27 stand hier nur eine Meldung: der alte Zweig war
    # unerreichbar, weil er denselben Schalter pruefte, den der Lauf davor immer setzte.)
    nachher = ocr_nachhol_gruende(prop, CFG)
    if nachher:
        TRACE["ocr"]["nach_pass1"] = nachher
    if nachher and not ocr_versucht and CFG["ocr_enabled"] and not NO_OCR:
        set_stage(did, "OCR-Nachlauf")
        try:
            new = mistral_ocr(did)
            if len(new) > 40:
                if not DRY:
                    send(f"/documents/{did}/", {"content": new}, "PATCH")
                content = new
                ocr_note = (ocr_note + " " if ocr_note else "") + f"OCR-nachgeholt({len(new)})"
                TRACE["ocr"].update({"triggered": True, "grund": "nach Pass 1: " + "; ".join(nachher),
                                     "chars": len(new), "excerpt": new[:8000]})
                log(f"OCR-nachgeholt {did}: {'; '.join(nachher)} → {len(new)} Zeichen")
                messages.append({"role": "assistant", "content": assistant_raw})
                messages.append({"role": "user", "content":
                    "Der Text war unbrauchbar. Hier der per OCR neu gelesene INHALT:\n"
                    f"{new[:CFG['content_max_len']]}\n"
                    "Gib die vollständige Analyse (alle Felder, summary, document_date, correspondent, "
                    "tags) mit diesem Text erneut."})
                prop, assistant_raw = mistral_chat(messages, 1200)
            else:
                TRACE["ocr"]["nachlauf_verworfen"] = f"OCR lieferte nur {len(new)} Zeichen"
        except Exception as e:
            TRACE["ocr"]["nachlauf_fehler"] = repr(e)
            log(f"OCR-nachgeholt-fail {did}: {e!r}")
    TRACE["pass1"] = {"system": system, "user": user_msg[:4000], "response": prop}

    # --- Korrespondent-Feedback-Loop ---
    set_stage(did, "Korrespondent")
    corr_name = (prop.get("correspondent") or "").strip()
    corr_id = None; corr_info = "kein"
    if corr_name:
        at = ctoks(corr_name); ak = " ".join(at)
        def cscore(c):
            bt = ctoks(c["name"])
            if not at or not bt:
                return 0.0
            ov = len(set(at) & set(bt)) / min(len(set(at)), len(set(bt)))
            return max(ov, difflib.SequenceMatcher(None, ak, " ".join(bt)).ratio())
        scored = sorted(((cscore(c), c) for c in corrs), key=lambda x: -x[0])
        exact = next((c for s, c in scored if ak and " ".join(ctoks(c["name"])) == ak), None)
        pass2 = None
        if exact:
            corr_id = exact["id"]; corr_info = f"exakt='{exact['name']}'"
        else:
            cands = [c for s, c in scored[:20] if s >= 0.28]
            if cands:
                p2_sys = "Du ordnest einen Absender bestehenden Korrespondenten zu. Antworte NUR JSON {\"match\": <exakter Name aus der Liste> ODER null}."
                bsp_txt = beispiel_text(CFG["korrespondent_beispiele"])
                p2_usr = (f"Vorgeschlagener Absender: '{corr_name}'.\nBestehende Kandidaten: {[c['name'] for c in cands]}.\n"
                          "Welcher bezeichnet DIESELBE Firma/Behörde/Person? Rechtsform/Zusätze (GmbH/AG/OG) egal; "
                          f"auch OCR-/Tippfehler, Abkürzungen und Namensvarianten berücksichtigen{bsp_txt}. "
                          "Nur bei echter Übereinstimmung, sonst null.")
                pick = mistral(p2_sys, p2_usr, 200)
                pass2 = {"system": p2_sys, "user": p2_usr, "response": pick}
                m = pick.get("match")
                if m:
                    for c in cands:
                        if norm(c["name"]) == norm(m):
                            corr_id = c["id"]; corr_info = f"gewählt='{c['name']}'"; break
            if corr_id is None:
                if doc.get("correspondent") and bad_ocr(content):   # kein Halluzinat bei Müll-Text
                    corr_id = doc["correspondent"]; corr_info = "bestehenden behalten (Text unsicher)"
                elif DRY:
                    corr_info = f"NEU='{corr_name}' (dry)"
                else:
                    nc = send("/correspondents/", {"name": corr_name}, "POST")
                    corr_id = nc["id"]; corr_info = f"NEU='{corr_name}'"
        TRACE["correspondent"] = {"vorschlag": corr_name, "ergebnis": corr_info, "pass2": pass2}

    # --- Tags (nur wenn Tagging aktiv) ---
    set_stage(did, "Tags & Schreiben")
    tag_ids, new_tags = [], []
    if CFG["tagging_enabled"]:
        for t in (prop.get("tags") or []):
            tid = tagid_by_norm.get(norm(t))
            if tid and norm(tagname_by_id[tid]) not in reserved:
                tag_ids.append(tid)
        new_tags = [t for t in (prop.get("new_tags") or []) if t and norm(t) not in tagid_by_norm]

    dt = prop.get("document_type")
    dt_id = types.get(dt) or (next((v for k, v in types.items() if norm(k) == norm(dt)), None) if dt else None)
    summary = summary_aus(prop) if summary_fid else ""
    if new_tags and summary_fid:
        summary = (summary + f"\n\n[KI-Tag-Vorschlag: {', '.join(new_tags)}]").strip()

    if DRY:
        out = {"id": did, "correspondent": corr_name, "corr_info": corr_info, "document_type": dt,
               "tags": [tagname_by_id.get(i) for i in tag_ids], "new_tags": new_tags,
               "summary": summary, "fields": prop.get("fields"), "needs_ocr": prop.get("needs_ocr"), "ocr": ocr_note}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        log(f"DRY {did} | {corr_info} | typ={dt} | tags={[tagname_by_id.get(i) for i in tag_ids]} | {ocr_note}")
        return

    # --- Zurückschreiben (KEIN owner/Rechte — macht post-consume.sh) ---
    extra = ([marker_id] if marker_id else []) + ([unsicher_id] if ((new_tags) and unsicher_id) else [])
    keep_tags = tag_ids_on + tag_ids + extra
    patch = {"tags": [t for t in dict.fromkeys(keep_tags) if not (redo_id and t == redo_id)]}
    if corr_id:
        patch["correspondent"] = corr_id
    neuer_typ = typ_setzen(dt_id, doc.get("document_type"), SOURCE in ("redo", "manual"))
    if neuer_typ:
        patch["document_type"] = neuer_typ

    flds = prop.get("fields") or {}
    date_note = None
    dm = re.match(r"(\d{4})-(\d{2})-(\d{2})$", str(flds.get("document_date") or "").strip())
    if dm and 1950 <= int(dm.group(1)) <= 2035 and (doc.get("created") or "")[:10] != dm.group(0):
        patch["created"] = f"{dm.group(0)}T12:00:00+00:00"
        date_note = f"{(doc.get('created') or '?')[:10]} -> {dm.group(0)}"
    code_flds = {}
    if hinweis_fid and hinweis:
        # Nutzer-Hinweis nach Gebrauch entfernen, sonst feuert der Redo-Trigger erneut.
        code_flds[hinweis_fid] = None
    cfs, field_log = build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds)
    patch["custom_fields"] = cfs
    TRACE["writeback"] = {"document_type": dt, "tags": [tagname_by_id.get(i) for i in tag_ids],
                          "new_tags": new_tags, "correspondent": corr_info,
                          "fields_ki": field_log, "summary": summary,
                          "document_date": patch.get("created"), "date_change": date_note}

    ok, err = patch_doc(did, patch)
    TRACE["repair"] = []; rounds = 0
    while not ok and rounds < 4:
        rounds += 1
        set_stage(did, f"Feld-Korrektur {rounds}")
        log(f"patch-fail {did} R{rounds}: {err[:100]}")
        messages.append({"role": "assistant", "content": assistant_raw})
        messages.append({"role": "user", "content":
            f"Beim Speichern nach Paperless kam dieser Fehler:\n{fehler_mit_feldnamen(err, cfs, cfields)}\n"
            "Korrigiere die betroffenen Feldwerte (nicht korrigierbare auf null) und gib NUR das JSON "
            "{\"fields\": {<Feldname>: <Wert|null>}} mit denselben Feldnamen zurück."})
        fix, assistant_raw = mistral_chat(messages, 900)
        flds = {**flds, **(fix.get("fields") or {})}
        cfs, field_log = build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds)
        patch["custom_fields"] = cfs
        prev = err; ok, err = patch_doc(did, patch)
        TRACE["repair"].append({"round": rounds, "error": prev, "correction": fix.get("fields"), "ok": ok, "error_after": None if ok else err})
    TRACE["writeback"]["fields_ki"] = field_log
    repair_note = None
    if rounds:
        repair_note = f"repariert(R{rounds})" if ok else "repair-fehlgeschlagen"
        log(f"repariert {did} nach {rounds} Runde(n)" if ok else f"repair-fehlgeschlagen {did}")
    if not ok:   # nach allen Runden weiter Fehler → wenigstens ohne custom_fields speichern
        patch.pop("custom_fields", None); patch_doc(did, patch)

    log(f"OK {did} | {corr_info} id={corr_id} | typ={dt_id} | tags={[tagname_by_id.get(i) for i in tag_ids]} | new={new_tags} | {ocr_note}" + (f" | {repair_note}" if repair_note else ""))
    nachbearbeiten(did, patch, ok, TRACE.get("writeback") or {})
    TRACE["_stage"] = "fertig"
    save_trace(did)
    unmark_running(did)


# Nur beim direkten Aufruf ausführen (Post-Consume / manuell / Panel). So bleibt das Modul
# importierbar — die Tests prüfen die reinen Hilfsfunktionen, ohne main() oder sys.exit auszulösen.
if __name__ == "__main__":
    if os.environ.get("CLASSIFY_DUMP_CONFIG") == "1":
        wirksam = {k: v for k, v in CFG.items() if not k.startswith("api_key")}
        regeln = ocr_regeln(CFG)
        if (CFG.get("ocr_regeln") or {}).get("min_zeichen") is None:
            # Nicht eigens gesetzt: dann gilt ocr_min_len. Nicht als Wert ausgeben, sonst schriebe
            # ein Speichern im Panel die Zahl fest und ocr_min_len wirkte nie wieder.
            regeln.pop("min_zeichen")
        wirksam["ocr_regeln"] = regeln
        print(json.dumps(wirksam, ensure_ascii=False))
        sys.exit(0)
    if os.environ.get("CLASSIFY_PROMPT_VORSCHAU") == "1":
        print(json.dumps(prompt_vorschau(), ensure_ascii=False))
        sys.exit(0)
    if os.environ.get("CLASSIFY_DUMP_DEFAULTS") == "1":
        print(json.dumps({"system_prompt": DEFAULT_PROMPT, "tag_descriptions": TAG_DESC,
                          "model": CFG["model"], "ocr_model": CFG["ocr_model"], "ocr_min_len": CFG["ocr_min_len"],
                          "temperature": CFG["temperature"], "content_max_len": CFG["content_max_len"],
                          "ocr_always": CFG["ocr_always"], "tagging_enabled": CFG["tagging_enabled"]}, ensure_ascii=False))
        sys.exit(0)

    try:
        main()
    except Exception as e:
        eid = os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID") or "?"
        log(f"FEHLER {eid} | " + repr(e) + " | " + traceback.format_exc().replace("\n", " ")[:600])
        save_trace(None if eid == "?" else eid, {"error": repr(e), "traceback": traceback.format_exc()[:1500]})
    finally:
        unmark_running(os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID"))
    sys.exit(0)
